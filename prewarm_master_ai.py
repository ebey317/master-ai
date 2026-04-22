#!/usr/bin/env python3
"""Minimal prewarm — just ensure master-ai weights are loaded in RAM.

Reverted 2026-04-21 evening to the simple pattern that worked before.
The "real-shape" prewarm (behavior + memory injection) timed out even
at 300s on Skylake CPU. Too much for the hardware. This script just
loads the model weights and sets keep_alive — nothing clever.
"""
import json
import urllib.request


def main():
    # Standard prewarm sentence (2026-04-21) — identity-anchoring, short.
    # "ok" loaded weights but didn't lock the Sensei role; the new sentence
    # gets the model into character on first token, so Sensei's actual first
    # user turn finds master-ai already in the right voice.
    payload = {
        "model": "master-ai",
        "prompt": "You are Sensei. Reply with the single word: ready.",
        "stream": False,
        "keep_alive": "30m",
    }
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=300).read()
    except Exception as e:
        print(f"prewarm failed: {e}")
        raise SystemExit(0)


if __name__ == "__main__":
    main()
