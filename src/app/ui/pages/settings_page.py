"""Settings & Security page."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSpinBox, QVBoxLayout, QWidget, QCheckBox, QListWidget, QListWidgetItem,
)

from ...core.config import DB_PATH, DATA_DIR, PROJECT_ROOT
from ...core.db import DatabaseManager
from ...core.secrets_manager import SecretsManager
from ..widgets.common import SecretLineEdit


class SettingsPage(QWidget):
    db_switched = Signal()
    def __init__(self, db: DatabaseManager, secrets: SecretsManager, parent=None):
        super().__init__(parent)
        self._db = db
        self._secrets = secrets
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # ── Global responsive stylesheet ─────────────────────
        self.setStyleSheet("""
            QGroupBox {
                margin-top: 10px;
                padding: 14px 12px 12px 12px;
                font-weight: bold;
                font-size: 13px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                padding: 0 6px;
            }
            QLabel { margin-right: 4px; }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                padding: 4px 6px;
                min-height: 26px;
            }
            QPushButton {
                min-height: 32px;
            }
        """)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        header = QLabel("Settings & Security")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #1e1e2e;")
        layout.addWidget(header)

        # ── API Keys (Multi-token Apify) ──────────────────────
        keys_group = QGroupBox("Apify API Management")
        keys_layout = QVBoxLayout(keys_group)

        # Instructions
        info_label = QLabel(
            "Manage multiple Apify API tokens for failover and rotation.\n"
            "Add at least one token; requests will automatically rotate through and fallback on failure."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #666; font-size: 12px; margin-bottom: 8px;")
        keys_layout.addWidget(info_label)

        # Token list
        self.token_list = QListWidget()
        self.token_list.setMaximumHeight(120)
        keys_layout.addWidget(QLabel("Active Tokens:"))
        keys_layout.addWidget(self.token_list)

        # Add token input and button
        add_layout = QHBoxLayout()
        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("Paste Apify API token…")
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        add_layout.addWidget(self.token_input)

        btn_add_token = QPushButton("Add Token")
        btn_add_token.setStyleSheet("background: #a6e3a1; color: #1e1e2e; border: none; padding: 6px 16px; border-radius: 4px; font-weight: bold;")
        btn_add_token.clicked.connect(self._add_apify_token)
        add_layout.addWidget(btn_add_token)
        keys_layout.addLayout(add_layout)

        # Remove token button
        btn_remove_token = QPushButton("Remove Selected Token")
        btn_remove_token.setStyleSheet("background: #f38ba8; color: white; border: none; padding: 6px 16px; border-radius: 4px; font-weight: bold;")
        btn_remove_token.clicked.connect(self._remove_apify_token)
        keys_layout.addWidget(btn_remove_token)

        # Status
        self.apify_status = QLabel()
        self.apify_status.setStyleSheet("color: #a6e3a1; font-weight: bold;")
        keys_layout.addWidget(self.apify_status)

        layout.addWidget(keys_group)

        # ── General Settings ──────────────────────────────────
        gen_group = QGroupBox("General Settings")
        gen_form = QFormLayout(gen_group)

        self.ed_quota = QSpinBox()
        self.ed_quota.setRange(1, 500)
        self.ed_quota.setValue(50)
        gen_form.addRow("Score Quota (top N):", self.ed_quota)

        self.ed_language = QLineEdit("en")
        gen_form.addRow("Language:", self.ed_language)

        self.chk_mock = QCheckBox("Default Mock Mode")
        gen_form.addRow("", self.chk_mock)

        btn_save_settings = QPushButton("Save Settings")
        btn_save_settings.setStyleSheet("background: #89b4fa; color: white; border: none; padding: 8px 16px; border-radius: 4px; font-weight: bold;")
        btn_save_settings.clicked.connect(self._save_settings)
        gen_form.addRow("", btn_save_settings)
        layout.addWidget(gen_group)

        # ── Per-Stage Provider Selection ──────────────────────
        stage_group = QGroupBox("Pipeline Stage Providers")
        stage_form = QFormLayout(stage_group)
        stage_form.setVerticalSpacing(10)
        stage_form.setHorizontalSpacing(14)

        hint = QLabel(
            "Choose which provider runs each pipeline stage. "
            "\"Auto\" picks the first enabled local provider."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; font-size: 12px; margin-bottom: 6px;")
        stage_form.addRow(hint)

        self.cb_prefilter_provider = QComboBox()
        stage_form.addRow("Prefilter:", self.cb_prefilter_provider)

        self.cb_analysis_provider = QComboBox()
        stage_form.addRow("Analysis (Score + Enrich):", self.cb_analysis_provider)

        btn_save_stages = QPushButton("Save Stage Providers")
        btn_save_stages.setStyleSheet(
            "background: #89b4fa; color: white; border: none; "
            "padding: 8px 16px; border-radius: 4px; font-weight: bold;"
        )
        btn_save_stages.clicked.connect(self._save_stage_providers)
        stage_form.addRow("", btn_save_stages)

        layout.addWidget(stage_group)

        # ── Database Configuration ─────────────────────────
        db_group = QGroupBox("Database Configuration")
        db_layout = QVBoxLayout(db_group)

        # Current path display
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Current DB:"))
        self.db_path_label = QLabel(str(self._db.db_path))
        self.db_path_label.setStyleSheet("color: #666; font-size: 12px;")
        self.db_path_label.setWordWrap(True)
        path_row.addWidget(self.db_path_label, 1)
        db_layout.addLayout(path_row)

        # Path input + browse
        input_row = QHBoxLayout()
        self.db_path_input = QLineEdit()
        self.db_path_input.setPlaceholderText("Enter path to .db file or use Browse…")
        input_row.addWidget(self.db_path_input, 1)

        btn_browse_db = QPushButton("Browse…")
        btn_browse_db.setMaximumWidth(80)
        btn_browse_db.clicked.connect(self._browse_db)
        input_row.addWidget(btn_browse_db)
        db_layout.addLayout(input_row)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_load_db = QPushButton("Load Database")
        btn_load_db.setStyleSheet(
            "background: #89b4fa; color: white; border: none; "
            "padding: 6px 16px; border-radius: 4px; font-weight: bold;"
        )
        btn_load_db.clicked.connect(self._load_database)
        btn_row.addWidget(btn_load_db)

        btn_create_db = QPushButton("Create New Database")
        btn_create_db.setStyleSheet(
            "background: #a6e3a1; color: #1e1e2e; border: none; "
            "padding: 6px 16px; border-radius: 4px; font-weight: bold;"
        )
        btn_create_db.clicked.connect(self._create_database)
        btn_row.addWidget(btn_create_db)

        btn_row.addStretch()
        db_layout.addLayout(btn_row)

        layout.addWidget(db_group)

        # ── Export / Import ───────────────────────────────────
        io_group = QGroupBox("Export / Import")
        io_layout = QHBoxLayout(io_group)

        btn_export_settings = QPushButton("Export Settings JSON")
        btn_export_settings.clicked.connect(self._export_settings)
        io_layout.addWidget(btn_export_settings)

        btn_export_actors = QPushButton("Export Actors JSON")
        btn_export_actors.clicked.connect(self._export_actors)
        io_layout.addWidget(btn_export_actors)

        btn_export_keywords = QPushButton("Export Keywords JSON")
        btn_export_keywords.clicked.connect(self._export_keywords)
        io_layout.addWidget(btn_export_keywords)

        btn_import = QPushButton("Import JSON…")
        btn_import.clicked.connect(self._import_json)
        io_layout.addWidget(btn_import)

        layout.addWidget(io_group)

        # ── Secrets management ────────────────────────────────
        sec_group = QGroupBox("Security")
        sec_layout = QHBoxLayout(sec_group)

        btn_reset = QPushButton("Reset All Secrets")
        btn_reset.setStyleSheet("background: #f38ba8; color: white; border: none; padding: 8px 16px; border-radius: 4px;")
        btn_reset.clicked.connect(self._reset_secrets)
        sec_layout.addWidget(btn_reset)

        sec_layout.addStretch()
        layout.addWidget(sec_group)

        # ── Scheduling ────────────────────────────────────────
        sched_group = QGroupBox("Scheduling (Windows Task Scheduler)")
        sched_layout = QVBoxLayout(sched_group)

        info_text = QLabel(
            "To schedule automatic pipeline runs:\n"
            "1. Use the 'Generate .bat' button to create a batch script\n"
            "2. Open Windows Task Scheduler (taskschd.msc)\n"
            "3. Create a new task pointing to the .bat script\n"
            "4. Set the trigger (e.g. daily at 8:00 AM)\n\n"
            "CLI command: python -m app.pipeline --once"
        )
        info_text.setWordWrap(True)
        info_text.setStyleSheet("color: #666; font-size: 12px;")
        sched_layout.addWidget(info_text)

        btn_gen_bat = QPushButton("Generate .bat Script")
        btn_gen_bat.clicked.connect(self._generate_bat)
        sched_layout.addWidget(btn_gen_bat)

        layout.addWidget(sched_group)
        layout.addStretch()

        scroll.setWidget(container)
        outer.addWidget(scroll)

    # ── Methods ───────────────────────────────────────────────
    def _add_apify_token(self):
        """Add a new Apify token to the list."""
        token = self.token_input.text().strip()
        if not token:
            QMessageBox.warning(self, "No token", "Please enter an Apify API token")
            return
        
        try:
            self._secrets.add_apify_token(token)
            self.token_input.clear()
            self.refresh()
            QMessageBox.information(self, "Success", "Token added successfully")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to add token: {e}")

    def _remove_apify_token(self):
        """Remove selected token from the list."""
        current_item = self.token_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "No selection", "Please select a token to remove")
            return
        
        token_preview = current_item.text()
        # Extract full token from the stored data
        token = current_item.data(256)  # Custom role for storing full token
        
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Remove token {token_preview}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                self._secrets.remove_apify_token(token)
                self.refresh()
                QMessageBox.information(self, "Success", "Token removed successfully")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to remove token: {e}")

    def _mask_token(self, token: str) -> str:
        """Return masked version of token (first 10 + ... + last 4 chars)."""
        if len(token) <= 14:
            return token
        return f"{token[:10]}...{token[-4:]}"

    def _browse_db(self):
        """Open file picker for .db file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Database File", str(DATA_DIR), "SQLite Database (*.db);;All Files (*)"
        )
        if path:
            self.db_path_input.setText(path)

    def _load_database(self):
        """Switch to the database at the entered path."""
        path = self.db_path_input.text().strip()
        if not path:
            QMessageBox.warning(self, "No Path", "Enter or browse for a database file path.")
            return

        p = Path(path)
        if not p.exists():
            QMessageBox.critical(self, "Not Found", f"File does not exist:\n{p}")
            return

        if not p.suffix.lower() == ".db":
            reply = QMessageBox.question(
                self, "Non-standard Extension",
                f"File does not have a .db extension:\n{p.name}\n\nLoad anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        reply = QMessageBox.question(
            self, "Switch Database",
            f"Switch to database:\n{p}\n\nThe current connection will be closed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            self._db.switch_database(p)
            self._secrets = SecretsManager(p)
            self.db_path_label.setText(str(p))
            self.db_path_input.clear()
            self.refresh()
            self.db_switched.emit()
            QMessageBox.information(self, "Success", f"Loaded database:\n{p}")
        except FileNotFoundError as e:
            QMessageBox.critical(self, "Error", str(e))
        except ValueError as e:
            QMessageBox.critical(self, "Invalid Database", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load database:\n{e}")

    def _create_database(self):
        """Create a new empty database with full schema."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Create New Database", str(DATA_DIR / "new_leads.db"),
            "SQLite Database (*.db)"
        )
        if not path:
            return

        p = Path(path)
        if p.exists():
            reply = QMessageBox.question(
                self, "File Exists",
                f"File already exists:\n{p.name}\n\nOverwrite and create a fresh database?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            p.unlink()

        try:
            DatabaseManager.create_new_database(p)
            QMessageBox.information(
                self, "Created",
                f"New database created at:\n{p}\n\n"
                "Use 'Load Database' to switch to it."
            )
            self.db_path_input.setText(str(p))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create database:\n{e}")

    def _save_settings(self):
        self._db.set_setting("top_n_for_scoring", self.ed_quota.value())
        self._db.set_setting("language", self.ed_language.text())
        self._db.set_setting("mock_run", self.chk_mock.isChecked())
        QMessageBox.information(self, "Saved", "Settings saved.")

    def _export_settings(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Settings", "settings_export.json", "JSON (*.json)")
        if not path:
            return
        from ...core.config import get_all_settings
        with self._db.connect() as con:
            settings = get_all_settings(con)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        QMessageBox.information(self, "Exported", f"Settings exported to {path}")

    def _export_actors(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Actors", "actors_export.json", "JSON (*.json)")
        if not path:
            return
        actors = self._db.get_actors()
        data = []
        for a in actors:
            data.append({
                "actor_name": a.actor_name, "enabled": a.enabled, "source": a.source,
                "actor_id": a.actor_id, "input_template_json": a.input_template_json,
                "query_strategy_json": a.query_strategy_json,
                "output_mapping_json": a.output_mapping_json,
                "transform_hook": a.transform_hook, "notes": a.notes,
                "allowed_groups_json": a.allowed_groups_json,
                "extraction_rules": a.extraction_rules,
            })
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        QMessageBox.information(self, "Exported", f"{len(data)} actors exported to {path}")

    def _export_keywords(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Keywords", "keywords_export.json", "JSON (*.json)")
        if not path:
            return
        keywords = self._db.get_keywords()
        data = [{"keyword": k.keyword, "status": k.status, "weight": k.weight,
                  "added_by": k.added_by, "notes": k.notes} for k in keywords]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        QMessageBox.information(self, "Exported", f"{len(data)} keywords exported to {path}")

    def _import_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import JSON", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to parse JSON: {e}")
            return

        if isinstance(data, list):
            imported = 0
            for item in data:
                if "actor_name" in item:
                    from ...core.models import Actor
                    a = Actor(**{k: v for k, v in item.items() if k in Actor.__dataclass_fields__})
                    self._db.save_actor(a)
                    imported += 1
                elif "keyword" in item:
                    from ...core.models import Keyword
                    k = Keyword(**{k: v for k, v in item.items() if k in Keyword.__dataclass_fields__})
                    self._db.save_keyword(k)
                    imported += 1
            QMessageBox.information(self, "Imported", f"Imported {imported} items")
        elif isinstance(data, dict):
            # Settings dict
            for k, v in data.items():
                self._db.set_setting(k, v)
            QMessageBox.information(self, "Imported", f"Imported {len(data)} settings")

    def _reset_secrets(self):
        reply = QMessageBox.warning(
            self, "Reset Secrets",
            "This will delete all stored API keys and tokens. Are you sure?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            for key in self._secrets.list_keys():
                self._secrets.delete_secret(key)
            QMessageBox.information(self, "Done", "All secrets have been reset.")
            self.refresh()

    def _generate_bat(self):
        python_exe = sys.executable
        src_dir = str(PROJECT_ROOT / "src")
        bat_content = f"""@echo off
REM LeadsScraper2 – Scheduled Pipeline Run
cd /d "{src_dir}"
"{python_exe}" -m app.pipeline --once
if %ERRORLEVEL% NEQ 0 (
    echo Pipeline failed with error code %ERRORLEVEL%
    pause
)
"""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Batch Script", str(PROJECT_ROOT / "run_pipeline.bat"), "Batch (*.bat)"
        )
        if path:
            with open(path, "w") as f:
                f.write(bat_content)
            QMessageBox.information(self, "Saved",
                f"Batch script saved to {path}\n\n"
                "To schedule:\n"
                "1. Open Task Scheduler (taskschd.msc)\n"
                "2. Create Basic Task → set trigger → Action: Start a program\n"
                f"3. Program: {path}")

    def _save_stage_providers(self):
        from ...pipeline.provider_manager import ProviderManager
        pm = ProviderManager(self._db)
        for stage, combo in (
            ("prefilter", self.cb_prefilter_provider),
            ("analysis", self.cb_analysis_provider),
        ):
            provider_id = combo.currentData()
            if provider_id:  # a specific provider chosen
                pm.configure_stage_provider(stage, provider_id)
            else:  # "Auto" selected → clear override
                pm.reset_stage_to_default(stage)
        QMessageBox.information(self, "Saved", "Stage provider settings saved.")

    def refresh(self):
        # Refresh Apify token list
        tokens = self._secrets.get_apify_tokens()
        self.token_list.clear()
        for token in tokens:
            masked = self._mask_token(token)
            item = QListWidgetItem(masked)
            item.setData(256, token)  # Store full token in custom role
            self.token_list.addItem(item)
        
        # Update status
        if tokens:
            self.apify_status.setText(f"✅ {len(tokens)} token{'s' if len(tokens) != 1 else ''} configured")
        else:
            self.apify_status.setText("❌ No tokens configured")

        self.ed_quota.setValue(self._db.get_setting("top_n_for_scoring", 50))
        self.ed_language.setText(self._db.get_setting("language", "en"))
        self.chk_mock.setChecked(self._db.get_setting("mock_run", False))

        # Populate stage-provider combos
        providers = self._db.get_providers()
        for stage, combo in (
            ("prefilter", self.cb_prefilter_provider),
            ("analysis", self.cb_analysis_provider),
        ):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Auto (first enabled)", None)
            for p in providers:
                label = f"{p.display_name}  {'✅' if p.enabled else '❌'}"
                combo.addItem(label, p.provider_id)
            # Select currently configured provider
            cfg = self._db.get_setting(f"provider_{stage}", {})
            pid = cfg.get("provider_id", "")
            idx = 0
            for i in range(combo.count()):
                if combo.itemData(i) == pid:
                    idx = i
                    break
            combo.setCurrentIndex(idx)
            combo.blockSignals(False)
