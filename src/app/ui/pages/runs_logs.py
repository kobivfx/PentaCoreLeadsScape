"""Runs & Logs page."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem,
    QPlainTextEdit, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QGroupBox,
)

from ...core.db import DatabaseManager


class RunsLogsPage(QWidget):
    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self._db = db
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel("Runs & Logs")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #1e1e2e;")
        layout.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # Top: runs table
        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)

        self.runs_table = QTableWidget()
        self.runs_table.setColumnCount(6)
        self.runs_table.setHorizontalHeaderLabels(["Run ID", "Started", "Finished", "Status", "Stats", "Error"])
        self.runs_table.horizontalHeader().setStretchLastSection(True)
        self.runs_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.runs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.runs_table.setAlternatingRowColors(True)
        self.runs_table.setColumnWidth(0, 130)
        self.runs_table.setColumnWidth(1, 170)
        self.runs_table.setColumnWidth(2, 170)
        self.runs_table.setColumnWidth(3, 90)
        self.runs_table.currentCellChanged.connect(self._on_run_selected)
        top_layout.addWidget(self.runs_table)
        splitter.addWidget(top)

        # Bottom: log viewer + run details
        bottom = QWidget()
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        # Log content
        log_group = QGroupBox("Log File Content")
        log_lay = QVBoxLayout(log_group)
        self.log_viewer = QPlainTextEdit()
        self.log_viewer.setReadOnly(True)
        self.log_viewer.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_viewer.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        log_lay.addWidget(self.log_viewer)
        bottom_layout.addWidget(log_group, 2)

        # Stats detail
        stats_group = QGroupBox("Run Details")
        stats_lay = QVBoxLayout(stats_group)
        self.stats_viewer = QPlainTextEdit()
        self.stats_viewer.setReadOnly(True)
        stats_lay.addWidget(self.stats_viewer)
        bottom_layout.addWidget(stats_group, 1)

        splitter.addWidget(bottom)
        splitter.setSizes([300, 400])
        layout.addWidget(splitter)

    def _on_run_selected(self, row, col, prev_row, prev_col):
        runs = self._db.get_runs()
        if 0 <= row < len(runs):
            run = runs[row]

            # Stats
            try:
                stats = json.loads(run.stats_json) if run.stats_json else {}
                lines = [f"Run ID: {run.run_id}", f"Status: {run.status}",
                         f"Started: {run.started_at}", f"Finished: {run.finished_at or '–'}"]
                for k, v in stats.items():
                    if k == "errors" and isinstance(v, list):
                        lines.append(f"\nErrors ({len(v)}):")
                        for e in v:
                            lines.append(f"  • {e}")
                    else:
                        lines.append(f"{k}: {v}")
                self.stats_viewer.setPlainText("\n".join(lines))
            except Exception:
                self.stats_viewer.setPlainText(run.stats_json)

            # Log file
            if run.log_path:
                log_path = Path(run.log_path)
                if log_path.exists():
                    try:
                        content = log_path.read_text(encoding="utf-8", errors="replace")
                        self.log_viewer.setPlainText(content[-50000:])  # Last 50K chars
                    except Exception as e:
                        self.log_viewer.setPlainText(f"Error reading log: {e}")
                else:
                    self.log_viewer.setPlainText(f"Log file not found: {run.log_path}")
            else:
                self.log_viewer.setPlainText("No log file for this run.")

    def refresh(self):
        runs = self._db.get_runs(limit=100)
        self.runs_table.setRowCount(len(runs))
        for i, r in enumerate(runs):
            self.runs_table.setItem(i, 0, QTableWidgetItem(r.run_id))
            self.runs_table.setItem(i, 1, QTableWidgetItem(r.started_at[:19] if r.started_at else ""))
            self.runs_table.setItem(i, 2, QTableWidgetItem(r.finished_at[:19] if r.finished_at else ""))

            status_item = QTableWidgetItem(r.status)
            color_map = {"success": "#a6e3a1", "failed": "#f38ba8",
                         "partial": "#f9e2af", "cancelled": "#fab387", "running": "#89b4fa"}
            c = color_map.get(r.status, "#ccc")
            from PySide6.QtGui import QColor
            status_item.setBackground(QColor(c))
            self.runs_table.setItem(i, 3, status_item)

            try:
                stats = json.loads(r.stats_json) if r.stats_json else {}
                summary = f"raw={stats.get('raw_items', 0)} new={stats.get('leads_new', 0)} scored={stats.get('scored', 0)}"
            except Exception:
                summary = ""
            self.runs_table.setItem(i, 4, QTableWidgetItem(summary))
            self.runs_table.setItem(i, 5, QTableWidgetItem(r.error[:100] if r.error else ""))
