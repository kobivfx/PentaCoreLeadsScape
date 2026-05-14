"""Leads review page – table, filters, detail panel."""
from __future__ import annotations

import csv
import json
import webbrowser
from io import StringIO
from pathlib import Path

from PySide6.QtCore import Qt, QModelIndex
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea,
    QSlider, QSpinBox, QSplitter, QTableView, QTextEdit, QVBoxLayout, QWidget,
    QCheckBox, QMessageBox,
)

from ...core.db import DatabaseManager
from ...core.models import Lead
from ..models.leads_model import LeadsTableModel


class LeadsPage(QWidget):
    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self._db = db
        self._current_lead: Lead | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel("Leads")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #1e1e2e;")
        header.setMaximumHeight(36)
        layout.addWidget(header)

        # Filters (scrollable to prevent overlap on resize)
        filter_scroll = QScrollArea()
        filter_scroll.setWidgetResizable(True)
        filter_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        filter_scroll.setMaximumHeight(50)
        filter_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        filter_widget = QWidget()
        filter_layout = QHBoxLayout(filter_widget)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search title, text, URL, author, client…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumWidth(200)
        self.search_input.returnPressed.connect(self._apply_filters)
        filter_layout.addWidget(self.search_input)

        filter_layout.addWidget(QLabel("Status:"))
        self.filter_status = QComboBox()
        self.filter_status.addItems(["", "new", "saved", "contacted", "ignored"])
        filter_layout.addWidget(self.filter_status)

        filter_layout.addWidget(QLabel("Source:"))
        self.filter_source = QComboBox()
        self.filter_source.addItems(["", "google", "x", "linkedin", "instagram", "facebook"])
        filter_layout.addWidget(self.filter_source)

        filter_layout.addWidget(QLabel("Group:"))
        self.filter_group = QComboBox()
        self.filter_group.addItem("")
        filter_layout.addWidget(self.filter_group)

        self.chk_starred = QCheckBox("★")
        self.chk_starred.setToolTip("Show starred only")
        filter_layout.addWidget(self.chk_starred)

        self.chk_prefilter_yes = QCheckBox("Prefilter YES")
        self.chk_prefilter_yes.setToolTip("Show only leads that passed prefilter")
        filter_layout.addWidget(self.chk_prefilter_yes)

        filter_layout.addWidget(QLabel("Score ≥"))
        self.filter_min_score = QSpinBox()
        self.filter_min_score.setRange(0, 10)
        self.filter_min_score.setValue(0)
        filter_layout.addWidget(self.filter_min_score)

        btn_apply = QPushButton("Apply")
        btn_apply.clicked.connect(self._apply_filters)
        filter_layout.addWidget(btn_apply)

        btn_reset = QPushButton("Reset")
        btn_reset.clicked.connect(self._reset_filters)
        filter_layout.addWidget(btn_reset)

        filter_layout.addStretch()

        btn_export = QPushButton("Export CSV")
        btn_export.clicked.connect(self._export_csv)
        filter_layout.addWidget(btn_export)

        filter_scroll.setWidget(filter_widget)
        layout.addWidget(filter_scroll)

        # Splitter: table + detail
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Table
        table_widget = QWidget()
        table_layout = QVBoxLayout(table_widget)
        table_layout.setContentsMargins(0, 0, 0, 0)

        self.model = LeadsTableModel(self._db)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 30)   # starred
        self.table.setColumnWidth(1, 80)   # status
        self.table.setColumnWidth(2, 50)   # score
        self.table.setColumnWidth(3, 55)   # m.score
        self.table.setColumnWidth(4, 100)  # type
        self.table.setColumnWidth(5, 250)  # title
        self.table.setColumnWidth(6, 70)   # source
        self.table.setColumnWidth(7, 120)  # author
        self.table.setColumnWidth(8, 120)  # client
        self.table.setColumnWidth(9, 100)  # group
        self.table.setColumnWidth(10, 110) # keyword
        self.table.setColumnWidth(11, 65)  # prefilter
        self.table.setColumnWidth(12, 80)  # scored by
        self.table.selectionModel().currentRowChanged.connect(self._on_row_changed)
        table_layout.addWidget(self.table)

        # Pagination
        pag_layout = QHBoxLayout()
        self.btn_prev = QPushButton("← Prev")
        self.btn_prev.clicked.connect(self._prev_page)
        pag_layout.addWidget(self.btn_prev)
        self.page_label = QLabel("Page 1 / 1")
        pag_layout.addWidget(self.page_label)
        self.btn_next = QPushButton("Next →")
        self.btn_next.clicked.connect(self._next_page)
        pag_layout.addWidget(self.btn_next)
        pag_layout.addStretch()
        self.count_label = QLabel("0 leads")
        pag_layout.addWidget(self.count_label)

        # Bulk actions
        pag_layout.addWidget(QLabel("Bulk:"))
        self.bulk_status = QComboBox()
        self.bulk_status.addItems(["saved", "contacted", "ignored", "new"])
        pag_layout.addWidget(self.bulk_status)
        btn_bulk = QPushButton("Set Status")
        btn_bulk.clicked.connect(self._bulk_set_status)
        pag_layout.addWidget(btn_bulk)

        btn_delete = QPushButton("Delete Selected")
        btn_delete.setStyleSheet(
            "background: #f38ba8; color: white; border: none; "
            "padding: 6px 12px; border-radius: 4px; font-weight: bold;"
        )
        btn_delete.clicked.connect(self._bulk_delete)
        pag_layout.addWidget(btn_delete)

        btn_rerun_pf = QPushButton("Re-run Prefilter")
        btn_rerun_pf.setStyleSheet(
            "background: #cba6f7; color: white; border: none; "
            "padding: 6px 12px; border-radius: 4px; font-weight: bold;"
        )
        btn_rerun_pf.setToolTip("Re-run LLM prefilter on selected leads")
        btn_rerun_pf.clicked.connect(self._bulk_rerun_prefilter)
        pag_layout.addWidget(btn_rerun_pf)

        table_layout.addLayout(pag_layout)
        splitter.addWidget(table_widget)

        # Detail panel (scrollable to prevent stretching on small windows)
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        detail_scroll.setMinimumWidth(340)
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(8, 0, 0, 0)
        detail_layout.setSpacing(8)

        self.detail_title = QLabel("Select a lead")
        self.detail_title.setWordWrap(True)
        self.detail_title.setStyleSheet("font-size: 15px; font-weight: bold;")
        detail_layout.addWidget(self.detail_title)

        self.detail_url = QLabel()
        self.detail_url.setOpenExternalLinks(True)
        self.detail_url.setWordWrap(True)
        self.detail_url.setStyleSheet("color: #0066cc;")
        detail_layout.addWidget(self.detail_url)

        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setMaximumHeight(150)
        detail_layout.addWidget(self.detail_text)

        # Agent info
        agent_group = QGroupBox("Agent Analysis")
        agent_layout = QVBoxLayout(agent_group)
        self.agent_info = QTextEdit()
        self.agent_info.setReadOnly(True)
        self.agent_info.setMaximumHeight(120)
        agent_layout.addWidget(self.agent_info)
        detail_layout.addWidget(agent_group)

        # Provenance / V2 info
        prov_group = QGroupBox("Pipeline Provenance")
        prov_layout = QVBoxLayout(prov_group)
        self.prov_info = QTextEdit()
        self.prov_info.setReadOnly(True)
        self.prov_info.setMaximumHeight(100)
        prov_layout.addWidget(self.prov_info)

        detail_layout.addWidget(prov_group)

        # ── LLM Scoring Debug ────────────────────────────────
        score_debug_group = QGroupBox("Manual LLM Scoring")
        score_debug_layout = QVBoxLayout(score_debug_group)

        score_btn_row = QHBoxLayout()
        self.btn_score_selected = QPushButton("Score Selected Lead")
        self.btn_score_selected.setStyleSheet(
            "background: #a6e3a1; color: #1e1e2e; border: none; "
            "padding: 6px 12px; border-radius: 4px; font-weight: bold;"
        )
        self.btn_score_selected.clicked.connect(self._manual_score_selected)
        score_btn_row.addWidget(self.btn_score_selected)

        self.btn_score_all_yes = QPushButton("Score All Unscored (Yes)")
        self.btn_score_all_yes.setStyleSheet(
            "background: #89b4fa; color: white; border: none; "
            "padding: 6px 12px; border-radius: 4px; font-weight: bold;"
        )
        self.btn_score_all_yes.clicked.connect(self._manual_score_all_yes)
        score_btn_row.addWidget(self.btn_score_all_yes)
        score_btn_row.addStretch()
        score_debug_layout.addLayout(score_btn_row)

        self.score_debug_log = QPlainTextEdit()
        self.score_debug_log.setReadOnly(True)
        self.score_debug_log.setMaximumHeight(180)
        self.score_debug_log.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")
        self.score_debug_log.setPlaceholderText("Scoring debug logs will appear here…")
        score_debug_layout.addWidget(self.score_debug_log)

        detail_layout.addWidget(score_debug_group)

        # Editable fields
        edit_group = QGroupBox("Review")
        edit_form = QFormLayout(edit_group)

        self.edit_status = QComboBox()
        self.edit_status.addItems(["new", "saved", "contacted", "ignored"])
        edit_form.addRow("Status:", self.edit_status)

        self.edit_manual_score = QSpinBox()
        self.edit_manual_score.setRange(0, 10)
        self.edit_manual_score.setSpecialValueText("–")
        edit_form.addRow("Manual Score:", self.edit_manual_score)

        self.edit_feedback = QLineEdit()
        self.edit_feedback.setPlaceholderText("Notes / feedback…")
        edit_form.addRow("Feedback:", self.edit_feedback)

        self.edit_tags = QLineEdit()
        self.edit_tags.setPlaceholderText("tag1, tag2, …")
        edit_form.addRow("Tags:", self.edit_tags)

        self.edit_starred = QCheckBox("Starred")
        edit_form.addRow("", self.edit_starred)

        self.edit_prefilter = QComboBox()
        self.edit_prefilter.addItems(["", "Yes", "No"])
        edit_form.addRow("Prefilter:", self.edit_prefilter)

        btn_save = QPushButton("Save Changes")
        btn_save.setStyleSheet("background: #89b4fa; color: white; border: none; padding: 8px; border-radius: 4px; font-weight: bold;")
        btn_save.clicked.connect(self._save_lead_edits)
        edit_form.addRow("", btn_save)

        detail_layout.addWidget(edit_group)
        detail_layout.addStretch()

        detail_scroll.setWidget(detail_widget)
        splitter.addWidget(detail_scroll)
        splitter.setSizes([700, 400])
        layout.addWidget(splitter)

    # ── Filters ───────────────────────────────────────────────
    def search_by_client(self, client_name: str):
        """Set search bar to client_name and apply filters – called from Clients page."""
        self._reset_filters()
        self.search_input.setText(client_name)
        self._apply_filters()

    def _apply_filters(self):
        filters = {}
        s = self.search_input.text().strip()
        if s:
            filters["search"] = s
        st = self.filter_status.currentText()
        if st:
            filters["status"] = st
        src = self.filter_source.currentText()
        if src:
            filters["source"] = src
        if self.chk_starred.isChecked():
            filters["is_starred"] = 1
        if self.chk_prefilter_yes.isChecked():
            filters["prefilter_result"] = "Yes"
        ms = self.filter_min_score.value()
        if ms > 0:
            filters["min_auto_score"] = ms
        self.model.set_filters(**filters)
        self._update_pagination()

    def _reset_filters(self):
        self.search_input.clear()
        self.filter_status.setCurrentIndex(0)
        self.filter_source.setCurrentIndex(0)
        self.chk_starred.setChecked(False)
        self.chk_prefilter_yes.setChecked(False)
        self.filter_min_score.setValue(0)
        self.model.set_filters()
        self._update_pagination()

    # ── Pagination ────────────────────────────────────────────
    def _prev_page(self):
        self.model.prev_page()
        self._update_pagination()

    def _next_page(self):
        self.model.next_page()
        self._update_pagination()

    def _update_pagination(self):
        self.page_label.setText(f"Page {self.model.page + 1} / {self.model.total_pages}")
        self.count_label.setText(f"{self.model.total_count} leads")
        self.btn_prev.setEnabled(self.model.page > 0)
        self.btn_next.setEnabled(self.model.page + 1 < self.model.total_pages)

    # ── Row selection ─────────────────────────────────────────
    def _on_row_changed(self, current: QModelIndex, previous: QModelIndex):
        lead = self.model.get_lead_at(current.row())
        if not lead:
            return
        self._current_lead = lead
        self.detail_title.setText(lead.title or "(no title)")
        self.detail_url.setText(f'<a href="{lead.url}">{lead.url}</a>' if lead.url else "")
        self.detail_text.setPlainText(lead.text or "")

        # Agent info
        agent = lead.agent_data
        if agent:
            lines = []
            lines.append(f"Type: {agent.get('lead_type', '–')}")
            lines.append(f"Score: {agent.get('score', '–')}")
            reason = agent.get('reason', agent.get('score_reason', ''))
            if reason:
                lines.append(f"Reason: {reason}")
            signals = agent.get("buyer_signals", [])
            if signals:
                lines.append(f"Buyer signals: {', '.join(signals)}")
            lines.append(f"Company: {agent.get('client_name', agent.get('company_guess', '–'))}")
            proj = agent.get("project_type_guess", [])
            if proj:
                lines.append(f"Project types: {', '.join(proj)}")
            lines.append(f"Action: {agent.get('recommended_action', '–')}")
            self.agent_info.setPlainText("\n".join(lines))
        else:
            self.agent_info.setPlainText("Not scored yet")

        # Provenance info
        prov_lines = []
        prov_lines.append(f"Keyword Group: {lead.keyword_group_id or '–'}")
        prov_lines.append(f"Keyword Used: {lead.keyword_used or lead.query_used or '–'}")
        prov_lines.append(f"Prefilter: {lead.prefilter_result or '–'} (model: {lead.prefilter_model or '–'})")
        prov_lines.append(f"Enrichment: {'Yes' if lead.enrichment_json and lead.enrichment_json != '{}' else 'No'} (provider: {lead.enrichment_provider or '–'})")
        prov_lines.append(f"Scoring Provider: {lead.scoring_provider or '–'}")
        self.prov_info.setPlainText("\n".join(prov_lines))

        # Edit fields
        idx = self.edit_status.findText(lead.status)
        if idx >= 0:
            self.edit_status.setCurrentIndex(idx)
        self.edit_manual_score.setValue(lead.manual_score if lead.manual_score is not None else 0)
        self.edit_feedback.setText(lead.manual_feedback or "")
        self.edit_tags.setText(", ".join(lead.tags))
        self.edit_starred.setChecked(bool(lead.is_starred))

        pf = lead.prefilter_result or ""
        pf_idx = self.edit_prefilter.findText(pf)
        self.edit_prefilter.setCurrentIndex(pf_idx if pf_idx >= 0 else 0)

    def _save_lead_edits(self):
        if not self._current_lead:
            return
        tags = [t.strip() for t in self.edit_tags.text().split(",") if t.strip()]
        ms = self.edit_manual_score.value()
        self._db.update_lead_manual(
            self._current_lead.lead_id,
            status=self.edit_status.currentText(),
            manual_score=ms if ms > 0 else None,
            manual_feedback=self.edit_feedback.text(),
            tags_json=json.dumps(tags),
            is_starred=1 if self.edit_starred.isChecked() else 0,
        )
        # Update prefilter if changed
        new_pf = self.edit_prefilter.currentText()
        old_pf = self._current_lead.prefilter_result or ""
        if new_pf != old_pf:
            self._db.update_lead_prefilter(
                self._current_lead.lead_id,
                prefilter_result=new_pf,
                prefilter_model="manual",
            )
        self.model.refresh()
        self._update_pagination()

    # ── Bulk actions ──────────────────────────────────────────
    def _bulk_set_status(self):
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return
        ids = []
        for idx in indexes:
            lead = self.model.get_lead_at(idx.row())
            if lead:
                ids.append(lead.lead_id)
        status = self.bulk_status.currentText()
        self._db.bulk_update_status(ids, status)
        self.model.refresh()
        self._update_pagination()

    def _bulk_delete(self):
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return
        ids = []
        for idx in indexes:
            lead = self.model.get_lead_at(idx.row())
            if lead:
                ids.append(lead.lead_id)
        if not ids:
            return
        answer = QMessageBox.question(
            self, "Delete Leads",
            f"Permanently delete {len(ids)} selected lead(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._db.bulk_delete_leads(ids)
        self._current_lead = None
        self.detail_title.setText("Select a lead")
        self.detail_url.clear()
        self.detail_text.clear()
        self.agent_info.clear()
        self.prov_info.clear()
        self.model.refresh()
        self._update_pagination()

    def _bulk_rerun_prefilter(self):
        """Re-run LLM prefilter on all selected leads."""
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return
        leads = []
        for idx in indexes:
            lead = self.model.get_lead_at(idx.row())
            if lead:
                leads.append(lead)
        if not leads:
            return

        self.score_debug_log.clear()
        self._log_score(f"── Re-running prefilter on {len(leads)} lead(s) ──")

        # Get prefilter provider
        from ...pipeline.provider_manager import ProviderManager
        from ...pipeline.stages.group_prefilter import DEFAULT_PREFILTER_PROMPT, DEFAULT_INPUT_TEMPLATE, render_prefilter_input
        pm = ProviderManager(self._db, mock=False)
        provider, provider_name = pm.get_provider_for_stage("prefilter")
        if not provider:
            self._log_score(f"❌ No prefilter provider available (resolved: '{provider_name}').")
            return

        model_name = getattr(provider, '_config', {}).get("http_model", provider_name)
        self._log_score(f"Provider: {provider_name} ({type(provider).__name__})")
        self._log_score(f"Model: {model_name}")

        if hasattr(provider, 'validate_config'):
            err = provider.validate_config()
            if err:
                self._log_score(f"❌ Config validation failed: {err}")
                return
            self._log_score("Config validation: OK")

        groups = {g.group_id: g for g in self._db.get_keyword_groups()}

        import time as _time
        passed = 0
        rejected = 0
        for i, lead in enumerate(leads, 1):
            self._log_score(f"\n── [{i}/{len(leads)}] {lead.title[:80]} ──")
            self._log_score(f"  ID: {lead.lead_id}")
            self._log_score(f"  URL: {lead.url}")
            self._log_score(f"  Group: {lead.keyword_group_id or '–'}")
            self._log_score(f"  Previous prefilter: {lead.prefilter_result or '–'} (model: {lead.prefilter_model or '–'})")

            group = groups.get(lead.keyword_group_id)
            prompt = (group.prefilter_prompt if group and group.prefilter_prompt
                      else DEFAULT_PREFILTER_PROMPT)
            input_template = (group.prefilter_input_template if group and group.prefilter_input_template
                              else DEFAULT_INPUT_TEMPLATE)
            content = render_prefilter_input(lead, input_template)

            # Show the full prompt that will be sent
            if hasattr(provider, 'build_prefilter_prompt'):
                full_prompt = provider.build_prefilter_prompt(content, prompt)
            else:
                full_prompt = f"{prompt}\n\nContent:\n{content[:4000]}\n\nAnswer (Yes or No):"
            self._log_score(f"\n  ── Full Prompt ({len(full_prompt)} chars) ──")
            self._log_score(f"  {full_prompt}")
            self._log_score(f"  ── End Prompt ──\n")

            t0 = _time.perf_counter()
            try:
                result, raw = provider.prefilter(content, prompt)
                latency = round((_time.perf_counter() - t0) * 1000)
                icon = "✅" if result == "Yes" else "❌"
                self._log_score(f"  {icon} Result: {result}  ({latency} ms)")
                self._log_score(f"  Raw response: {raw[:500]}")
                self._db.update_lead_prefilter(lead.lead_id, result, model_name, prefilter_raw=raw)
                if result == "Yes":
                    passed += 1
                else:
                    rejected += 1
            except Exception as e:
                latency = round((_time.perf_counter() - t0) * 1000)
                self._log_score(f"  ❌ Error ({latency} ms): {e}")

        self._log_score(f"\n── Done: {passed} Yes, {rejected} No ──")
        self.model.refresh()
        self._update_pagination()

    # ── Export ────────────────────────────────────────────────
    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Leads CSV", "leads_export.csv", "CSV (*.csv)")
        if not path:
            return
        leads = self._db.get_leads(limit=100000)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["lead_id", "status", "auto_score", "manual_score", "lead_type",
                             "title", "url", "source", "author",
                             "score_reason", "manual_feedback", "tags", "is_starred",
                             "first_seen_at", "last_seen_at"])
            for l in leads:
                writer.writerow([
                    l.lead_id, l.status, l.auto_score, l.manual_score or "", l.lead_type,
                    l.title, l.url, l.source, l.author,
                    l.score_reason, l.manual_feedback, "|".join(l.tags), l.is_starred,
                    l.first_seen_at, l.last_seen_at,
                ])
        QMessageBox.information(self, "Export", f"Exported {len(leads)} leads to {path}")

    # ── Manual LLM Scoring ────────────────────────────────────
    def _log_score(self, msg: str):
        """Append a line to the scoring debug log and force UI update."""
        self.score_debug_log.appendPlainText(msg)
        QApplication.processEvents()

    def _manual_score_selected(self):
        """Score just the currently selected lead and show debug output."""
        if not self._current_lead:
            self._log_score("❌ No lead selected.")
            return
        self.score_debug_log.clear()
        self._run_scoring_on_leads([self._current_lead])
        self.model.refresh()
        self._update_pagination()
        # Re-select to refresh detail panel
        if self._current_lead:
            self._on_row_changed(self.table.currentIndex(), self.table.currentIndex())

    def _manual_score_all_yes(self):
        """Score all leads with prefilter_result=Yes that haven't been scored yet."""
        self.score_debug_log.clear()
        to_score = self._db.get_leads_for_analysis(limit=99999999)
        if not to_score:
            self._log_score("No unscored Yes leads found.")
            return
        self._log_score(f"Found {len(to_score)} unscored Yes leads.")
        self._run_scoring_on_leads(to_score)
        self.model.refresh()
        self._update_pagination()

    def _run_scoring_on_leads(self, leads: list[Lead]):
        """Run LLM analysis on a list of leads, logging each step."""
        import time as _time

        self._log_score("── Loading analysis provider ──")
        try:
            from ...pipeline.provider_manager import ProviderManager
            pm = ProviderManager(self._db, mock=False)
            provider, provider_name = pm.get_provider_for_stage("analysis")
        except Exception as e:
            self._log_score(f"❌ ProviderManager error: {e}")
            return

        if not provider:
            self._log_score(f"❌ No analysis provider available (resolved: '{provider_name}').")
            self._log_score("")
            self._log_score("── Troubleshooting ──")
            cfg = self._db.get_setting("provider_analysis", {})
            self._log_score(f"Stage config: {cfg}")
            for p in self._db.get_providers():
                self._log_score(f"  {p.provider_id}: enabled={p.enabled}")
            self._log_score("")
            self._log_score("Check: is the selected provider enabled?")
            self._log_score("Check: is the API key set? (for DeepSeek)")
            self._log_score("Check: is llama-cpp-python installed? (for local direct mode)")
            self._log_score("Check: is the HTTP server running? (for http mode)")
            return

        self._log_score(f"Provider: {provider_name} ({type(provider).__name__})")
        self._log_score(f"Mode: {getattr(provider, '_mode', 'api')}")

        # Validate
        if hasattr(provider, 'validate_config'):
            err = provider.validate_config()
            if err:
                self._log_score(f"❌ Config validation failed: {err}")
                return
            self._log_score("Config validation: OK")

        # Get analysis prompt template
        from ...pipeline.stages.analysis import AnalysisStage, DEFAULT_ANALYSIS_PROMPT
        stage = AnalysisStage(self._db, mock=False, dry_run=False)
        prompt_template = stage._get_analysis_prompt()
        self._log_score(f"Prompt template: {len(prompt_template)} chars")
        self._log_score("")

        analyzed = 0
        for i, lead in enumerate(leads, 1):
            self._log_score(f"── Analyzing lead {i}/{len(leads)}: {lead.title[:60]} ──")
            self._log_score(f"  ID: {lead.lead_id}")
            self._log_score(f"  URL: {lead.url}")
            self._log_score(f"  Domain: {lead.domain}")
            self._log_score(f"  Prefilter: {lead.prefilter_result}")

            t0 = _time.perf_counter()
            stats: dict = {"errors": []}
            try:
                stage._analyze_lead(lead, provider, provider_name, prompt_template, stats)
                latency = round((_time.perf_counter() - t0) * 1000)
                analyzed += 1

                # Re-read the lead to show updated score
                updated = self._db.get_lead(lead.lead_id)
                if updated:
                    self._log_score(f"  ✅ Score: {updated.auto_score}  Type: {updated.lead_type}")
                    self._log_score(f"  Reason: {updated.score_reason[:120]}")
                    self._log_score(f"  Author: {updated.author}")
                    if updated.enrichment_json and updated.enrichment_json != "{}":
                        import json as _json
                        try:
                            enrich = _json.loads(updated.enrichment_json)
                            self._log_score(f"  Brand: {enrich.get('brand', '')}")
                            self._log_score(f"  Contact: {enrich.get('contact', '')}")
                        except Exception:
                            pass
                else:
                    self._log_score("  ✅ Analyzed (could not reload)")
                self._log_score(f"  Latency: {latency} ms")
            except Exception as e:
                latency = round((_time.perf_counter() - t0) * 1000)
                self._log_score(f"  ❌ Error ({latency} ms): {e}")
                if stats.get("errors"):
                    for err_msg in stats["errors"]:
                        self._log_score(f"  Detail: {err_msg}")

        self._log_score("")
        self._log_score(f"── Done: {analyzed}/{len(leads)} leads analyzed ──")

    # ── Refresh ───────────────────────────────────────────────
    def refresh(self):
        self.model.refresh()
        self._update_pagination()
        # Refresh group filter
        current_group = self.filter_group.currentText()
        self.filter_group.blockSignals(True)
        self.filter_group.clear()
        self.filter_group.addItem("")
        for g in self._db.get_keyword_groups():
            self.filter_group.addItem(g.group_id)
        idx = self.filter_group.findText(current_group)
        if idx >= 0:
            self.filter_group.setCurrentIndex(idx)
        self.filter_group.blockSignals(False)
