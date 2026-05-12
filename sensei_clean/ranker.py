from __future__ import annotations

from .schemas import ActionRecord, ItemRecord


def score_item(item: ItemRecord) -> int:
    impact = min(40, max(0, int(item.size_bytes / (1024 * 1024 * 10))))
    confidence_bonus = int(item.confidence * 20)
    reversibility_bonus = 20 if item.reversible_actions else 0
    return min(100, item.risk + impact + confidence_bonus + reversibility_bonus)


def score_action(action: ActionRecord) -> int:
    reversible_bonus = 15 if action.reversible else 0
    confidence_bonus = int(action.confidence * 20)
    return min(100, action.risk + confidence_bonus + reversible_bonus)
