"""Bounded, session/page-scoped registry for verified element locators."""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict


@dataclass
class ElementRecord:
    session_id: str
    page_id: str
    frame_id: str
    locator: str
    fingerprint: Dict[str, str]
    expires_at: float


class ElementRegistry:
    """LRU registry storing locator strings and immutable identity only."""

    def __init__(self, per_page: int = 512, per_session: int = 1000, ttl: int = 600):
        self.per_page = per_page
        self.per_session = per_session
        self.ttl = ttl
        self._records: "OrderedDict[str, ElementRecord]" = OrderedDict()
        self._next_id = 1

    def register(
        self,
        session_id: str,
        page_id: str,
        frame_id: str,
        locator: str,
        fingerprint: Dict[str, str],
    ) -> str:
        self._purge_expired()
        short_id = self._base36(self._next_id)
        self._next_id += 1
        handle = f"surf:e1:{page_id}:{short_id}"
        self._records[handle] = ElementRecord(
            session_id=session_id,
            page_id=page_id,
            frame_id=str(frame_id),
            locator=locator,
            fingerprint=fingerprint,
            expires_at=time.monotonic() + self.ttl,
        )
        self._enforce_limits(session_id, page_id)
        return handle

    def get(self, handle: str, session_id: str, page_id: str) -> ElementRecord:
        self._purge_expired()
        record = self._records.get(handle)
        if not record or record.session_id != session_id or record.page_id != page_id:
            raise ValueError("Unknown or stale element handle")
        self._records.move_to_end(handle)
        return record

    def evict_page(self, session_id: str, page_id: str) -> None:
        self._remove_where(lambda r: r.session_id == session_id and r.page_id == page_id)

    def evict_session(self, session_id: str) -> None:
        self._remove_where(lambda r: r.session_id == session_id)

    def _purge_expired(self) -> None:
        now = time.monotonic()
        self._remove_where(lambda r: r.expires_at <= now)

    def _remove_where(self, predicate) -> None:
        for handle in [key for key, value in self._records.items() if predicate(value)]:
            self._records.pop(handle, None)

    def _enforce_limits(self, session_id: str, page_id: str) -> None:
        def count(match) -> int:
            return sum(1 for record in self._records.values() if match(record))

        while count(lambda r: r.session_id == session_id and r.page_id == page_id) > self.per_page:
            self._pop_oldest(lambda r: r.session_id == session_id and r.page_id == page_id)
        while count(lambda r: r.session_id == session_id) > self.per_session:
            self._pop_oldest(lambda r: r.session_id == session_id)

    def _pop_oldest(self, predicate) -> None:
        for handle, record in self._records.items():
            if predicate(record):
                self._records.pop(handle)
                return

    @staticmethod
    def _base36(value: int) -> str:
        alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
        result = ""
        while value:
            value, remainder = divmod(value, 36)
            result = alphabet[remainder] + result
        return result or "0"


element_registry = ElementRegistry()
