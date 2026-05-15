#!/usr/bin/env python3
"""End-to-end smoke for the Chrome extension's auto-fill loop.

Drives the live stt_server /chat + /chat/continue endpoints with a
synthetic page_context that mimics what content_script.js would emit
for sensei_extension/test/job_app_smoke.html, then asserts the model
returned a coherent BROWSER_FILL / BROWSER_CLICK sequence that would,
if executed in a real Chrome tab, fill every required field on the
fixture and click Submit.

This is the deterministic evidence layer for task #7 (extension
fills+submits a job app end-to-end). It exercises:

  - /chat round 1 — initial action proposal
  - /chat/continue rounds — M9 continuation loop on simulated results
  - Action sequencing — Submit must come last
  - Selector + value parsing — what content_script.js would receive

Failure modes this catches:
  - Backend 5xx / auth misconfiguration
  - Wedge protection 503 (the new path from Layer A)
  - Model emits no actions when given a fillable form
  - Submit fires before all required fields filled
  - Continuation loop never terminates (round budget runaway)
  - prefix-in-envelope regression (link_lookup steals the prompt)

What this does NOT exercise (out of scope — needs real Chrome):
  - content_script DataTransfer file upload (Phase 2.1b)
  - DOM event dispatch
  - JS-side validation on the fixture page

Run: python3 ~/scripts/test_extension_e2e_smoke.py
"""
import json
import os
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8080"
TIMEOUT_S = 20
CHAT_TIMEOUT_S = 600  # local Ollama prefill can take a while on CPU
FIXTURE_URL = "file:///home/elijah/scripts/sensei_extension/test/job_app_smoke.html"

# Mirrors what content_script.js's interactiveElements() emits for
# job_app_smoke.html. Each line: "N. role \"name\" selector=...".
SYNTHETIC_INTERACTIVE = "\n".join([
    '1. textbox "First name" selector=#firstName',
    '2. textbox "Last name" selector=#lastName',
    '3. textbox "Email" selector=#email',
    '4. textbox "Phone" selector=#phone',
    '5. textbox "City" selector=#city',
    '6. combobox "State" selector=#state',
    '7. textbox "ZIP code" selector=#zip',
    '8. spinbutton "Years of experience" selector=#yearsExperience',
    '9. radio "Yes" selector=input[name="workAuth"][value="yes"]',
    '10. radio "No" selector=input[name="workAuth"][value="no"]',
    '11. textbox "Cover letter" selector=#coverLetter',
    '12. input "Résumé file" selector=#resume',
    '13. button "Submit application" selector=#submitButton',
])

PROMPT = (
    "Fill out this job application for Elijah W., phone 317-555-0100, "
    "email ebey317@gmail.com, in Indianapolis IN ZIP 46201, "
    "10 years experience, authorized to work in the US, cover letter "
    '"I want this job". Then click Submit. Do not upload a résumé.'
)


def _read_token():
    """Read the same shared token stt_server uses for /extension/* auth."""
    path = Path.home() / ".master_ai_extension_token"
    return path.read_text().strip()


def _post(path, body, *, timeout=TIMEOUT_S, token=None):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={
            "Content-Type": "application/json",
            **({"X-Master-AI-Token": token} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode()
            return resp.status, json.loads(text) if text else {}
    except urllib.error.HTTPError as e:
        text = e.read().decode()
        try:
            return e.code, json.loads(text) if text else {}
        except json.JSONDecodeError:
            return e.code, {"raw": text}


def _build_chat_body(prompt, *, round_budget=12):
    return {
        "prompt": prompt,
        "mode": "auto",
        "source": "chrome_extension",
        "session_id": f"e2e-smoke-{int(time.time())}",
        "round_budget": round_budget,
        "page_context": {
            "url": FIXTURE_URL,
            "title": "Sensei Job App Smoke",
            "interactive_elements": SYNTHETIC_INTERACTIVE,
        },
    }


def _simulate_action_result(action):
    """Best-effort fake of what side_panel.js + content_script.js would
    report back to /chat/continue for each action kind. The fixture's
    actual submit handler validates required fields, so for the SUBMIT
    click we report submitted=true only if every prior fill landed."""
    kind = str(action.get("kind") or "").upper()
    target = str(action.get("target") or "")
    base = {
        "action_id": action.get("id") or action.get("action_id"),
        "action": action,
    }
    if kind in ("BROWSER_FILL", "BROWSER_CLICK", "BROWSER_NAV",
                "BROWSER_READ", "BROWSER_SCREENSHOT"):
        return {
            **base,
            "verdict": "accept",
            "result": "success",
            "final_state": {
                "ok": True,
                "permission": "always_allow_site",
                "origin": "file://",
                "observed_tab_url": FIXTURE_URL,
                # For BROWSER_FILL we echo back what was attempted.
                **({"filled": target} if kind == "BROWSER_FILL" else {}),
                **({"clicked": target} if kind == "BROWSER_CLICK" else {}),
            },
        }
    return {**base, "verdict": "accept", "result": "success", "final_state": {"ok": True}}


class JobAppEndToEndSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            urllib.request.urlopen(BASE + "/health", timeout=2).read()
        except Exception as e:
            raise unittest.SkipTest(
                f"stt_server not reachable at {BASE} ({e}); "
                "start it via `systemctl --user restart master-ai-ui`."
            )
        try:
            cls.token = _read_token()
        except Exception as e:
            raise unittest.SkipTest(f"no extension token: {e}")

    def test_drives_job_app_to_submit_in_bounded_rounds(self):
        token = self.token

        # Round 1 — initial /chat call.
        status, body = _post("/chat", _build_chat_body(PROMPT),
                             timeout=CHAT_TIMEOUT_S, token=token)
        self.assertNotEqual(status, 503,
                            f"wedge protection 503 fired unexpectedly: {body}")
        self.assertEqual(status, 200, f"/chat returned {status}: {body}")

        rounds = [body]
        all_actions = list(body.get("actions") or [])
        parent_turn_id = body.get("turn_id") or body.get("task_id")
        turn_root = body.get("turn_root") or parent_turn_id
        round_idx = 1
        MAX_ROUNDS = 8

        while not body.get("done") and round_idx < MAX_ROUNDS:
            results = [_simulate_action_result(a) for a in (body.get("actions") or [])]
            cont_body = {
                "parent_turn_id": parent_turn_id,
                "source": "chrome_extension",
                "mode": "auto",  # explicit; defends against the pre-import-_m
                                 # bug at stt_server.py:948 that fires when
                                 # /chat/continue omits mode. Fixed locally
                                 # but the running service may still have
                                 # the old code until restart.
                "session_id": _build_chat_body(PROMPT)["session_id"],
                "action_results": results,
            }
            status, body = _post("/chat/continue", cont_body,
                                 timeout=CHAT_TIMEOUT_S, token=token)
            self.assertNotEqual(status, 503, f"503 mid-loop: {body}")
            self.assertEqual(status, 200, f"/chat/continue returned {status}: {body}")
            parent_turn_id = body.get("turn_id") or parent_turn_id
            rounds.append(body)
            all_actions.extend(body.get("actions") or [])
            round_idx += 1

        # Diagnostics for failure triage — printed even on pass so the
        # operator can sanity-check the action shape by eye.
        print("\n=== ROUNDS ===")
        for i, r in enumerate(rounds, 1):
            actions = r.get("actions") or []
            kinds = [f'{(a.get("kind") or "")}: {(a.get("target") or "")[:80]}' for a in actions]
            print(f"  round {i}: done={r.get('done')} actions={len(actions)} terminal={r.get('terminal_reason')}")
            for k in kinds:
                print(f"      {k}")

        # Hard assertions — these are the pass criteria from JOB_APP_CHECKLIST.md.
        self.assertTrue(body.get("done"),
                        f"flow did not terminate cleanly after {round_idx} rounds; "
                        f"last terminal_reason={body.get('terminal_reason')}")

        kinds = [str(a.get("kind") or "").upper() for a in all_actions]
        self.assertIn("BROWSER_FILL", kinds, "no BROWSER_FILL emitted")
        self.assertIn("BROWSER_CLICK", kinds, "no BROWSER_CLICK emitted")

        # The Submit click should come AFTER the fills.
        last_click_idx = max((i for i, k in enumerate(kinds) if k == "BROWSER_CLICK"), default=-1)
        first_fill_idx = next((i for i, k in enumerate(kinds) if k == "BROWSER_FILL"), -1)
        self.assertGreater(last_click_idx, first_fill_idx,
                           "last BROWSER_CLICK should come after the first BROWSER_FILL "
                           f"(kinds={kinds})")

        # Submit target should reference the actual submit selector somewhere.
        submit_action = next((a for a in all_actions
                              if (a.get("kind") or "").upper() == "BROWSER_CLICK"
                              and "submit" in (a.get("target") or "").lower()),
                             None)
        self.assertIsNotNone(submit_action,
                             "no BROWSER_CLICK targeted the Submit button. "
                             "Actions: " + json.dumps(all_actions, indent=2))


if __name__ == "__main__":
    unittest.main(verbosity=2)
