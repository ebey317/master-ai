from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator, List, Optional

from ..schemas import AccessGrant, ActionRecord, ApplyResult, CapabilityReport, ItemRecord, UndoRecord


class BaseAdapter(ABC):
    name: str

    @abstractmethod
    def probe(self) -> CapabilityReport:
        raise NotImplementedError

    @abstractmethod
    def authorize(self, mode: str) -> AccessGrant:
        raise NotImplementedError

    @abstractmethod
    def scan(self, cursor: Optional[str] = None) -> Iterator[ItemRecord]:
        raise NotImplementedError

    @abstractmethod
    def enrich(self, item: ItemRecord, jobs: List[str]) -> ItemRecord:
        raise NotImplementedError

    @abstractmethod
    def can_apply(self, action: ActionRecord) -> bool:
        raise NotImplementedError

    @abstractmethod
    def apply(self, action: ActionRecord) -> ApplyResult:
        raise NotImplementedError

    @abstractmethod
    def undo(self, undo_record: UndoRecord) -> ApplyResult:
        raise NotImplementedError
