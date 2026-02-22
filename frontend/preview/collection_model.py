"""
Öğe listesi (mevcut klasör veya arama). next/prev, jump_to.
"""
from __future__ import annotations

from typing import Any


class CollectionModel:
    """Gezinilebilir öğe listesi."""

    def __init__(self, items: list[dict[str, Any]], current_index: int = 0):
        self._items = list(items)
        self._current_index = max(0, min(current_index, len(self._items) - 1)) if self._items else 0

    def __len__(self) -> int:
        return len(self._items)

    @property
    def current_index(self) -> int:
        return self._current_index

    @current_index.setter
    def current_index(self, value: int) -> None:
        if self._items:
            self._current_index = max(0, min(value, len(self._items) - 1))
        else:
            self._current_index = 0

    def get_current(self) -> dict[str, Any] | None:
        """Mevcut öğe."""
        if not self._items or self._current_index < 0 or self._current_index >= len(self._items):
            return None
        return self._items[self._current_index]

    def next_index(self) -> int | None:
        """Sonraki indeks."""
        if not self._items or self._current_index >= len(self._items) - 1:
            return None
        return self._current_index + 1

    def prev_index(self) -> int | None:
        """Önceki indeks."""
        if not self._items or self._current_index <= 0:
            return None
        return self._current_index - 1

    def next(self) -> dict[str, Any] | None:
        """Sonrakine geç."""
        ni = self.next_index()
        if ni is None:
            return None
        self._current_index = ni
        return self.get_current()

    def prev(self) -> dict[str, Any] | None:
        """Öncekine geç."""
        pi = self.prev_index()
        if pi is None:
            return None
        self._current_index = pi
        return self.get_current()

    def jump_to(self, index: int) -> dict[str, Any] | None:
        """İndekse git."""
        if not self._items:
            return None
        self._current_index = max(0, min(index, len(self._items) - 1))
        return self.get_current()

    def get_item_at(self, index: int) -> dict[str, Any] | None:
        """İndeksteki öğe."""
        if not self._items or index < 0 or index >= len(self._items):
            return None
        return self._items[index]

    def items(self) -> list[dict[str, Any]]:
        """Öğe listesi."""
        return self._items
