from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .schemas import ActionRecord, CapabilityReport, FindingRecord, ItemRecord


def write_jsonl(path: str, records: Iterable[object]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=True) + "\n")


def write_summary(
    path: str,
    capabilities: list[CapabilityReport],
    items: list[ItemRecord],
    findings: list[FindingRecord],
    actions: list[ActionRecord],
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Sensei Scan Summary",
        "",
        f"- Adapters: {len(capabilities)}",
        f"- Items: {len(items)}",
        f"- Findings: {len(findings)}",
        f"- Actions: {len(actions)}",
        f"- Preview index: previews.md",
        "",
        "## Adapters",
    ]
    for capability in capabilities:
        lines.append(
            f"- {capability.adapter}: capability={capability.capability} available={capability.available} blockers={','.join(capability.blockers) or 'none'}"
        )
    if findings:
        lines.extend(["", "## Findings"])
        for finding in findings[:50]:
            lines.append(f"- {finding.summary} risk={finding.risk} ids={', '.join(finding.item_ids[:4])}")
    if actions:
        lines.extend(["", "## Planned Actions"])
        for action in actions[:100]:
            lines.append(
                f"- {action.action_type} lane={action.lane} from `{action.source_path}` to `{action.destination_path}`"
            )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
