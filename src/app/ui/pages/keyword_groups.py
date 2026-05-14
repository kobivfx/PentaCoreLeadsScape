"""Keyword Groups management page."""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...core.db import DatabaseManager
from ...core.models import KeywordGroup


class KeywordGroupsPage(QWidget):
    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self._db = db
        self._current_group: KeywordGroup | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel("Keyword Groups")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #1e1e2e;")
        layout.addWidget(header)

        splitter = QSplitter(Qt.Horizontal)

        # Left: group list
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ New Group")
        btn_add.setStyleSheet("background: #a6e3a1; color: #1e1e2e; border: none; padding: 8px 16px; border-radius: 4px; font-weight: bold;")
        btn_add.clicked.connect(self._add_group)
        btn_row.addWidget(btn_add)

        btn_del = QPushButton("Delete")
        btn_del.setStyleSheet("background: #f38ba8; color: white; border: none; padding: 8px 16px; border-radius: 4px;")
        btn_del.clicked.connect(self._delete_group)
        btn_row.addWidget(btn_del)
        btn_row.addStretch()
        left_layout.addLayout(btn_row)

        self.group_table = QTableWidget()
        self.group_table.setColumnCount(3)
        self.group_table.setHorizontalHeaderLabels(["ID", "Name", "Keywords"])
        self.group_table.horizontalHeader().setStretchLastSection(True)
        self.group_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.group_table.setSelectionMode(QTableWidget.SingleSelection)
        self.group_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.group_table.currentCellChanged.connect(self._on_group_selected)
        left_layout.addWidget(self.group_table)

        splitter.addWidget(left)

        # Right: group editor
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)

        # Group details
        details_box = QGroupBox("Group Details")
        form = QFormLayout(details_box)

        self.edit_id = QLineEdit()
        self.edit_id.setReadOnly(True)
        self.edit_id.setStyleSheet("background: #f0f0f0;")
        form.addRow("Group ID:", self.edit_id)

        self.edit_name = QLineEdit()
        form.addRow("Name:", self.edit_name)

        self.edit_desc = QLineEdit()
        form.addRow("Description:", self.edit_desc)

        right_layout.addWidget(details_box)

        # Prefilter prompt editor
        prompt_box = QGroupBox("Prefilter Prompt (Yes/No)")
        prompt_layout = QVBoxLayout(prompt_box)
        prompt_layout.addWidget(QLabel("This prompt is sent to the local LLM during the Group Prefilter stage.\nThe LLM will answer Yes or No for each lead in this group."))
        self.edit_prompt = QPlainTextEdit()
        self.edit_prompt.setMinimumHeight(120)
        self.edit_prompt.setStyleSheet("font-family: 'Consolas', monospace; font-size: 13px;")
        self.edit_prompt.setPlaceholderText("You are an expert lead-qualification agent for a 3D animation outsourcing studio. Your studio provides: game cinematics, brand mascot animation, animated commercials, product animation, and CGI content, animation feature film, animation IP, animation series, game trailer. Is the information below have a chance to be a lead? Answer Yes or No only.")
        prompt_layout.addWidget(self.edit_prompt)
        right_layout.addWidget(prompt_box)

        # Prefilter input template
        input_box = QGroupBox("Prefilter Input Template")
        input_layout = QVBoxLayout(input_box)
        input_layout.addWidget(QLabel(
            "Customize what data is sent to the prefilter LLM for leads in this group.\n"
            "Available variables: {lead.text}, {lead.title}, {lead.author}\n"
            "Leave empty to use the default template."
        ))
        self.edit_input_template = QPlainTextEdit()
        self.edit_input_template.setMinimumHeight(60)
        self.edit_input_template.setMaximumHeight(100)
        self.edit_input_template.setStyleSheet("font-family: 'Consolas', monospace; font-size: 13px;")
        self.edit_input_template.setPlaceholderText("{lead.text}\nTitle: {lead.title}\nAuthor: {lead.author}")
        input_layout.addWidget(self.edit_input_template)
        right_layout.addWidget(input_box)

        # Keywords in this group
        kw_box = QGroupBox("Keywords in Group")
        kw_layout = QVBoxLayout(kw_box)

        self.kw_table = QTableWidget()
        self.kw_table.setColumnCount(3)
        self.kw_table.setHorizontalHeaderLabels(["Keyword", "Status", "Weight"])
        self.kw_table.horizontalHeader().setStretchLastSection(True)
        self.kw_table.setEditTriggers(QTableWidget.NoEditTriggers)
        kw_layout.addWidget(self.kw_table)

        kw_btn_row = QHBoxLayout()
        btn_assign = QPushButton("Assign Keyword…")
        btn_assign.clicked.connect(self._assign_keyword)
        kw_btn_row.addWidget(btn_assign)

        btn_unassign = QPushButton("Remove from Group")
        btn_unassign.clicked.connect(self._unassign_keyword)
        kw_btn_row.addWidget(btn_unassign)
        kw_btn_row.addStretch()
        kw_layout.addLayout(kw_btn_row)

        right_layout.addWidget(kw_box)

        # Actors assigned to this group
        actor_box = QGroupBox("Actors Assigned to Group")
        actor_layout = QVBoxLayout(actor_box)

        self.actor_table = QTableWidget()
        self.actor_table.setColumnCount(3)
        self.actor_table.setHorizontalHeaderLabels(["Actor Name", "Source", "Enabled"])
        self.actor_table.horizontalHeader().setStretchLastSection(True)
        self.actor_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.actor_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.actor_table.setSelectionMode(QTableWidget.SingleSelection)
        actor_layout.addWidget(self.actor_table)

        actor_btn_row = QHBoxLayout()
        btn_assign_actor = QPushButton("Assign Actor…")
        btn_assign_actor.clicked.connect(self._assign_actor)
        actor_btn_row.addWidget(btn_assign_actor)

        btn_unassign_actor = QPushButton("Remove Actor")
        btn_unassign_actor.clicked.connect(self._unassign_actor)
        actor_btn_row.addWidget(btn_unassign_actor)
        actor_btn_row.addStretch()
        actor_layout.addLayout(actor_btn_row)

        right_layout.addWidget(actor_box)

        # Save button
        btn_save = QPushButton("Save Group")
        btn_save.setStyleSheet("background: #89b4fa; color: white; border: none; padding: 10px 24px; border-radius: 4px; font-weight: bold; font-size: 14px;")
        btn_save.clicked.connect(self._save_group)
        right_layout.addWidget(btn_save)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter)

    def refresh(self):
        groups = self._db.get_keyword_groups()
        self.group_table.setRowCount(len(groups))
        for r, g in enumerate(groups):
            kw_count = len(self._db.get_keywords_by_group(g.group_id))
            self.group_table.setItem(r, 0, QTableWidgetItem(g.group_id))
            self.group_table.setItem(r, 1, QTableWidgetItem(g.name))
            self.group_table.setItem(r, 2, QTableWidgetItem(str(kw_count)))
        if groups:
            self.group_table.selectRow(0)

    def _on_group_selected(self, row, col, prev_row, prev_col):
        if row < 0:
            return
        gid_item = self.group_table.item(row, 0)
        if not gid_item:
            return
        group = self._db.get_keyword_group(gid_item.text())
        if not group:
            return
        self._current_group = group
        self.edit_id.setText(group.group_id)
        self.edit_name.setText(group.name)
        self.edit_desc.setText(group.description)
        self.edit_prompt.setPlainText(group.prefilter_prompt)
        self.edit_input_template.setPlainText(group.prefilter_input_template)
        self._refresh_group_keywords(group.group_id)
        self._refresh_group_actors(group.group_id)

    def _refresh_group_keywords(self, group_id: str):
        keywords = self._db.get_keywords_by_group(group_id)
        self.kw_table.setRowCount(len(keywords))
        for r, kw in enumerate(keywords):
            self.kw_table.setItem(r, 0, QTableWidgetItem(kw.keyword))
            self.kw_table.setItem(r, 1, QTableWidgetItem(kw.status))
            self.kw_table.setItem(r, 2, QTableWidgetItem(f"{kw.weight:.1f}"))

    def _add_group(self):
        gid, ok = QInputDialog.getText(self, "New Keyword Group", "Group ID (lowercase, no spaces):")
        if not ok or not gid.strip():
            return
        gid = gid.strip().lower().replace(" ", "_")
        name, ok2 = QInputDialog.getText(self, "Group Name", "Display name:")
        if not ok2:
            return
        group = KeywordGroup(group_id=gid, name=name or gid)
        self._db.save_keyword_group(group)
        self.refresh()

    def _delete_group(self):
        if not self._current_group:
            return
        reply = QMessageBox.question(
            self, "Delete Group",
            f"Delete group '{self._current_group.name}'?\nKeywords will be unlinked, not deleted.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._db.delete_keyword_group(self._current_group.group_id)
            self._current_group = None
            self.refresh()

    def _save_group(self):
        if not self._current_group:
            QMessageBox.warning(self, "No Group", "Select a group first.")
            return
        group = KeywordGroup(
            group_id=self._current_group.group_id,
            name=self.edit_name.text().strip() or self._current_group.name,
            description=self.edit_desc.text().strip(),
            prefilter_prompt=self.edit_prompt.toPlainText().strip(),
            prefilter_input_template=self.edit_input_template.toPlainText().strip(),
        )
        self._db.save_keyword_group(group)
        self.refresh()

    def _assign_keyword(self):
        if not self._current_group:
            return
        unassigned = self._db.get_keywords_not_in_group(self._current_group.group_id, status="active")
        if not unassigned:
            QMessageBox.information(self, "No Keywords", "All active keywords are already in this group.")
            return
        items = [kw.keyword for kw in unassigned]
        chosen, ok = QInputDialog.getItem(self, "Assign Keyword", "Select keyword:", items, editable=False)
        if ok and chosen:
            self._db.move_keyword_to_group(chosen, self._current_group.group_id)
            self._refresh_group_keywords(self._current_group.group_id)
            self.refresh()

    def _unassign_keyword(self):
        row = self.kw_table.currentRow()
        if row < 0 or not self._current_group:
            return
        kw_item = self.kw_table.item(row, 0)
        if kw_item:
            self._db.remove_keyword_from_group(kw_item.text(), self._current_group.group_id)
            self._refresh_group_keywords(self._current_group.group_id)
            self.refresh()

    # ── Actor assignment ──────────────────────────────────────

    def _refresh_group_actors(self, group_id: str):
        """Show actors whose allowed_groups_json includes this group."""
        all_actors = self._db.get_actors()
        assigned = []
        for a in all_actors:
            try:
                groups = json.loads(a.allowed_groups_json or "[]")
            except (json.JSONDecodeError, TypeError):
                groups = []
            if group_id in groups:
                assigned.append(a)
        self.actor_table.setRowCount(len(assigned))
        for r, a in enumerate(assigned):
            self.actor_table.setItem(r, 0, QTableWidgetItem(a.actor_name))
            self.actor_table.setItem(r, 1, QTableWidgetItem(a.source))
            self.actor_table.setItem(r, 2, QTableWidgetItem("Yes" if a.enabled else "No"))

    def _assign_actor(self):
        if not self._current_group:
            return
        gid = self._current_group.group_id
        all_actors = self._db.get_actors()
        # Filter actors not already assigned to this group
        unassigned = []
        for a in all_actors:
            try:
                groups = json.loads(a.allowed_groups_json or "[]")
            except (json.JSONDecodeError, TypeError):
                groups = []
            if gid not in groups:
                unassigned.append(a)
        if not unassigned:
            QMessageBox.information(self, "No Actors", "All actors are already assigned to this group.")
            return
        items = [a.actor_name for a in unassigned]
        chosen, ok = QInputDialog.getItem(self, "Assign Actor", "Select actor:", items, editable=False)
        if ok and chosen:
            actor = self._db.get_actor(chosen)
            if actor:
                try:
                    groups = json.loads(actor.allowed_groups_json or "[]")
                except (json.JSONDecodeError, TypeError):
                    groups = []
                groups.append(gid)
                actor.allowed_groups_json = json.dumps(groups)
                self._db.save_actor(actor)
                self._refresh_group_actors(gid)

    def _unassign_actor(self):
        if not self._current_group:
            return
        row = self.actor_table.currentRow()
        if row < 0:
            return
        actor_name_item = self.actor_table.item(row, 0)
        if not actor_name_item:
            return
        actor = self._db.get_actor(actor_name_item.text())
        if not actor:
            return
        gid = self._current_group.group_id
        try:
            groups = json.loads(actor.allowed_groups_json or "[]")
        except (json.JSONDecodeError, TypeError):
            groups = []
        if gid in groups:
            groups.remove(gid)
            actor.allowed_groups_json = json.dumps(groups)
            self._db.save_actor(actor)
            self._refresh_group_actors(gid)
