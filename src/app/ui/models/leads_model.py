"""Paginated Qt table model for leads."""
from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from ...core.db import DatabaseManager
from ...core.models import Lead

COLUMNS = [
    ("is_starred", "★"),
    ("status", "Status"),
    ("auto_score", "Score"),
    ("manual_score", "M.Score"),
    ("lead_type", "Type"),
    ("title", "Title"),
    ("source", "Source"),
    ("author", "Author"),
    ("client_name", "Client"),
    ("keyword_group_id", "Group"),
    ("keyword_used", "Keyword"),
    ("prefilter_result", "Prefilter"),
    ("scoring_provider", "Scored By"),
    ("last_seen_at", "Last Seen"),
]


class LeadsTableModel(QAbstractTableModel):
    """Paginated model backed by SQLite queries."""

    PAGE_SIZE = 100

    # Map column keys to allowed SQL order expressions
    _SORTABLE = {
        "auto_score": "auto_score",
        "manual_score": "manual_score",
        "last_seen_at": "last_seen_at",
        "title": "title",
    }

    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self._db = db
        self._leads: list[Lead] = []
        self._total = 0
        self._page = 0
        self._filters: dict[str, Any] = {}
        self._order_by = "last_seen_at DESC"

    # -- Public API --------------------------------------------------------
    def set_filters(self, **kwargs):
        self._filters = {k: v for k, v in kwargs.items() if v is not None and v != ""}
        self._page = 0
        self.refresh()

    def set_order(self, order_by: str):
        self._order_by = order_by
        self.refresh()

    def next_page(self):
        if (self._page + 1) * self.PAGE_SIZE < self._total:
            self._page += 1
            self.refresh()

    def prev_page(self):
        if self._page > 0:
            self._page -= 1
            self.refresh()

    def goto_page(self, page: int):
        self._page = max(0, page)
        self.refresh()

    @property
    def page(self) -> int:
        return self._page

    @property
    def total_pages(self) -> int:
        return max(1, (self._total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)

    @property
    def total_count(self) -> int:
        return self._total

    def get_lead_at(self, row: int) -> Lead | None:
        if 0 <= row < len(self._leads):
            return self._leads[row]
        return None

    def refresh(self):
        self.beginResetModel()
        self._total = self._db.count_leads(
            **{k: v for k, v in self._filters.items() if k in ("status", "source", "lead_type", "prefilter_result")}
        )
        self._leads = self._db.get_leads(
            offset=self._page * self.PAGE_SIZE,
            limit=self.PAGE_SIZE,
            order_by=self._order_by,
            **self._filters,
        )
        self.endResetModel()

    # -- Qt Model interface ------------------------------------------------
    def rowCount(self, parent=QModelIndex()):
        return len(self._leads)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        lead = self._leads[index.row()]
        col_key = COLUMNS[index.column()][0]

        if role == Qt.ItemDataRole.DisplayRole:
            val = getattr(lead, col_key, "")
            if col_key == "is_starred":
                return "★" if val else ""
            if col_key == "manual_score":
                return str(val) if val is not None else ""
            if col_key == "title":
                return str(val)[:100]
            if col_key == "last_seen_at":
                return str(val)[:19] if val else ""
            return str(val) if val is not None else ""

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col_key in ("auto_score", "manual_score", "is_starred"):
                return Qt.AlignmentFlag.AlignCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        if role == Qt.ItemDataRole.UserRole:
            return lead.lead_id

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section][1]
        return None

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder):
        col_key = COLUMNS[column][0]
        sql_col = self._SORTABLE.get(col_key)
        if not sql_col:
            return
        direction = "ASC" if order == Qt.SortOrder.AscendingOrder else "DESC"
        self._order_by = f"{sql_col} {direction}"
        self._page = 0
        self.refresh()
