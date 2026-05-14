"""Dashboard page – overview, run controls, stats."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QVBoxLayout, QWidget, QCheckBox, QProgressBar, QScrollArea,
)

from ...core.db import DatabaseManager
from ...core.secrets_manager import SecretsManager


class StatCard(QFrame):
    def __init__(self, title: str, value: str = "0", color: str = "#89b4fa"):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(f"""
            QFrame {{ background: white; border-radius: 8px; padding: 16px; border: 1px solid #e0e0e0; }}
            QLabel#val {{ color: {color}; font-size: 32px; font-weight: bold; }}
            QLabel#title {{ color: #666; font-size: 13px; }}
        """)
        layout = QVBoxLayout(self)
        self.val_label = QLabel(value)
        self.val_label.setObjectName("val")
        self.val_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.val_label)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("title")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)

    def set_value(self, v):
        self.val_label.setText(str(v))


class DashboardPage(QWidget):
    run_requested = Signal(bool, bool, list)   # dry_run, mock_run, group_ids
    stop_requested = Signal()

    def __init__(self, db: DatabaseManager, secrets: SecretsManager, parent=None):
        super().__init__(parent)
        self._db = db
        self._secrets = secrets
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Header
        header = QLabel("Dashboard")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #1e1e2e;")
        layout.addWidget(header)

        # Stats row
        stats_layout = QGridLayout()
        stats_layout.setSpacing(12)
        self.card_total_clients = StatCard("Total Clients", "0", "#89b4fa")
        self.card_contacted_clients = StatCard("Contacted Clients", "0", "#a6e3a1")
        self.card_starred_clients = StatCard("Starred Clients", "0", "#fab387")
        self.card_total_leads = StatCard("Total Leads", "0", "#cba6f7")
        self.card_starred_leads = StatCard("Starred Leads", "0", "#f9e2af")

        for i, card in enumerate([self.card_total_clients, self.card_contacted_clients, self.card_starred_clients,
                                   self.card_total_leads, self.card_starred_leads]):
            stats_layout.addWidget(card, 0, i)
        layout.addLayout(stats_layout)

        # Run controls
        run_group = QGroupBox("Pipeline Control")
        run_group.setStyleSheet("""
            QGroupBox { font-weight: bold; font-size: 14px; background: white;
                        border: 1px solid #e0e0e0; border-radius: 8px; padding: 16px; margin-top: 8px; }
            QGroupBox::title { padding: 0 8px; }
        """)
        run_layout = QVBoxLayout(run_group)

        btn_row = QHBoxLayout()
        self.btn_run = QPushButton("▶  Run Pipeline Now")
        self.btn_run.setStyleSheet("""
            QPushButton { background: #a6e3a1; color: #1e1e2e; border: none; border-radius: 6px;
                          padding: 10px 24px; font-size: 14px; font-weight: bold; }
            QPushButton:hover { background: #94e2d5; }
            QPushButton:disabled { background: #ccc; }
        """)
        self.btn_run.clicked.connect(self._on_run)
        btn_row.addWidget(self.btn_run)

        self.btn_stop = QPushButton("⏹  Stop Run")
        self.btn_stop.setStyleSheet("""
            QPushButton { background: #f38ba8; color: white; border: none; border-radius: 6px;
                          padding: 10px 24px; font-size: 14px; font-weight: bold; }
            QPushButton:hover { background: #eba0ac; }
        """)
        self.btn_stop.clicked.connect(self.stop_requested)
        btn_row.addWidget(self.btn_stop)

        btn_row.addStretch()

        # Group selector
        self.selected_group_ids = ["all"]  # Default to all groups
        self.btn_select_groups = QPushButton("Select Groups (All)")
        self.btn_select_groups.setToolTip("Choose which keyword groups to run")
        self.btn_select_groups.clicked.connect(self._open_group_selector)
        btn_row.addWidget(self.btn_select_groups)

        btn_row.addSpacing(20)

        self.chk_dry = QCheckBox("Dry Run")
        self.chk_dry.setToolTip("Simulate pipeline without calling APIs")
        btn_row.addWidget(self.chk_dry)

        self.chk_mock = QCheckBox("Mock Run")
        self.chk_mock.setToolTip("Use mock data instead of real API calls")
        btn_row.addWidget(self.chk_mock)

        run_layout.addLayout(btn_row)

        # Last run info
        self.last_run_label = QLabel("Last run: –")
        self.last_run_label.setStyleSheet("color: #666; font-size: 12px; padding-top: 8px;")
        run_layout.addWidget(self.last_run_label)

        layout.addWidget(run_group)

        # Pipeline Settings
        settings_group = QGroupBox("Pipeline Settings")
        settings_group.setStyleSheet("""
            QGroupBox { font-weight: bold; font-size: 14px; background: white;
                        border: 1px solid #e0e0e0; border-radius: 8px; padding: 16px; margin-top: 8px; }
            QGroupBox::title { padding: 0 8px; }
        """)
        settings_layout = QHBoxLayout(settings_group)

        settings_layout.addWidget(QLabel("Client Creation Threshold:"))
        self.spin_client_threshold = QSpinBox()
        self.spin_client_threshold.setRange(0, 100)
        self.spin_client_threshold.setToolTip(
            "Only create a client record when the analysis score >= this value.\n"
            "Score range is 0-100. Default: 50."
        )
        threshold = self._db.get_setting("client_creation_threshold", 50)
        try:
            threshold = int(threshold)
        except (TypeError, ValueError):
            threshold = 50
        self.spin_client_threshold.setValue(threshold)
        self.spin_client_threshold.valueChanged.connect(self._on_threshold_changed)
        settings_layout.addWidget(self.spin_client_threshold)
        settings_layout.addStretch()

        layout.addWidget(settings_group)

        # Quick info
        info_group = QGroupBox("Quick Info")
        info_group.setStyleSheet("""
            QGroupBox { font-weight: bold; font-size: 14px; background: white;
                        border: 1px solid #e0e0e0; border-radius: 8px; padding: 16px; margin-top: 8px; }
            QGroupBox::title { padding: 0 8px; }
        """)
        info_layout = QVBoxLayout(info_group)
        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color: #444; font-size: 13px;")
        info_layout.addWidget(self.info_label)
        layout.addWidget(info_group)

        layout.addStretch()

    def _on_run(self):
        groups_to_run = self.selected_group_ids if self.selected_group_ids else ["all"]
        self.run_requested.emit(self.chk_dry.isChecked(), self.chk_mock.isChecked(), groups_to_run)

    def refresh(self):
        # Refresh group selector
        self._refresh_groups()

        # Get lead stats
        lead_stats = self._db.get_lead_stats()
        total_leads = lead_stats["total"]
        starred_leads = lead_stats["starred"]

        # Get client stats
        client_stats = self._db.count_clients_by_status()
        total_clients = client_stats["total"]
        contacted_clients = client_stats["contacted"]
        starred_clients = client_stats["starred"]

        # Update cards: Total Client, Contacted Client, Star Client, Total Lead, Star Lead
        self.card_total_clients.set_value(total_clients)
        self.card_contacted_clients.set_value(contacted_clients)
        self.card_starred_clients.set_value(starred_clients)
        self.card_total_leads.set_value(total_leads)
        self.card_starred_leads.set_value(starred_leads)

        # Last run
        runs = self._db.get_runs(limit=1)
        if runs:
            r = runs[0]
            self.last_run_label.setText(
                f"Last run: {r.started_at[:19]}  |  Status: {r.status}  |  ID: {r.run_id}"
            )
        else:
            self.last_run_label.setText("Last run: no runs yet")

        # Info
        actors = self._db.get_actors(enabled_only=True)
        keywords = self._db.get_keywords(status="active")
        apify_tokens = self._secrets.get_apify_tokens()
        has_apify = len(apify_tokens) > 0
        
        # Get providers for each stage
        from ...pipeline.provider_manager import ProviderManager
        pm = ProviderManager(self._db, mock=False)
        pf_provider_display = pm.get_provider_name_for_stage("prefilter")
        an_provider_display = pm.get_provider_name_for_stage("analysis")
        
        client_threshold = self._db.get_setting("client_creation_threshold", 50)
        try:
            client_threshold = int(client_threshold)
        except (TypeError, ValueError):
            client_threshold = 50

        info_parts = [
            f"Active actors: {len(actors)} | Active keywords: {len(keywords)}",
            f"Apify token: {'✅ set' if has_apify else '❌ not set'}",
            "",
            "Providers:",
            f"  • Prefilter: {pf_provider_display}",
            f"  • Analysis: {an_provider_display}",
            "",
            "Pipeline Flow:",
            f"  1. Scrape data by Apify (Setting on Actors page)",
            f"  2. Prefilter via {pf_provider_display.title()} (Config Promt in Ketwords/Groups tab)",
            f"  3. Analyze via {an_provider_display.title()} (Config Promt in Ketwords/Groups tab)",
            f"  4. Save leads + create&analysis clients from lead (if score ≥ {client_threshold})",
        ]
        self.info_label.setText("\n".join(info_parts))

    def _on_threshold_changed(self, value: int):
        self._db.set_setting("client_creation_threshold", value)

    def _refresh_groups(self):
        """Refresh available groups (called periodically to sync with DB)."""
        groups = self._db.get_keyword_groups()
        group_id_set = {g.group_id for g in groups}
        # Remove any no-longer-existing groups from selection
        self.selected_group_ids = [gid for gid in self.selected_group_ids if gid == "all" or gid in group_id_set]
        if not self.selected_group_ids:
            self.selected_group_ids = ["all"]
        self._update_group_button_text()
    
    def _update_group_button_text(self):
        """Update button text to show selected groups count."""
        if self.selected_group_ids == ["all"]:
            self.btn_select_groups.setText("Select Groups (All)")
        else:
            count = len(self.selected_group_ids)
            self.btn_select_groups.setText(f"Select Groups ({count})")
    
    def _open_group_selector(self):
        """Open dialog to select which keyword groups to run."""
        groups = self._db.get_keyword_groups()
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Keyword Groups")
        dialog.setModal(True)
        dialog.setMinimumWidth(300)
        
        layout = QVBoxLayout(dialog)
        
        # "All Groups" checkbox
        chk_all = QCheckBox("All Groups")
        chk_all.setChecked("all" in self.selected_group_ids)
        layout.addWidget(chk_all)
        
        layout.addSpacing(8)
        
        # Individual group checkboxes in scrollable area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(4)
        
        group_checkboxes = {}
        for group in groups:
            chk = QCheckBox(group.name)
            chk.setChecked(group.group_id in self.selected_group_ids)
            group_checkboxes[group.group_id] = chk
            scroll_layout.addWidget(chk)
        
        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)
        
        layout.addSpacing(8)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_cancel = QPushButton("Cancel")
        btn_layout.addStretch()
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        
        def on_all_toggled(checked: bool):
            """Toggle all individual groups when 'All Groups' is checked."""
            for chk in group_checkboxes.values():
                chk.setChecked(not checked)
                chk.setEnabled(not checked)
        
        def on_ok():
            """Apply selection and close dialog."""
            if chk_all.isChecked():
                self.selected_group_ids = ["all"]
            else:
                self.selected_group_ids = [gid for gid, chk in group_checkboxes.items() if chk.isChecked()]
                if not self.selected_group_ids:
                    self.selected_group_ids = ["all"]
            self._update_group_button_text()
            dialog.accept()
        
        chk_all.toggled.connect(on_all_toggled)
        btn_ok.clicked.connect(on_ok)
        btn_cancel.clicked.connect(dialog.reject)
        
        # Initialize button states
        on_all_toggled(chk_all.isChecked())
        
        dialog.exec()
