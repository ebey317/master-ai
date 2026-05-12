from __future__ import annotations

from .schemas import ActionRecord, CapabilityReport, ItemRecord


MONITORED_SENSITIVITIES = {"private", "financial", "medical", "identity", "credential", "career"}


def allowed_actions(capability: str, sensitivity: str) -> list[str]:
    if capability == "api":
        return ["scan", "enrich", "organize"]
    if capability == "local":
        return ["scan", "enrich", "archive_move", "quarantine_move"]
    if capability == "export":
        return ["scan", "enrich", "archive_move"]
    if capability == "browser":
        return ["scan", "export"]
    return []


def requires_monitored_review(item: ItemRecord, capability: str) -> bool:
    if capability == "browser":
        return True
    if item.sensitivity in MONITORED_SENSITIVITIES:
        return True
    if item.confidence < 0.75:
        return True
    return False


def can_apply(capability: CapabilityReport, action: ActionRecord) -> bool:
    if not capability.available:
        return False
    if action.action_type == "delete":
        return False
    return action.action_type in allowed_actions(capability.capability, action.metadata.get("sensitivity", "unknown"))
