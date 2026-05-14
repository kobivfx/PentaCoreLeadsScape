"""Keywords management page -- includes Keywords, Groups, Negative Keywords, and Domain Blacklist sub-tabs."""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from ...core.db import DatabaseManager
from ...core.models import ActorGroupVars, Keyword, KeywordGroup, NegativeKeyword
from ...pipeline.stages.group_prefilter import DEFAULT_PREFILTER_PROMPT
from ...pipeline.stages.analysis import DEFAULT_ANALYSIS_PROMPT


class KeywordsPage(QWidget):
    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self._db = db
        self._current_group: KeywordGroup | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel("Groups")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #1e1e2e;")
        layout.addWidget(header)

        self.tabs = QTabWidget()

        # == Tab 1: Keywords ===================================================
        kw_tab = QWidget()
        kw_layout = QVBoxLayout(kw_tab)

        # Filter row
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Status:"))
        self.kw_filter = QComboBox()
        self.kw_filter.addItems(["", "active", "paused", "blacklist"])
        self.kw_filter.currentTextChanged.connect(self._refresh_keywords)
        filter_row.addWidget(self.kw_filter)

        filter_row.addWidget(QLabel("Group:"))
        self.kw_group_filter = QComboBox()
        self.kw_group_filter.addItem("", "")  # empty value for "all"
        self.kw_group_filter.currentIndexChanged.connect(self._refresh_keywords)
        filter_row.addWidget(self.kw_group_filter)

        filter_row.addStretch()

        btn_add = QPushButton("+ Add Keyword")
        btn_add.setStyleSheet("background: #a6e3a1; color: #1e1e2e; border: none; padding: 8px 16px; border-radius: 4px; font-weight: bold;")
        btn_add.clicked.connect(self._add_keyword)
        filter_row.addWidget(btn_add)

        btn_del = QPushButton("Delete Selected")
        btn_del.setStyleSheet("background: #f38ba8; color: white; border: none; padding: 8px 16px; border-radius: 4px;")
        btn_del.clicked.connect(self._delete_keyword)
        filter_row.addWidget(btn_del)

        kw_layout.addLayout(filter_row)

        # Keywords table with multi-select
        self.kw_table = QTableWidget()
        self.kw_table.setColumnCount(8)
        self.kw_table.setHorizontalHeaderLabels(["Keyword", "Group", "Status", "Weight", "Added By", "Avg Score", "Uses", "Notes"])
        self.kw_table.horizontalHeader().setStretchLastSection(True)
        self.kw_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.kw_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.kw_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.kw_table.setAlternatingRowColors(True)
        self.kw_table.cellDoubleClicked.connect(self._edit_keyword)
        self.kw_table.itemSelectionChanged.connect(self._on_kw_selection_changed)
        kw_layout.addWidget(self.kw_table)

        # Bulk actions row (below table)
        bulk_row = QHBoxLayout()
        bulk_row.addWidget(QLabel("Bulk:"))

        self.bulk_status_combo = QComboBox()
        self.bulk_status_combo.addItems(["active", "paused", "blacklist"])
        bulk_row.addWidget(self.bulk_status_combo)

        btn_bulk_status = QPushButton("Set Status")
        btn_bulk_status.setStyleSheet("background: #89b4fa; color: white; border: none; padding: 6px 14px; border-radius: 4px; font-weight: bold;")
        btn_bulk_status.clicked.connect(self._bulk_set_status)
        bulk_row.addWidget(btn_bulk_status)

        bulk_row.addWidget(QLabel("|"))

        btn_bulk_group = QPushButton("Assign to Group...")
        btn_bulk_group.setStyleSheet("background: #cba6f7; color: white; border: none; padding: 6px 14px; border-radius: 4px; font-weight: bold;")
        btn_bulk_group.clicked.connect(self._bulk_assign_group)
        bulk_row.addWidget(btn_bulk_group)

        bulk_row.addStretch()
        self.selection_label = QLabel("")
        self.selection_label.setStyleSheet("color: #666;")
        bulk_row.addWidget(self.selection_label)

        kw_layout.addLayout(bulk_row)

        # == Tab 2: Keyword Groups =============================================
        groups_tab = QWidget()
        groups_layout = QVBoxLayout(groups_tab)

        groups_splitter = QSplitter(Qt.Horizontal)

        # Left: group list
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        grp_btn_row = QHBoxLayout()
        btn_add_grp = QPushButton("+ New Group")
        btn_add_grp.setStyleSheet("background: #a6e3a1; color: #1e1e2e; border: none; padding: 8px 16px; border-radius: 4px; font-weight: bold;")
        btn_add_grp.clicked.connect(self._add_group)
        grp_btn_row.addWidget(btn_add_grp)

        btn_del_grp = QPushButton("Delete")
        btn_del_grp.setStyleSheet("background: #f38ba8; color: white; border: none; padding: 8px 16px; border-radius: 4px;")
        btn_del_grp.clicked.connect(self._delete_group)
        grp_btn_row.addWidget(btn_del_grp)
        grp_btn_row.addStretch()
        left_layout.addLayout(grp_btn_row)

        self.group_table = QTableWidget()
        self.group_table.setColumnCount(3)
        self.group_table.setHorizontalHeaderLabels(["ID", "Name", "Keywords"])
        self.group_table.horizontalHeader().setStretchLastSection(True)
        self.group_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.group_table.setSelectionMode(QTableWidget.SingleSelection)
        self.group_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.group_table.currentCellChanged.connect(self._on_group_selected)
        left_layout.addWidget(self.group_table)

        groups_splitter.addWidget(left)

        # Right: group editor inside scroll area
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        right_inner = QWidget()
        right_layout = QVBoxLayout(right_inner)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(10)

        details_box = QGroupBox("Group Details")
        form = QFormLayout(details_box)
        form.setVerticalSpacing(8)
        form.setHorizontalSpacing(12)
        form.setContentsMargins(10, 14, 10, 10)

        self.edit_id = QLineEdit()
        self.edit_id.setReadOnly(True)
        self.edit_id.setStyleSheet("background: #f0f0f0;")
        form.addRow("Group ID:", self.edit_id)

        self.edit_name = QLineEdit()
        form.addRow("Name:", self.edit_name)

        self.edit_desc = QLineEdit()
        form.addRow("Description:", self.edit_desc)

        right_layout.addWidget(details_box)

        # Sub-tabs for group editor
        group_subtabs = QTabWidget()
        group_subtabs.setStyleSheet("""
            QTabBar::tab {
                padding: 8px 20px;
                background: #f5f5f5;
                border: 1px solid #e0e0e0;
                border-bottom: none;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background: white;
                border: 1px solid #e0e0e0;
                border-bottom: 1px solid white;
            }
            QTabBar::tab:hover:!selected {
                background: #fafafa;
            }
            QTabWidget::pane {
                border: 1px solid #e0e0e0;
            }
        """)

        # ── Sub-tab 1: Prompt Config ──────────────────────────
        prompt_tab = QWidget()
        prompt_tab_layout = QVBoxLayout(prompt_tab)
        prompt_tab_layout.setContentsMargins(0, 8, 0, 0)
        prompt_tab_layout.setSpacing(10)

        prompt_box = QGroupBox("Prefilter Prompt (Yes/No)")
        prompt_lay = QVBoxLayout(prompt_box)
        prompt_lay.setContentsMargins(10, 14, 10, 10)
        prompt_lay.setSpacing(6)
        lbl_pf = QLabel(
            "This prompt is sent to the LLM during the Group Prefilter stage.\n"
            "The LLM will answer Yes or No for each lead in this group."
        )
        lbl_pf.setWordWrap(True)
        lbl_pf.setStyleSheet("color: #555; font-size: 12px;")
        prompt_lay.addWidget(lbl_pf)
        self.edit_prompt = QPlainTextEdit()
        self.edit_prompt.setMinimumHeight(140)
        self.edit_prompt.setStyleSheet(
            "font-family: 'Consolas', monospace; font-size: 13px; padding: 6px;"
        )
        self.edit_prompt.setPlaceholderText(DEFAULT_PREFILTER_PROMPT)
        prompt_lay.addWidget(self.edit_prompt)
        prompt_tab_layout.addWidget(prompt_box)

        # Prefilter input template
        input_box = QGroupBox("Prefilter Input Template")
        input_lay = QVBoxLayout(input_box)
        input_lay.setContentsMargins(10, 14, 10, 10)
        input_lay.setSpacing(6)
        lbl_tpl = QLabel(
            "Customize what data is sent to the prefilter LLM.\n"
            "Variables: {lead.text}, {lead.title}, {lead.author}  —  Leave empty for default."
        )
        lbl_tpl.setWordWrap(True)
        lbl_tpl.setStyleSheet("color: #555; font-size: 12px;")
        input_lay.addWidget(lbl_tpl)
        self.edit_input_template = QPlainTextEdit()
        self.edit_input_template.setMinimumHeight(70)
        self.edit_input_template.setMaximumHeight(110)
        self.edit_input_template.setStyleSheet(
            "font-family: 'Consolas', monospace; font-size: 13px; padding: 6px;"
        )
        self.edit_input_template.setPlaceholderText("{lead.text}\nTitle: {lead.title}\nAuthor: {lead.author}")
        input_lay.addWidget(self.edit_input_template)
        prompt_tab_layout.addWidget(input_box)

        # Analysis prompt
        analysis_box = QGroupBox("Analysis Prompt (Scoring + Enrichment)")
        analysis_lay = QVBoxLayout(analysis_box)
        analysis_lay.setContentsMargins(10, 14, 10, 10)
        analysis_lay.setSpacing(6)
        lbl_an = QLabel(
            "Prompt sent to the analysis LLM for leads in this group.\n"
            "Variables: {url}, {content}, {author}  —  Leave empty for default."
        )
        lbl_an.setWordWrap(True)
        lbl_an.setStyleSheet("color: #555; font-size: 12px;")
        analysis_lay.addWidget(lbl_an)
        self.edit_analysis_prompt = QPlainTextEdit()
        self.edit_analysis_prompt.setMinimumHeight(140)
        self.edit_analysis_prompt.setStyleSheet(
            "font-family: 'Consolas', monospace; font-size: 13px; padding: 6px;"
        )
        self.edit_analysis_prompt.setPlaceholderText(DEFAULT_ANALYSIS_PROMPT)
        analysis_lay.addWidget(self.edit_analysis_prompt)
        prompt_tab_layout.addWidget(analysis_box)

        prompt_tab_layout.addStretch()

        # ── Sub-tab 2: Key (Keywords + Actors) ────────────────
        key_tab = QWidget()
        key_tab_layout = QVBoxLayout(key_tab)
        key_tab_layout.setContentsMargins(0, 8, 0, 0)
        key_tab_layout.setSpacing(10)

        # Keywords in group
        kw_box = QGroupBox("Keywords in Group")
        kw_box_layout = QVBoxLayout(kw_box)
        kw_box_layout.setContentsMargins(10, 14, 10, 10)

        self.grp_kw_table = QTableWidget()
        self.grp_kw_table.setColumnCount(4)
        self.grp_kw_table.setHorizontalHeaderLabels(["Keyword", "Status", "Uses", "Last Run"])
        self.grp_kw_table.horizontalHeader().setStretchLastSection(True)
        self.grp_kw_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.grp_kw_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.grp_kw_table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.grp_kw_table.setMinimumHeight(280)
        self.grp_kw_table.setMaximumHeight(360)
        self.grp_kw_table.setSortingEnabled(True)
        kw_box_layout.addWidget(self.grp_kw_table)

        kw_btn_row = QHBoxLayout()
        btn_create = QPushButton("+ Create Keyword")
        btn_create.setStyleSheet("background: #a6e3a1; color: #1e1e2e; border: none; padding: 6px 14px; border-radius: 4px; font-weight: bold;")
        btn_create.clicked.connect(self._create_keyword_for_group)
        kw_btn_row.addWidget(btn_create)

        btn_assign = QPushButton("Assign Keyword...")
        btn_assign.clicked.connect(self._assign_keyword_to_group)
        kw_btn_row.addWidget(btn_assign)

        btn_unassign = QPushButton("Remove from Group")
        btn_unassign.clicked.connect(self._unassign_keyword)
        kw_btn_row.addWidget(btn_unassign)

        # Bulk edit status for keywords in group
        kw_btn_row.addWidget(QLabel("|"))
        kw_btn_row.addWidget(QLabel("Bulk:"))
        self.grp_kw_status_combo = QComboBox()
        self.grp_kw_status_combo.addItems(["active", "paused"])
        kw_btn_row.addWidget(self.grp_kw_status_combo)
        btn_bulk_status = QPushButton("Set Status")
        btn_bulk_status.setStyleSheet("background: #89b4fa; color: white; border: none; padding: 6px 14px; border-radius: 4px; font-weight: bold;")
        btn_bulk_status.clicked.connect(self._grp_bulk_set_status)
        kw_btn_row.addWidget(btn_bulk_status)

        kw_btn_row.addStretch()
        kw_box_layout.addLayout(kw_btn_row)

        key_tab_layout.addWidget(kw_box)

        # Actors assigned to this group
        actor_box = QGroupBox("Actors Assigned to Group")
        actor_box_layout = QVBoxLayout(actor_box)
        actor_box_layout.setContentsMargins(10, 14, 10, 10)

        self.actor_table = QTableWidget()
        self.actor_table.setColumnCount(7)
        self.actor_table.setHorizontalHeaderLabels(["Actor Name", "Source", "Enabled", "Max Results", "Region", "Time Limit", "Notes"])
        self.actor_table.horizontalHeader().setStretchLastSection(True)
        self.actor_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.actor_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.actor_table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.actor_table.setMinimumHeight(80)
        self.actor_table.setMaximumHeight(150)
        actor_box_layout.addWidget(self.actor_table)

        actor_btn_row = QHBoxLayout()
        btn_assign_actor = QPushButton("Assign Actor\u2026")
        btn_assign_actor.clicked.connect(self._assign_actor)
        actor_btn_row.addWidget(btn_assign_actor)

        btn_edit_vars = QPushButton("Edit Variables\u2026")
        btn_edit_vars.setStyleSheet("background: #cba6f7; color: white; border: none; padding: 6px 14px; border-radius: 4px; font-weight: bold;")
        btn_edit_vars.clicked.connect(self._edit_actor_vars)
        actor_btn_row.addWidget(btn_edit_vars)

        btn_unassign_actor = QPushButton("Remove Actor")
        btn_unassign_actor.clicked.connect(self._unassign_actor)
        actor_btn_row.addWidget(btn_unassign_actor)
        actor_btn_row.addStretch()
        actor_box_layout.addLayout(actor_btn_row)

        key_tab_layout.addWidget(actor_box)

        key_tab_layout.addStretch()
        
        # Add tabs in order: Key first, then Prompt Config
        group_subtabs.addTab(key_tab, "Key")
        group_subtabs.addTab(prompt_tab, "Prompt Config")

        right_layout.addWidget(group_subtabs)

        btn_save_grp = QPushButton("Save Group")
        btn_save_grp.setStyleSheet("background: #89b4fa; color: white; border: none; padding: 10px 24px; border-radius: 4px; font-weight: bold; font-size: 14px;")
        btn_save_grp.clicked.connect(self._save_group)
        right_layout.addWidget(btn_save_grp)

        right_layout.addStretch()
        right_scroll.setWidget(right_inner)

        groups_splitter.addWidget(right_scroll)
        groups_splitter.setStretchFactor(0, 1)
        groups_splitter.setStretchFactor(1, 2)
        groups_layout.addWidget(groups_splitter)

        self.tabs.addTab(groups_tab, "Groups")
        self.tabs.addTab(kw_tab, "Keywords")

        # == Tab 3: Negative Keywords ==========================================
        neg_tab = QWidget()
        neg_layout = QVBoxLayout(neg_tab)

        neg_btn_row = QHBoxLayout()
        neg_btn_row.addStretch()
        btn_add_neg = QPushButton("+ Add Negative")
        btn_add_neg.setStyleSheet("background: #a6e3a1; color: #1e1e2e; border: none; padding: 8px 16px; border-radius: 4px; font-weight: bold;")
        btn_add_neg.clicked.connect(self._add_negative)
        neg_btn_row.addWidget(btn_add_neg)
        btn_del_neg = QPushButton("Delete Selected")
        btn_del_neg.setStyleSheet("background: #f38ba8; color: white; border: none; padding: 8px 16px; border-radius: 4px;")
        btn_del_neg.clicked.connect(self._delete_negative)
        neg_btn_row.addWidget(btn_del_neg)
        neg_layout.addLayout(neg_btn_row)

        self.neg_table = QTableWidget()
        self.neg_table.setColumnCount(3)
        self.neg_table.setHorizontalHeaderLabels(["Phrase", "Enabled", "Notes"])
        self.neg_table.horizontalHeader().setStretchLastSection(True)
        self.neg_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.neg_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.neg_table.setAlternatingRowColors(True)
        neg_layout.addWidget(self.neg_table)

        self.tabs.addTab(neg_tab, "Negative Keywords")

        # == Tab 4: Domain Blacklist ===========================================
        bl_tab = QWidget()
        bl_layout = QVBoxLayout(bl_tab)

        bl_btn_row = QHBoxLayout()
        bl_btn_row.addStretch()
        btn_add_bl = QPushButton("+ Add Domain")
        btn_add_bl.setStyleSheet("background: #a6e3a1; color: #1e1e2e; border: none; padding: 8px 16px; border-radius: 4px; font-weight: bold;")
        btn_add_bl.clicked.connect(self._add_blacklist)
        bl_btn_row.addWidget(btn_add_bl)
        btn_del_bl = QPushButton("Remove Selected")
        btn_del_bl.setStyleSheet("background: #f38ba8; color: white; border: none; padding: 8px 16px; border-radius: 4px;")
        btn_del_bl.clicked.connect(self._delete_blacklist)
        bl_btn_row.addWidget(btn_del_bl)
        bl_layout.addLayout(bl_btn_row)

        self.bl_table = QTableWidget()
        self.bl_table.setColumnCount(3)
        self.bl_table.setHorizontalHeaderLabels(["Domain", "Reason", "Added"])
        self.bl_table.horizontalHeader().setStretchLastSection(True)
        self.bl_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.bl_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.bl_table.setAlternatingRowColors(True)
        bl_layout.addWidget(self.bl_table)

        self.tabs.addTab(bl_tab, "Domain Blacklist")

        layout.addWidget(self.tabs)

    # == Keywords tab ==========================================================
    def _refresh_keywords(self):
        status = self.kw_filter.currentText() or None
        group_id = self.kw_group_filter.currentData() or None

        if group_id:
            keywords = self._db.get_keywords_by_group(group_id)
            if status:
                keywords = [kw for kw in keywords if kw.status == status]
        else:
            keywords = self._db.get_keywords(status=status)
        
        self.kw_table.setRowCount(len(keywords))
        for i, kw in enumerate(keywords):
            self.kw_table.setItem(i, 0, QTableWidgetItem(kw.keyword))
            self.kw_table.setItem(i, 1, QTableWidgetItem(kw.group_id or ""))
            self.kw_table.setItem(i, 2, QTableWidgetItem(kw.status))
            self.kw_table.setItem(i, 3, QTableWidgetItem(str(kw.weight)))
            self.kw_table.setItem(i, 4, QTableWidgetItem(kw.added_by))
            self.kw_table.setItem(i, 5, QTableWidgetItem(f"{kw.avg_manual_score:.1f}"))
            self.kw_table.setItem(i, 6, QTableWidgetItem(str(kw.uses_count)))
            self.kw_table.setItem(i, 7, QTableWidgetItem(kw.notes))
        self._on_kw_selection_changed()

    def _refresh_group_filter(self):
        """Update the group filter dropdown in Keywords tab."""
        groups = self._db.get_keyword_groups()
        current_group_id = self.kw_group_filter.currentData()
        
        self.kw_group_filter.blockSignals(True)
        self.kw_group_filter.clear()
        self.kw_group_filter.addItem("(All Groups)", "")
        for group in groups:
            self.kw_group_filter.addItem(group.name, group.group_id)
        
        # Restore selection if it still exists
        if current_group_id:
            idx = self.kw_group_filter.findData(current_group_id)
            if idx >= 0:
                self.kw_group_filter.setCurrentIndex(idx)
        self.kw_group_filter.blockSignals(False)

    def _on_kw_selection_changed(self):
        count = len(self.kw_table.selectionModel().selectedRows())
        if count > 0:
            self.selection_label.setText(f"{count} keyword{'s' if count != 1 else ''} selected")
        else:
            self.selection_label.setText("")

    def _get_selected_keywords(self) -> list[str]:
        keywords = []
        for idx in self.kw_table.selectionModel().selectedRows():
            item = self.kw_table.item(idx.row(), 0)
            if item:
                keywords.append(item.text())
        return keywords

    def _add_keyword(self):
        text, ok = QInputDialog.getText(self, "Add Keyword", "Keyword phrase:")
        if ok and text.strip():
            kw = Keyword(keyword=text.strip(), added_by="manual")
            self._db.save_keyword(kw)
            self._refresh_keywords()

    def _edit_keyword(self, row, col):
        kw_item = self.kw_table.item(row, 0)
        if not kw_item:
            return
        keyword = kw_item.text()
        existing = [k for k in self._db.get_keywords() if k.keyword == keyword]
        if not existing:
            return
        kw = existing[0]
        dlg = _KeywordEditDialog(kw, self)
        if dlg.exec():
            updated = dlg.get_keyword()
            self._db.save_keyword(updated)
            self._refresh_keywords()

    def _delete_keyword(self):
        keywords = self._get_selected_keywords()
        if not keywords:
            return
        for kw in keywords:
            self._db.delete_keyword(kw)
        self._refresh_keywords()

    # -- Bulk Actions ----------------------------------------------------------
    def _bulk_set_status(self):
        keywords = self._get_selected_keywords()
        if not keywords:
            QMessageBox.information(self, "No Selection", "Select one or more keywords first.")
            return
        new_status = self.bulk_status_combo.currentText()
        reply = QMessageBox.question(
            self, "Bulk Status Change",
            f"Set {len(keywords)} keyword{'s' if len(keywords) != 1 else ''} to '{new_status}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._db.bulk_update_keyword_status(keywords, new_status)
        self._refresh_keywords()
        QMessageBox.information(
            self, "Done",
            f"Updated {len(keywords)} keyword{'s' if len(keywords) != 1 else ''} to '{new_status}'.",
        )

    def _bulk_assign_group(self):
        keywords = self._get_selected_keywords()
        if not keywords:
            QMessageBox.information(self, "No Selection", "Select one or more keywords first.")
            return

        groups = self._db.get_keyword_groups()
        group_names = [f"{g.group_id} -- {g.name}" for g in groups]
        group_names.append("+ Create new group...")

        chosen, ok = QInputDialog.getItem(
            self, "Assign to Group",
            f"Assign {len(keywords)} keyword{'s' if len(keywords) != 1 else ''} to:",
            group_names, editable=False,
        )
        if not ok:
            return

        if chosen == "+ Create new group...":
            gid, ok2 = QInputDialog.getText(self, "New Group", "Group ID (lowercase, no spaces):")
            if not ok2 or not gid.strip():
                return
            gid = gid.strip().lower().replace(" ", "_")
            name, ok3 = QInputDialog.getText(self, "Group Name", "Display name:")
            if not ok3:
                return
            new_group = KeywordGroup(group_id=gid, name=name or gid)
            self._db.save_keyword_group(new_group)
            target_group_id = gid
            target_name = name or gid
        else:
            target_group_id = chosen.split(" -- ")[0]
            target_name = chosen.split(" -- ", 1)[1] if " -- " in chosen else target_group_id

        self._db.bulk_move_keywords_to_group(keywords, target_group_id)
        self._refresh_keywords()
        self._refresh_groups()
        QMessageBox.information(
            self, "Done",
            f"Assigned {len(keywords)} keyword{'s' if len(keywords) != 1 else ''} to group '{target_name}'.",
        )

    # == Groups tab ============================================================
    def _refresh_groups(self, keep_selection=True):
        groups = self._db.get_keyword_groups()
        current_group_id = self._current_group.group_id if keep_selection and self._current_group else None
        
        self.group_table.setRowCount(len(groups))
        select_row = -1
        for r, g in enumerate(groups):
            kw_count = len(self._db.get_keywords_by_group(g.group_id))
            self.group_table.setItem(r, 0, QTableWidgetItem(g.group_id))
            self.group_table.setItem(r, 1, QTableWidgetItem(g.name))
            self.group_table.setItem(r, 2, QTableWidgetItem(str(kw_count)))
            
            # Track row index for current group
            if current_group_id and g.group_id == current_group_id:
                select_row = r
        
        if groups:
            # Keep current selection if it exists, else select first
            if select_row >= 0:
                self.group_table.selectRow(select_row)
            else:
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
        self.edit_analysis_prompt.setPlainText(group.analysis_prompt)
        self._refresh_group_keywords(group.group_id)
        self._refresh_group_actors(group.group_id)

    def _refresh_group_keywords(self, group_id: str):
        keywords = self._db.get_keywords_by_group(group_id)
        self.grp_kw_table.setSortingEnabled(False)
        self.grp_kw_table.setRowCount(len(keywords))
        for r, kw in enumerate(keywords):
            self.grp_kw_table.setItem(r, 0, QTableWidgetItem(kw.keyword))
            self.grp_kw_table.setItem(r, 1, QTableWidgetItem(kw.status))
            uses_in_group = self._db.get_keyword_uses_in_group(kw.keyword, group_id)
            uses_item = QTableWidgetItem()
            uses_item.setData(Qt.ItemDataRole.DisplayRole, uses_in_group)
            self.grp_kw_table.setItem(r, 2, uses_item)
            last_run = self._db.get_keyword_last_run_in_group(kw.keyword, group_id)
            self.grp_kw_table.setItem(r, 3, QTableWidgetItem(last_run))
        self.grp_kw_table.setSortingEnabled(True)

    def _grp_bulk_set_status(self):
        """Bulk set status for selected keywords in the current group."""
        if not self._current_group:
            QMessageBox.warning(self, "No Group", "Please select a group first.")
            return
        
        selected = self.grp_kw_table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select keywords to update.")
            return
        
        # Get unique rows from selected items
        rows = set()
        for item in selected:
            rows.add(item.row())
        
        new_status = self.grp_kw_status_combo.currentText()
        keywords_to_update = []
        for row in sorted(rows):
            kw_item = self.grp_kw_table.item(row, 0)
            if kw_item:
                keywords_to_update.append(kw_item.text())
        
        if not keywords_to_update:
            return
        
        # Update all selected keywords
        self._db.bulk_update_keyword_status(keywords_to_update, new_status)
        
        # Refresh the table
        self._refresh_group_keywords(self._current_group.group_id)
        QMessageBox.information(
            self, "Success",
            f"Updated {len(keywords_to_update)} keyword(s) to '{new_status}'."
        )

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
        self._refresh_groups()

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
            self._refresh_groups()

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
            analysis_prompt=self.edit_analysis_prompt.toPlainText().strip(),
        )
        self._db.save_keyword_group(group)
        self._refresh_groups(keep_selection=True)
        QMessageBox.information(self, "Success", f"Group '{group.name}' saved successfully.")

    def _create_keyword_for_group(self):
        if not self._current_group:
            QMessageBox.warning(self, "No Group Selected", "Please select a group first.")
            return
        
        # Create dialog with multiline text editor
        dlg = QDialog(self)
        dlg.setWindowTitle("Create Keywords")
        dlg.setMinimumWidth(400)
        dlg.setMinimumHeight(300)
        
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("Enter keywords (one per line):"))
        
        text_edit = QPlainTextEdit()
        text_edit.setPlaceholderText("keyword1\nkeyword2\nkeyword3")
        layout.addWidget(text_edit)
        
        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("Create")
        btn_cancel = QPushButton("Cancel")
        btn_layout.addStretch()
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        
        def on_ok():
            text = text_edit.toPlainText().strip()
            if not text:
                QMessageBox.warning(self, "Empty Input", "Please enter at least one keyword.")
                return
            
            lines = text.split('\n')
            created = 0
            for line in lines:
                phrase = line.strip()
                if phrase:
                    kw = Keyword(keyword=phrase, added_by="manual", group_id=self._current_group.group_id)
                    self._db.save_keyword(kw)
                    created += 1
            
            if created > 0:
                QMessageBox.information(self, "Success", f"Created {created} keyword{'s' if created != 1 else ''}.")
                self._refresh_group_keywords(self._current_group.group_id)
                self._refresh_groups()
                self._refresh_keywords()
            dlg.accept()
        
        btn_ok.clicked.connect(on_ok)
        btn_cancel.clicked.connect(dlg.reject)
        dlg.exec()

    def _assign_keyword_to_group(self):
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
            self._refresh_groups()
            self._refresh_keywords()

    def _unassign_keyword(self):
        row = self.grp_kw_table.currentRow()
        if row < 0 or not self._current_group:
            return
        kw_item = self.grp_kw_table.item(row, 0)
        if kw_item:
            self._db.remove_keyword_from_group(kw_item.text(), self._current_group.group_id)
            self._refresh_group_keywords(self._current_group.group_id)
            self._refresh_groups()
            self._refresh_keywords()

    # -- Actor assignment ------------------------------------------------------

    def _refresh_group_actors(self, group_id: str):
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
            v = self._db.get_actor_group_vars(a.actor_name, group_id)
            self.actor_table.setItem(r, 0, QTableWidgetItem(a.actor_name))
            self.actor_table.setItem(r, 1, QTableWidgetItem(a.source))
            self.actor_table.setItem(r, 2, QTableWidgetItem("Yes" if a.enabled else "No"))
            self.actor_table.setItem(r, 3, QTableWidgetItem(str(v.maxresults)))
            self.actor_table.setItem(r, 4, QTableWidgetItem(v.region))
            self.actor_table.setItem(r, 5, QTableWidgetItem(str(v.timelimit)))
            self.actor_table.setItem(r, 6, QTableWidgetItem(a.notes or ""))

    def _assign_actor(self):
        if not self._current_group:
            return
        gid = self._current_group.group_id
        all_actors = self._db.get_actors()
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
        
        # Create multi-select dialog with checkboxes
        dlg = QDialog(self)
        dlg.setWindowTitle("Assign Actors")
        dlg.setMinimumWidth(350)
        
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("Select actors to assign to this group:"))
        
        # Scrollable area with checkboxes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(4)
        
        actor_checks = {}
        for actor in unassigned:
            chk = QCheckBox(actor.actor_name)
            actor_checks[actor.actor_name] = chk
            scroll_layout.addWidget(chk)
        
        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_cancel = QPushButton("Cancel")
        btn_layout.addStretch()
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        
        def on_ok():
            selected = [name for name, chk in actor_checks.items() if chk.isChecked()]
            if not selected:
                QMessageBox.warning(self, "No Selection", "Please select at least one actor.")
                return
            
            for actor_name in selected:
                actor = self._db.get_actor(actor_name)
                if actor:
                    try:
                        groups = json.loads(actor.allowed_groups_json or "[]")
                    except (json.JSONDecodeError, TypeError):
                        groups = []
                    if gid not in groups:
                        groups.append(gid)
                        actor.allowed_groups_json = json.dumps(groups)
                        self._db.save_actor(actor)
                    # Create default vars for this actor-group pair
                    self._db.save_actor_group_vars(
                        ActorGroupVars(actor_name=actor_name, group_id=gid)
                    )
            
            QMessageBox.information(self, "Success", f"Assigned {len(selected)} actor{'s' if len(selected) != 1 else ''} to this group.")
            self._refresh_group_actors(gid)
            dlg.accept()
        
        btn_ok.clicked.connect(on_ok)
        btn_cancel.clicked.connect(dlg.reject)
        dlg.exec()

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
            self._db.delete_actor_group_vars(actor.actor_name, gid)
            self._refresh_group_actors(gid)

    def _edit_actor_vars(self):
        """Open modal to edit variables for selected actor(s) in this group."""
        if not self._current_group:
            return
        gid = self._current_group.group_id
        selected_rows = sorted(set(idx.row() for idx in self.actor_table.selectedIndexes()))
        if not selected_rows:
            QMessageBox.warning(self, "No Selection", "Select one or more actors to edit.")
            return

        actor_names = []
        for row in selected_rows:
            item = self.actor_table.item(row, 0)
            if item:
                actor_names.append(item.text())
        if not actor_names:
            return

        # Load current values from first selected actor as defaults
        first_vars = self._db.get_actor_group_vars(actor_names[0], gid)

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Edit Variables – {', '.join(actor_names[:3])}{'…' if len(actor_names) > 3 else ''}")
        dlg.setMinimumWidth(380)
        layout = QVBoxLayout(dlg)

        if len(actor_names) > 1:
            layout.addWidget(QLabel(f"Editing {len(actor_names)} actors. Changes apply to all selected."))

        # maxresults
        mr_box = QGroupBox("maxresults")
        mr_lay = QHBoxLayout(mr_box)
        spin_mr = QSpinBox()
        spin_mr.setRange(1, 99999)
        spin_mr.setValue(first_vars.maxresults)
        mr_lay.addWidget(spin_mr)
        btn_save_mr = QPushButton("Save")
        btn_save_mr.setStyleSheet("background: #a6e3a1; color: #1e1e2e; border: none; padding: 6px 14px; border-radius: 4px; font-weight: bold;")
        mr_lay.addWidget(btn_save_mr)
        layout.addWidget(mr_box)

        # region
        rg_box = QGroupBox("region")
        rg_lay = QHBoxLayout(rg_box)
        edit_rg = QLineEdit(first_vars.region)
        rg_lay.addWidget(edit_rg)
        btn_save_rg = QPushButton("Save")
        btn_save_rg.setStyleSheet("background: #a6e3a1; color: #1e1e2e; border: none; padding: 6px 14px; border-radius: 4px; font-weight: bold;")
        rg_lay.addWidget(btn_save_rg)
        layout.addWidget(rg_box)

        # timelimit
        tl_box = QGroupBox("timelimit")
        tl_lay = QHBoxLayout(tl_box)
        edit_tl = QLineEdit(first_vars.timelimit)
        tl_lay.addWidget(edit_tl)
        btn_save_tl = QPushButton("Save")
        btn_save_tl.setStyleSheet("background: #a6e3a1; color: #1e1e2e; border: none; padding: 6px 14px; border-radius: 4px; font-weight: bold;")
        tl_lay.addWidget(btn_save_tl)
        layout.addWidget(tl_box)

        # Notes display
        notes_box = QGroupBox("Notes")
        notes_lay = QVBoxLayout(notes_box)
        notes_lay.setContentsMargins(8, 8, 8, 8)
        notes_display = QPlainTextEdit()
        notes_display.setReadOnly(True)
        notes_display.setMinimumHeight(60)
        notes_display.setMaximumHeight(90)
        notes_display.setStyleSheet("font-family: 'Consolas', monospace; font-size: 11px; background: #f9f9f9;")
        
        # Collect notes from all selected actors
        notes_list = []
        for aname in actor_names:
            actor = self._db.get_actor(aname)
            if actor and actor.notes:
                notes_list.append(f"{aname}: {actor.notes}")
            elif actor:
                notes_list.append(f"{aname}: (no notes)")
        
        notes_display.setPlainText("\n".join(notes_list) or "(no notes)")
        notes_lay.addWidget(notes_display)
        layout.addWidget(notes_box)

        status_label = QLabel("")
        status_label.setStyleSheet("color: #40a02b; font-weight: bold;")
        layout.addWidget(status_label)

        def _save_field(field_name, value):
            for aname in actor_names:
                v = self._db.get_actor_group_vars(aname, gid)
                setattr(v, field_name, value)
                self._db.save_actor_group_vars(v)
            status_label.setText(f"✓ {field_name} saved for {len(actor_names)} actor(s)")
            self._refresh_group_actors(gid)

        btn_save_mr.clicked.connect(lambda: _save_field("maxresults", spin_mr.value()))
        btn_save_rg.clicked.connect(lambda: _save_field("region", edit_rg.text().strip() or "us"))
        btn_save_tl.clicked.connect(lambda: _save_field("timelimit", edit_tl.text().strip() or "3"))

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close)

        dlg.exec()

    # == Negative Keywords tab =================================================
    def _refresh_negatives(self):
        negs = self._db.get_negative_keywords()
        self.neg_table.setRowCount(len(negs))
        for i, nk in enumerate(negs):
            self.neg_table.setItem(i, 0, QTableWidgetItem(nk.phrase))
            self.neg_table.setItem(i, 1, QTableWidgetItem("Yes" if nk.enabled else "No"))
            self.neg_table.setItem(i, 2, QTableWidgetItem(nk.notes))

    def _add_negative(self):
        text, ok = QInputDialog.getText(self, "Add Negative Keyword", "Phrase:")
        if ok and text.strip():
            self._db.save_negative_keyword(NegativeKeyword(phrase=text.strip()))
            self._refresh_negatives()

    def _delete_negative(self):
        rows = self.neg_table.selectionModel().selectedRows()
        for idx in rows:
            item = self.neg_table.item(idx.row(), 0)
            if item:
                self._db.delete_negative_keyword(item.text())
        self._refresh_negatives()

    # == Domain Blacklist tab ==================================================
    def _refresh_blacklist(self):
        bls = self._db.get_domain_blacklist()
        self.bl_table.setRowCount(len(bls))
        for i, bl in enumerate(bls):
            self.bl_table.setItem(i, 0, QTableWidgetItem(bl.domain))
            self.bl_table.setItem(i, 1, QTableWidgetItem(bl.reason))
            self.bl_table.setItem(i, 2, QTableWidgetItem(bl.created_at or ""))

    def _add_blacklist(self):
        text, ok = QInputDialog.getText(self, "Add Domain to Blacklist", "Domain:")
        if ok and text.strip():
            self._db.add_domain_blacklist(text.strip().lower(), "Manual")
            self._refresh_blacklist()

    def _delete_blacklist(self):
        rows = self.bl_table.selectionModel().selectedRows()
        for idx in rows:
            item = self.bl_table.item(idx.row(), 0)
            if item:
                self._db.delete_domain_blacklist(item.text())
        self._refresh_blacklist()

    # == Refresh all ===========================================================
    def refresh(self):
        self._refresh_keywords()
        self._refresh_groups()
        self._refresh_group_filter()
        self._refresh_negatives()
        self._refresh_blacklist()


class _KeywordEditDialog(QWidget):
    """Inline keyword editor dialog."""
    def __init__(self, kw: Keyword, parent=None):
        super().__init__(parent)
        self._dlg = QDialog(parent)
        self._dlg.setWindowTitle(f"Edit: {kw.keyword}")
        self._dlg.setMinimumWidth(350)
        self._kw = kw

        layout = QFormLayout(self._dlg)

        self._keyword = QLineEdit(kw.keyword)
        self._keyword.setReadOnly(True)
        layout.addRow("Keyword:", self._keyword)

        self._status = QComboBox()
        self._status.addItems(["active", "paused", "blacklist"])
        idx = self._status.findText(kw.status)
        if idx >= 0:
            self._status.setCurrentIndex(idx)
        layout.addRow("Status:", self._status)

        self._weight = QSpinBox()
        self._weight.setRange(1, 10)
        self._weight.setValue(kw.weight)
        layout.addRow("Weight:", self._weight)

        self._notes = QLineEdit(kw.notes)
        layout.addRow("Notes:", self._notes)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._dlg.accept)
        buttons.rejected.connect(self._dlg.reject)
        layout.addRow(buttons)

    def exec(self):
        return self._dlg.exec()

    def get_keyword(self) -> Keyword:
        self._kw.status = self._status.currentText()
        self._kw.weight = self._weight.value()
        self._kw.notes = self._notes.text()
        return self._kw
