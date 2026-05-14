"""Actors (Apify Connectors) management page."""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSplitter,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...core.db import DatabaseManager
from ...core.models import Actor
from ..widgets.common import JsonEditor


class ActorsPage(QWidget):
    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self._db = db
        self._current_actor: Actor | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Global readability stylesheet
        self.setStyleSheet("""
            QGroupBox {
                margin-top: 12px;
                padding: 14px 12px 12px 12px;
                font-weight: bold;
                font-size: 13px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                padding: 0 6px;
            }
            QLabel { margin-right: 4px; }
            QLineEdit, QComboBox {
                padding: 4px 6px;
                min-height: 28px;
            }
        """)

        header = QLabel("Actors (Apify Connectors)")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #1e1e2e;")
        header.setMaximumHeight(36)
        layout.addWidget(header)

        # Button row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_add = QPushButton("+ New Actor")
        btn_add.setStyleSheet("background: #a6e3a1; color: #1e1e2e; border: none; padding: 8px 16px; border-radius: 4px; font-weight: bold;")
        btn_add.clicked.connect(self._new_actor)
        btn_row.addWidget(btn_add)

        btn_del = QPushButton("Delete Selected")
        btn_del.setStyleSheet("background: #f38ba8; color: white; border: none; padding: 8px 16px; border-radius: 4px;")
        btn_del.clicked.connect(self._delete_actor)
        btn_row.addWidget(btn_del)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Splitter: list + editor
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Actor list (left – fixed)
        self.actor_list = QListWidget()
        self.actor_list.setMaximumWidth(280)
        self.actor_list.setMinimumWidth(180)
        self.actor_list.currentRowChanged.connect(self._on_actor_selected)
        splitter.addWidget(self.actor_list)

        # Right panel inside a scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(8, 0, 0, 0)
        editor_layout.setSpacing(14)

        # ── Actor Configuration ───────────────────────────────
        form_group = QGroupBox("Actor Configuration")
        form = QFormLayout(form_group)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(14)
        form.setContentsMargins(12, 18, 12, 12)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.ed_name = QLineEdit()
        self.ed_name.setReadOnly(True)
        self.ed_name.setStyleSheet("background: #f0f0f0;")
        form.addRow("Name:", self.ed_name)

        self.ed_enabled = QCheckBox("Enabled")
        form.addRow("", self.ed_enabled)

        self.ed_source = QComboBox()
        self.ed_source.addItems(["google", "x", "linkedin", "instagram", "facebook", "other"])
        self.ed_source.setEditable(True)
        form.addRow("Source:", self.ed_source)

        self.ed_actor_id = QLineEdit()
        self.ed_actor_id.setPlaceholderText("e.g. apify/google-search-scraper")
        form.addRow("Actor ID:", self.ed_actor_id)

        self.ed_notes = QLineEdit()
        form.addRow("Notes:", self.ed_notes)

        editor_layout.addWidget(form_group)

        # ── Per-Group Variables ───────────────────────────────
        info_group = QGroupBox("Per-Group Variables (Dynamic Parameters)")
        info_layout = QVBoxLayout(info_group)
        info_layout.setContentsMargins(12, 18, 12, 12)
        info_layout.setSpacing(8)
        info_text = QLabel(
            "Available Variables: {maxresults}, {region}, {timelimit}\n"
            "Example:\n"
            '{\n'
            '  "maxPagesPerQuery": "{maxresults}",\n'
            '  "countryCode": "{region}",\n'
            '  "timeout": "{timelimit}"\n'
            '}\n\n'
        )
        info_text.setWordWrap(True)
        info_text.setStyleSheet("color: #555; font-size: 11px; line-height: 1.6;")
        info_layout.addWidget(info_text)

        # Default variable values for this actor
        defaults_form = QFormLayout()
        defaults_form.setVerticalSpacing(8)
        defaults_form.setHorizontalSpacing(10)
        defaults_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        from PySide6.QtWidgets import QSpinBox
        self.ed_default_maxresults = QSpinBox()
        self.ed_default_maxresults.setRange(1, 99999)
        self.ed_default_maxresults.setValue(10)
        defaults_form.addRow("Default maxresults:", self.ed_default_maxresults)

        self.ed_default_region = QLineEdit("us")
        defaults_form.addRow("Default region:", self.ed_default_region)

        self.ed_default_timelimit = QLineEdit("3")
        defaults_form.addRow("Default timelimit:", self.ed_default_timelimit)

        info_layout.addLayout(defaults_form)
        editor_layout.addWidget(info_group)

        # ── Templates & Mappings (JSON) ───────────────────────
        json_group = QGroupBox("Templates & Mappings (JSON)")
        json_layout = QVBoxLayout(json_group)
        json_layout.setContentsMargins(12, 18, 12, 12)
        json_layout.setSpacing(10)

        json_layout.addWidget(QLabel("Input Template:"))
        self.ed_input_template = JsonEditor()
        self.ed_input_template.setMinimumHeight(130)
        json_layout.addWidget(self.ed_input_template)

        json_layout.addWidget(QLabel("Query Strategy:"))
        self.ed_query_strategy = JsonEditor()
        self.ed_query_strategy.setMinimumHeight(110)
        json_layout.addWidget(self.ed_query_strategy)

        json_layout.addWidget(QLabel("Output Mapping:"))
        self.ed_output_mapping = JsonEditor()
        self.ed_output_mapping.setMinimumHeight(90)
        json_layout.addWidget(self.ed_output_mapping)

        editor_layout.addWidget(json_group)

        # ── Extraction Rules ──────────────────────────────────
        extract_group = QGroupBox("Extraction Rules")
        extract_layout = QVBoxLayout(extract_group)
        extract_layout.setContentsMargins(12, 18, 12, 12)
        extract_layout.setSpacing(8)
        hint = QLabel(
            "Define how to extract items from the Apify response (one rule per line).\n"
            "Leave empty to use top-level items (default).\n\n"
            "Examples:\n"
            '  raw_items                        → use top-level items\n'
            '  raw_items["organicResults"]       → extract from nested field\n'
            '  raw_items["organicResults"]["a"]  → deeper nesting\n'
            '  raw_items["organicResults"]       → combine items from\n'
            '  raw_items["paidProducts"]           multiple sources'
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; font-size: 12px;")
        extract_layout.addWidget(hint)
        self.ed_extraction_rules = QPlainTextEdit()
        self.ed_extraction_rules.setPlaceholderText('raw_items["organicResults"]')
        self.ed_extraction_rules.setMinimumHeight(80)
        self.ed_extraction_rules.setMaximumHeight(120)
        extract_layout.addWidget(self.ed_extraction_rules)
        editor_layout.addWidget(extract_group)

        # ── Transform Hook ────────────────────────────────────
        hook_group = QGroupBox("Transform Hook (optional Python expression)")
        hook_layout = QVBoxLayout(hook_group)
        hook_layout.setContentsMargins(12, 18, 12, 12)
        hook_layout.setSpacing(8)
        self.ed_transform = QLineEdit()
        self.ed_transform.setPlaceholderText("Leave empty for default mapping")
        hook_layout.addWidget(self.ed_transform)
        editor_layout.addWidget(hook_group)

        # ── Action Buttons ────────────────────────────────────
        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(10)
        btn_save = QPushButton("Save Actor")
        btn_save.setStyleSheet("background: #89b4fa; color: white; border: none; padding: 10px 24px; border-radius: 4px; font-weight: bold;")
        btn_save.clicked.connect(self._save_actor)
        btn_row2.addWidget(btn_save)

        btn_test = QPushButton("Test Actor (sample run)")
        btn_test.setStyleSheet("background: #cba6f7; color: white; border: none; padding: 10px 24px; border-radius: 4px;")
        btn_test.clicked.connect(self._test_actor)
        btn_row2.addWidget(btn_test)
        btn_row2.addStretch()
        editor_layout.addLayout(btn_row2)

        editor_layout.addStretch()

        scroll.setWidget(editor)
        splitter.addWidget(scroll)
        splitter.setSizes([250, 700])
        layout.addWidget(splitter)

    def _on_actor_selected(self, row: int):
        actors = self._db.get_actors()
        if 0 <= row < len(actors):
            a = actors[row]
            self._current_actor = a
            self.ed_name.setText(a.actor_name)
            self.ed_enabled.setChecked(bool(a.enabled))
            idx = self.ed_source.findText(a.source)
            if idx >= 0:
                self.ed_source.setCurrentIndex(idx)
            else:
                self.ed_source.setEditText(a.source)
            self.ed_actor_id.setText(a.actor_id)
            self.ed_notes.setText(a.notes)
            self.ed_input_template.set_json(a.input_template_json)
            self.ed_query_strategy.set_json(a.query_strategy_json)
            self.ed_output_mapping.set_json(a.output_mapping_json)
            self.ed_extraction_rules.setPlainText(a.extraction_rules or "")
            self.ed_transform.setText(a.transform_hook or "")
            self.ed_default_maxresults.setValue(a.default_maxresults)
            self.ed_default_region.setText(a.default_region)
            self.ed_default_timelimit.setText(a.default_timelimit)

    def _save_actor(self):
        if not self._current_actor:
            return
        try:
            actor = Actor(
                actor_name=self._current_actor.actor_name,
                enabled=1 if self.ed_enabled.isChecked() else 0,
                source=self.ed_source.currentText(),
                actor_id=self.ed_actor_id.text(),
                input_template_json=json.dumps(self.ed_input_template.get_json()),
                query_strategy_json=json.dumps(self.ed_query_strategy.get_json()),
                output_mapping_json=json.dumps(self.ed_output_mapping.get_json()),
                transform_hook=self.ed_transform.text() or None,
                notes=self.ed_notes.text(),
                allowed_groups_json=self._current_actor.allowed_groups_json,
                extraction_rules=self.ed_extraction_rules.toPlainText().strip(),
                default_maxresults=self.ed_default_maxresults.value(),
                default_region=self.ed_default_region.text().strip() or "us",
                default_timelimit=self.ed_default_timelimit.text().strip() or "3",
            )
            self._db.save_actor(actor)
            self.refresh()
            QMessageBox.information(self, "Saved", f"Actor '{actor.actor_name}' saved.")
        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "JSON Error", f"Invalid JSON: {e}")

    def _new_actor(self):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Actor", "Actor name (unique):")
        if ok and name.strip():
            name = name.strip().lower().replace(" ", "_")
            existing = self._db.get_actor(name)
            if existing:
                QMessageBox.warning(self, "Exists", f"Actor '{name}' already exists.")
                return
            actor = Actor(actor_name=name)
            self._db.save_actor(actor)
            self.refresh()

    def _delete_actor(self):
        if not self._current_actor:
            return
        reply = QMessageBox.question(
            self, "Delete", f"Delete actor '{self._current_actor.actor_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._db.delete_actor(self._current_actor.actor_name)
            self._current_actor = None
            self.refresh()

    def _test_actor(self):
        """Run a mock test with the current actor configuration."""
        if not self._current_actor:
            return
        from ...pipeline.apify_runner import ApifyRunner
        from ...pipeline.mapping import map_raw_item
        runner = ApifyRunner(token="", mock=True)
        try:
            input_tpl = self.ed_input_template.get_json()
            mapping = self.ed_output_mapping.get_json()
        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "JSON Error", str(e))
            return

        results = runner._mock_results(self.ed_actor_id.text(), input_tpl)
        mapped = []
        for item in results:
            cand = map_raw_item(item, mapping, self._current_actor.actor_name, self.ed_source.currentText(), "test")
            if cand:
                mapped.append(f"• {cand.title[:80]}\n  URL: {cand.url}\n  Domain: {cand.domain}")

        text = "\n\n".join(mapped) if mapped else "No results mapped."
        QMessageBox.information(self, "Test Results (Mock)", f"Mapped {len(mapped)} items:\n\n{text}")

    def refresh(self):
        current_name = self._current_actor.actor_name if self._current_actor else None
        actors = self._db.get_actors()
        self.actor_list.clear()
        select_row = 0
        for i, a in enumerate(actors):
            status = "✅" if a.enabled else "❌"
            item = QListWidgetItem(f"{status} {a.actor_name} [{a.source}]")
            self.actor_list.addItem(item)
            if current_name and a.actor_name == current_name:
                select_row = i
        if actors:
            self.actor_list.setCurrentRow(select_row)
