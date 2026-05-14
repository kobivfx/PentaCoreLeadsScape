"""Providers (Agent/LLM) configuration page."""
from __future__ import annotations

import json
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QTabWidget,
    QVBoxLayout, QWidget, QCheckBox, QTextEdit,
)

from ...core.db import DatabaseManager
from ...core.models import Provider
from ...core.secrets_manager import SecretsManager
from ..widgets.common import SecretLineEdit


class ProvidersPage(QWidget):
    def __init__(self, db: DatabaseManager, secrets: SecretsManager, parent=None):
        super().__init__(parent)
        self._db = db
        self._secrets = secrets
        self._current: Provider | None = None
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
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                padding: 4px 6px;
                min-height: 28px;
            }
        """)

        header = QLabel("Scoring Providers (Agent/LLM)")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #1e1e2e;")
        header.setMaximumHeight(36)
        layout.addWidget(header)

        # Active provider selector
        active_row = QHBoxLayout()
        active_row.setSpacing(10)
        active_row.addWidget(QLabel("Active Provider:"))
        self.active_combo = QComboBox()
        self.active_combo.currentTextChanged.connect(self._on_active_changed)
        active_row.addWidget(self.active_combo)
        active_row.addStretch()
        layout.addLayout(active_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Provider list (left – fixed)
        self.provider_list = QListWidget()
        self.provider_list.setMaximumWidth(250)
        self.provider_list.setMinimumWidth(180)
        self.provider_list.currentRowChanged.connect(self._on_provider_selected)
        splitter.addWidget(self.provider_list)

        # ══════════════════════════════════════════════════════
        # Right panel – 3 main tabs
        # ══════════════════════════════════════════════════════
        right_tabs = QTabWidget()

        # ── TAB 1: Configuration ──────────────────────────────
        cfg_scroll = QScrollArea()
        cfg_scroll.setWidgetResizable(True)
        cfg_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        cfg_widget = QWidget()
        cfg_layout = QVBoxLayout(cfg_widget)
        cfg_layout.setContentsMargins(8, 8, 8, 8)
        cfg_layout.setSpacing(14)

        # Provider Configuration
        form_group = QGroupBox("Provider Configuration")
        form = QFormLayout(form_group)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(14)
        form.setContentsMargins(12, 18, 12, 12)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.ed_id = QLineEdit()
        self.ed_id.setReadOnly(True)
        self.ed_id.setStyleSheet("background: #f0f0f0;")
        form.addRow("ID:", self.ed_id)

        self.ed_display = QLineEdit()
        form.addRow("Display Name:", self.ed_display)

        self.ed_enabled = QCheckBox("Enabled")
        form.addRow("", self.ed_enabled)

        cfg_layout.addWidget(form_group)

        # API Key
        key_group = QGroupBox("API Key")
        key_form = QFormLayout(key_group)
        key_form.setVerticalSpacing(10)
        key_form.setHorizontalSpacing(14)
        key_form.setContentsMargins(12, 18, 12, 12)
        key_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.ed_api_key = SecretLineEdit()
        self.ed_api_key.setPlaceholderText("Enter API key…")
        key_form.addRow("Key:", self.ed_api_key)
        self.key_status = QLabel()
        key_form.addRow("Status:", self.key_status)
        cfg_layout.addWidget(key_group)

        # Model Settings
        config_group = QGroupBox("Model Settings")
        config_form = QFormLayout(config_group)
        config_form.setVerticalSpacing(10)
        config_form.setHorizontalSpacing(14)
        config_form.setContentsMargins(12, 18, 12, 12)
        config_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.ed_model = QLineEdit()
        config_form.addRow("Model:", self.ed_model)

        self.ed_temperature = QDoubleSpinBox()
        self.ed_temperature.setRange(0.0, 2.0)
        self.ed_temperature.setSingleStep(0.1)
        self.ed_temperature.setDecimals(2)
        config_form.addRow("Temperature:", self.ed_temperature)

        self.ed_max_tokens = QSpinBox()
        self.ed_max_tokens.setRange(100, 16000)
        self.ed_max_tokens.setSingleStep(256)
        config_form.addRow("Max Output Tokens:", self.ed_max_tokens)

        self.ed_rate_limit = QSpinBox()
        self.ed_rate_limit.setRange(1, 1000)
        config_form.addRow("Rate Limit (RPM):", self.ed_rate_limit)

        cfg_layout.addWidget(config_group)

        # Local LLM Settings (visible only for local_llm)
        self.local_group = QGroupBox("Local LLM Settings")
        local_form = QFormLayout(self.local_group)
        local_form.setVerticalSpacing(10)
        local_form.setHorizontalSpacing(14)
        local_form.setContentsMargins(12, 18, 12, 12)
        local_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.ed_mode = QComboBox()
        self.ed_mode.addItems(["http", "direct"])
        local_form.addRow("Mode:", self.ed_mode)

        self.ed_http_url = QLineEdit()
        self.ed_http_url.setPlaceholderText("http://localhost:8080")
        local_form.addRow("HTTP Base URL:", self.ed_http_url)

        self.ed_http_model = QLineEdit()
        self.ed_http_model.setPlaceholderText("gemma-4")
        local_form.addRow("HTTP Model Name:", self.ed_http_model)

        self.ed_model_path = QLineEdit()
        self.ed_model_path.setPlaceholderText("C:/models/gemma-4.gguf")
        local_form.addRow("Model Path (.gguf):", self.ed_model_path)

        self.ed_context_size = QSpinBox()
        self.ed_context_size.setRange(512, 131072)
        self.ed_context_size.setSingleStep(1024)
        self.ed_context_size.setValue(8192)
        local_form.addRow("Context Size:", self.ed_context_size)

        self.ed_gpu_layers = QSpinBox()
        self.ed_gpu_layers.setRange(-1, 999)
        self.ed_gpu_layers.setValue(-1)
        local_form.addRow("GPU Layers (-1=all):", self.ed_gpu_layers)

        self.local_group.setVisible(False)
        cfg_layout.addWidget(self.local_group)

        # Qwen LLM Settings (visible only for qwen)
        self.qwen_group = QGroupBox("Qwen LLM Settings")
        qwen_form = QFormLayout(self.qwen_group)
        qwen_form.setVerticalSpacing(10)
        qwen_form.setHorizontalSpacing(14)
        qwen_form.setContentsMargins(12, 18, 12, 12)
        qwen_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.qw_mode = QComboBox()
        self.qw_mode.addItems(["http", "direct"])
        qwen_form.addRow("Mode:", self.qw_mode)

        self.qw_http_url = QLineEdit()
        self.qw_http_url.setPlaceholderText("http://localhost:11434")
        qwen_form.addRow("HTTP Base URL:", self.qw_http_url)

        self.qw_http_model = QLineEdit()
        self.qw_http_model.setPlaceholderText("qwen")
        qwen_form.addRow("HTTP Model Name:", self.qw_http_model)

        self.qw_model_path = QLineEdit()
        self.qw_model_path.setPlaceholderText("C:/models/Qwen3.5-9B.gguf")
        qwen_form.addRow("Model Path (.gguf):", self.qw_model_path)

        self.qw_context_size = QSpinBox()
        self.qw_context_size.setRange(512, 131072)
        self.qw_context_size.setSingleStep(1024)
        self.qw_context_size.setValue(8192)
        qwen_form.addRow("Context Size:", self.qw_context_size)

        self.qw_gpu_layers = QSpinBox()
        self.qw_gpu_layers.setRange(-1, 999)
        self.qw_gpu_layers.setValue(-1)
        qwen_form.addRow("GPU Layers (-1=all):", self.qw_gpu_layers)

        self.qwen_group.setVisible(False)
        cfg_layout.addWidget(self.qwen_group)

        # DeepSeek Settings (visible only for deepseek)
        self.deepseek_group = QGroupBox("DeepSeek API Settings")
        ds_form = QFormLayout(self.deepseek_group)
        ds_form.setVerticalSpacing(10)
        ds_form.setHorizontalSpacing(14)
        ds_form.setContentsMargins(12, 18, 12, 12)
        ds_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.ds_base_url = QLineEdit()
        self.ds_base_url.setPlaceholderText("https://api.deepseek.com")
        ds_form.addRow("Base URL:", self.ds_base_url)

        self.deepseek_group.setVisible(False)
        cfg_layout.addWidget(self.deepseek_group)

        # Action Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_save = QPushButton("Save Provider")
        btn_save.setStyleSheet("background: #89b4fa; color: white; border: none; padding: 10px 24px; border-radius: 4px; font-weight: bold;")
        btn_save.clicked.connect(self._save_provider)
        btn_row.addWidget(btn_save)

        btn_test = QPushButton("Test Connection")
        btn_test.setStyleSheet("background: #cba6f7; color: white; border: none; padding: 10px 24px; border-radius: 4px;")
        btn_test.clicked.connect(self._test_provider)
        btn_row.addWidget(btn_test)
        btn_row.addStretch()
        cfg_layout.addLayout(btn_row)

        # Test result
        self.test_output = QTextEdit()
        self.test_output.setReadOnly(True)
        self.test_output.setMaximumHeight(200)
        self.test_output.setPlaceholderText("Test results will appear here…")
        cfg_layout.addWidget(self.test_output)

        cfg_layout.addStretch()
        cfg_scroll.setWidget(cfg_widget)
        right_tabs.addTab(cfg_scroll, "Configuration")

        # ── TAB 2: Pipeline Testing ───────────────────────────
        test_scroll = QScrollArea()
        test_scroll.setWidgetResizable(True)
        test_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        test_widget = QWidget()
        test_outer = QVBoxLayout(test_widget)
        test_outer.setContentsMargins(8, 8, 8, 8)
        testing_tabs = QTabWidget()

        # Sub-tab 1: Prefilter Test
        pf_tab = QWidget()
        pf_layout = QVBoxLayout(pf_tab)
        pf_layout.setContentsMargins(8, 8, 8, 8)
        pf_layout.setSpacing(8)
        pf_layout.addWidget(QLabel("Paste sample text to run through the prefilter:"))
        self.pf_test_input = QTextEdit()
        self.pf_test_input.setMinimumHeight(80)
        self.pf_test_input.setPlaceholderText(
            "e.g. Studio XYZ announces partnership with outsourcing vendor for 3D cinematics…"
        )
        pf_layout.addWidget(self.pf_test_input)

        pf_btn_row = QHBoxLayout()
        btn_pf_test = QPushButton("Run Prefilter Test")
        btn_pf_test.setStyleSheet("background: #f9e2af; color: #1e1e2e; border: none; padding: 8px 16px; border-radius: 4px; font-weight: bold;")
        btn_pf_test.clicked.connect(self._test_prefilter)
        pf_btn_row.addWidget(btn_pf_test)

        self.chk_show_prompt = QCheckBox("Show prompt")
        self.chk_show_prompt.setToolTip("Display the exact prompt sent to the model")
        pf_btn_row.addWidget(self.chk_show_prompt)
        pf_btn_row.addStretch()
        pf_layout.addLayout(pf_btn_row)

        self.pf_test_output = QTextEdit()
        self.pf_test_output.setReadOnly(True)
        self.pf_test_output.setMinimumHeight(100)
        self.pf_test_output.setPlaceholderText("Prefilter test results will appear here…")
        pf_layout.addWidget(self.pf_test_output)
        pf_layout.addStretch()

        testing_tabs.addTab(pf_tab, "Test Prefilter")

        # Sub-tab 2: Analysis Test
        an_tab = QWidget()
        an_layout = QVBoxLayout(an_tab)
        an_layout.setContentsMargins(8, 8, 8, 8)
        an_layout.setSpacing(8)
        an_layout.addWidget(QLabel(
            "Test the full analysis (scoring + enrichment) step.\n"
            "Uses the selected provider and the analysis prompt template with {url}, {content}, {author}."
        ))

        an_form = QFormLayout()
        an_form.setVerticalSpacing(6)
        an_form.setHorizontalSpacing(10)
        an_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.an_test_url = QLineEdit()
        self.an_test_url.setPlaceholderText("https://example.com/about")
        an_form.addRow("URL:", self.an_test_url)

        self.an_test_author = QLineEdit()
        self.an_test_author.setPlaceholderText("Author / company name (optional)")
        an_form.addRow("Author:", self.an_test_author)

        self.an_test_content = QTextEdit()
        self.an_test_content.setMinimumHeight(80)
        self.an_test_content.setMaximumHeight(120)
        self.an_test_content.setPlaceholderText(
            "Paste scraped content / description here (optional, sent as {content})…"
        )
        an_form.addRow("Content:", self.an_test_content)

        an_layout.addLayout(an_form)

        an_btn_row = QHBoxLayout()
        btn_an_test = QPushButton("Run Analysis Test")
        btn_an_test.setStyleSheet(
            "background: #a6e3a1; color: #1e1e2e; border: none; "
            "padding: 8px 16px; border-radius: 4px; font-weight: bold;"
        )
        btn_an_test.clicked.connect(self._test_analysis)
        an_btn_row.addWidget(btn_an_test)

        self.chk_show_analysis_prompt = QCheckBox("Show prompt")
        self.chk_show_analysis_prompt.setToolTip("Display the exact prompt sent to the model")
        an_btn_row.addWidget(self.chk_show_analysis_prompt)

        self.chk_show_raw = QCheckBox("Show raw response")
        self.chk_show_raw.setChecked(True)
        self.chk_show_raw.setToolTip("Display the raw LLM response text")
        an_btn_row.addWidget(self.chk_show_raw)

        an_btn_row.addStretch()
        an_layout.addLayout(an_btn_row)

        self.an_test_output = QPlainTextEdit()
        self.an_test_output.setReadOnly(True)
        self.an_test_output.setMinimumHeight(200)
        self.an_test_output.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        self.an_test_output.setPlaceholderText("Analysis test results will appear here…")
        an_layout.addWidget(self.an_test_output)
        an_layout.addStretch()

        testing_tabs.addTab(an_tab, "Test Analysis")

        test_outer.addWidget(testing_tabs)
        test_scroll.setWidget(test_widget)
        right_tabs.addTab(test_scroll, "Testing")

        splitter.addWidget(right_tabs)
        splitter.setSizes([220, 700])
        layout.addWidget(splitter)

    def _on_active_changed(self, text: str):
        if text:
            # Extract provider_id from display
            pid = text.split(" ")[0] if text else ""
            for p in self._db.get_providers():
                if p.provider_id == pid or p.display_name == text:
                    self._db.set_setting("active_provider", p.provider_id)
                    break

    def _on_provider_selected(self, row: int):
        providers = self._db.get_providers()
        if 0 <= row < len(providers):
            p = providers[row]
            self._current = p
            self.ed_id.setText(p.provider_id)
            self.ed_display.setText(p.display_name)
            self.ed_enabled.setChecked(bool(p.enabled))

            # API key
            has_key = self._secrets.has_secret(p.secret_key_name)
            self.key_status.setText("✅ Key is set" if has_key else "❌ Key not set")
            self.ed_api_key.clear()

            # Config
            cfg = p.config
            self.ed_model.setText(cfg.get("model", ""))
            self.ed_temperature.setValue(cfg.get("temperature", 0.2))
            self.ed_max_tokens.setValue(cfg.get("max_output_tokens", cfg.get("max_tokens", 2048)))
            self.ed_rate_limit.setValue(cfg.get("rate_limit_rpm", 15))

            # Local LLM specific
            is_local = p.provider_id == "local_llm"
            self.local_group.setVisible(is_local)
            if is_local:
                mode = cfg.get("mode", "http")
                idx = self.ed_mode.findText(mode)
                if idx >= 0:
                    self.ed_mode.setCurrentIndex(idx)
                self.ed_http_url.setText(cfg.get("http_base_url", "http://localhost:8080"))
                self.ed_http_model.setText(cfg.get("http_model", "gemma-4"))
                self.ed_model_path.setText(cfg.get("model_path", ""))
                self.ed_context_size.setValue(cfg.get("context_size", 8192))
                self.ed_gpu_layers.setValue(cfg.get("n_gpu_layers", -1))

            # Qwen specific
            is_qwen = p.provider_id == "qwen"
            self.qwen_group.setVisible(is_qwen)
            if is_qwen:
                mode = cfg.get("mode", "http")
                idx = self.qw_mode.findText(mode)
                if idx >= 0:
                    self.qw_mode.setCurrentIndex(idx)
                self.qw_http_url.setText(cfg.get("http_base_url", "http://localhost:11434"))
                self.qw_http_model.setText(cfg.get("http_model", "qwen"))
                self.qw_model_path.setText(cfg.get("model_path", ""))
                self.qw_context_size.setValue(cfg.get("context_size", 8192))
                self.qw_gpu_layers.setValue(cfg.get("n_gpu_layers", -1))

            # DeepSeek specific
            is_deepseek = p.provider_id == "deepseek"
            self.deepseek_group.setVisible(is_deepseek)
            if is_deepseek:
                self.ds_base_url.setText(cfg.get("base_url", "https://api.deepseek.com"))

    def _save_provider(self):
        if not self._current:
            return
        cfg = {
            "model": self.ed_model.text(),
            "temperature": self.ed_temperature.value(),
            "max_output_tokens": self.ed_max_tokens.value(),
            "rate_limit_rpm": self.ed_rate_limit.value(),
        }
        # Include local LLM specific config
        if self._current.provider_id == "local_llm":
            cfg.update({
                "mode": self.ed_mode.currentText(),
                "http_base_url": self.ed_http_url.text().strip() or "http://localhost:8080",
                "http_model": self.ed_http_model.text().strip() or "gemma-4",
                "model_path": self.ed_model_path.text().strip(),
                "context_size": self.ed_context_size.value(),
                "n_gpu_layers": self.ed_gpu_layers.value(),
                "max_tokens": self.ed_max_tokens.value(),
            })
            # Invalidate cached model so next use picks up new settings
            from ...providers.local_provider import LocalLLMProvider
            LocalLLMProvider.invalidate_cache()
        elif self._current.provider_id == "qwen":
            cfg.update({
                "mode": self.qw_mode.currentText(),
                "http_base_url": self.qw_http_url.text().strip() or "http://localhost:11434",
                "http_model": self.qw_http_model.text().strip() or "qwen",
                "model_path": self.qw_model_path.text().strip(),
                "context_size": self.qw_context_size.value(),
                "n_gpu_layers": self.qw_gpu_layers.value(),
                "max_tokens": self.ed_max_tokens.value(),
            })
            from ...providers.qwen_provider import QwenProvider
            QwenProvider.invalidate_cache()
        elif self._current.provider_id == "deepseek":
            cfg.update({
                "base_url": self.ds_base_url.text().strip() or "https://api.deepseek.com",
            })
        provider = Provider(
            provider_id=self._current.provider_id,
            enabled=1 if self.ed_enabled.isChecked() else 0,
            display_name=self.ed_display.text(),
            config_json=json.dumps(cfg),
            secret_key_name=self._current.secret_key_name,
        )
        self._db.save_provider(provider)

        # Save API key if entered
        key = self.ed_api_key.text().strip()
        if key:
            self._secrets.set_secret(provider.secret_key_name, key)
            self.key_status.setText("✅ Key is set")
            self.ed_api_key.clear()

        QMessageBox.information(self, "Saved", f"Provider '{provider.display_name}' saved.")
        self.refresh()

    def _current_ui_config(self) -> dict:
        """Build config dict from the current UI field values (not the saved DB values)."""
        cfg = {
            "model": self.ed_model.text(),
            "temperature": self.ed_temperature.value(),
            "max_output_tokens": self.ed_max_tokens.value(),
            "rate_limit_rpm": self.ed_rate_limit.value(),
        }
        if self._current and self._current.provider_id == "local_llm":
            cfg.update({
                "mode": self.ed_mode.currentText(),
                "http_base_url": self.ed_http_url.text().strip() or "http://localhost:8080",
                "http_model": self.ed_http_model.text().strip() or "gemma-4",
                "model_path": self.ed_model_path.text().strip(),
                "context_size": self.ed_context_size.value(),
                "n_gpu_layers": self.ed_gpu_layers.value(),
                "max_tokens": self.ed_max_tokens.value(),
            })
        elif self._current and self._current.provider_id == "qwen":
            cfg.update({
                "mode": self.qw_mode.currentText(),
                "http_base_url": self.qw_http_url.text().strip() or "http://localhost:11434",
                "http_model": self.qw_http_model.text().strip() or "qwen",
                "model_path": self.qw_model_path.text().strip(),
                "context_size": self.qw_context_size.value(),
                "n_gpu_layers": self.qw_gpu_layers.value(),
                "max_tokens": self.ed_max_tokens.value(),
            })
        elif self._current and self._current.provider_id == "deepseek":
            cfg.update({
                "base_url": self.ds_base_url.text().strip() or "https://api.deepseek.com",
            })
        return cfg

    def _test_provider(self):
        if not self._current:
            return
        self.test_output.setPlainText("Testing…")
        QApplication.processEvents()

        cfg = self._current_ui_config()

        # For local_llm, qwen, deepseek, or gemini – do a health-check first
        if self._current.provider_id in ("local_llm", "qwen", "deepseek", "gemini"):
            if self._current.provider_id == "qwen":
                from ...providers.qwen_provider import QwenProvider
                ProviderCls = QwenProvider
            elif self._current.provider_id == "deepseek":
                from ...providers.deepseek_provider import DeepSeekProvider
                ProviderCls = DeepSeekProvider
            elif self._current.provider_id == "gemini":
                from ...providers.gemini_provider import GeminiProvider
                ProviderCls = GeminiProvider
            else:
                from ...providers.local_provider import LocalLLMProvider
                ProviderCls = LocalLLMProvider

            api_key = ""
            if self._current.secret_key_name:
                api_key = self._secrets.get_secret(self._current.secret_key_name) or ""

            try:
                p = ProviderCls(api_key=api_key, config=cfg, mock=False)
            except RuntimeError as e:
                self.test_output.setPlainText(f"❌ Init failed: {e}")
                return

            # Validate config
            err = p.validate_config()
            if err:
                self.test_output.setPlainText(f"❌ Config error: {err}")
                return

            hc = p.health_check()
            rt = hc.get("runtime", {})
            lines = []
            lines.append(f"{'✅' if hc['ok'] else '❌'} Health check: {'OK' if hc['ok'] else 'FAILED'}")
            lines.append(f"Provider: {self._current.provider_id}")
            lines.append(f"Latency: {hc['latency_ms']} ms")
            lines.append(f"Mode: {cfg.get('mode', 'http')}")
            lines.append("")
            lines.append("── Runtime Info ──")
            lines.append(f"Backend: {rt.get('backend', '?')}")
            lines.append(f"GPU offload: {rt.get('gpu_offload', '?')}")
            lines.append(f"GPU layers: {rt.get('gpu_layers', '?')}")
            lines.append(f"Model load: {rt.get('model_load_ms', 0)} ms")
            lines.append(f"Cached: {rt.get('cached', False)}")
            if hc["error"]:
                lines.append(f"\nError: {hc['error']}")
            if hc["raw"]:
                lines.append(f"\nResponse: {hc['raw'][:300]}")
            self.test_output.setPlainText("\n".join(lines))
            return

        # Cloud provider – score a sample candidate
        from ...core.models import LeadCandidate
        from ...providers import get_provider_instance

        api_key = self._secrets.get_secret(self._current.secret_key_name) or ""

        mock = not bool(api_key)
        try:
            provider = get_provider_instance(
                self._current.provider_id, api_key, cfg, mock=mock,
            )
            candidate = LeadCandidate(
                url="https://example.com/test",
                title="Major game studio announces 3D cinematic outsourcing partnership",
                text="Studio XYZ is expanding their pipeline and seeking external 3D animation studios for next-gen game cinematics.",
                source="google",
                domain="example.com",
            )
            context = {
                "keywords": ["game cinematics outsourcing", "3D animation studio"],
                "purpose": "3D animation outsourcing/vendor services",
            }
            import time as _time
            t0 = _time.perf_counter()
            result = provider.score_candidate(candidate, context)
            latency = round((_time.perf_counter() - t0) * 1000)
            lines = [
                f"✅ Test passed {'(mock)' if mock else ''}",
                f"Latency: {latency} ms",
                "",
                json.dumps(json.loads(result.to_json()), indent=2),
            ]
            self.test_output.setPlainText("\n".join(lines))
        except Exception as e:
            self.test_output.setPlainText(f"❌ Error: {e}")

    def _test_prefilter(self):
        """Run a prefilter test with sample text using the local LLM provider."""
        text = self.pf_test_input.toPlainText().strip()
        if not text:
            self.pf_test_output.setPlainText("Paste some sample text first.")
            return

        if not self._current or self._current.provider_id not in ("local_llm", "qwen"):
            self.pf_test_output.setPlainText("❌ Select the Local LLM or Qwen provider first.")
            return

        self.pf_test_output.setPlainText("Running prefilter…")
        QApplication.processEvents()

        if self._current.provider_id == "qwen":
            from ...providers.qwen_provider import QwenProvider as _ProviderCls
        else:
            from ...providers.local_provider import LocalLLMProvider as _ProviderCls
        cfg = self._current_ui_config()

        try:
            p = _ProviderCls(api_key="", config=cfg, mock=False)
            err = p.validate_config()
            if err:
                self.pf_test_output.setPlainText(f"❌ Config error: {err}")
                return

            # Use the same default prompt as the pipeline
            prefilter_prompt = (
                "You are an expert lead-qualification agent for a 3D animation outsourcing studio. Your studio provides: game cinematics, brand mascot animation, animated commercials, product animation, and CGI content, animation feature film, animation IP, animation series, game trailer. "
                "Is the content below have 0.1% (Simply have a company can be our client or mention a game is going to be released) to be your lead? Answer Yes or No only."
            )

            import time as _time
            t0 = _time.perf_counter()
            result, raw = p.prefilter(text, prefilter_prompt,)
            latency = round((_time.perf_counter() - t0) * 1000)

            rt = p.get_runtime_info()

            lines = []
            icon = "✅" if result == "Yes" else "❌"
            lines.append(f"{icon} Result: {result}  |  Latency: {latency} ms")
            lines.append(f"Temperature: {cfg.get('temperature', 0.1)}")
            lines.append("")
            lines.append("── Runtime Info ──")
            lines.append(f"Mode: {rt.get('mode', '?')}")
            lines.append(f"Backend: {rt.get('backend', '?')}")
            lines.append(f"GPU offload: {rt.get('gpu_offload', '?')}")
            lines.append(f"GPU layers: {rt.get('gpu_layers', '?')}")
            lines.append(f"Model load: {rt.get('model_load_ms', 0)} ms")
            lines.append(f"Cached: {rt.get('cached', False)}")
            lines.append("")
            lines.append("── Raw output ──")
            lines.append(raw[:500])

            if self.chk_show_prompt.isChecked():
                full_prompt = p.build_prefilter_prompt(text, prefilter_prompt)
                lines.append("")
                lines.append("── Full prompt sent ──")
                lines.append(full_prompt)

            self.pf_test_output.setPlainText("\n".join(lines))
        except Exception as e:
            self.pf_test_output.setPlainText(f"❌ Error: {e}")

    @staticmethod
    def _extract_json(raw: str) -> str:
        """Extract JSON from an LLM response that may contain markdown fences or surrounding text."""
        m = re.search(r"```(?:json)?\s*\n(.*?)\n\s*```", raw, re.DOTALL)
        if m:
            return m.group(1).strip()
        m = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
        if m:
            return m.group(0)
        return raw.strip()

    def _test_analysis(self):
        """Run a full analysis (scoring + enrichment) test — mirrors real pipeline."""
        url = self.an_test_url.text().strip()
        if not url:
            self.an_test_output.setPlainText("Enter a URL first.")
            return

        if not self._current:
            self.an_test_output.setPlainText("❌ Select a provider first.")
            return

        content = self.an_test_content.toPlainText().strip()
        author = self.an_test_author.text().strip()

        self.an_test_output.setPlainText("Running analysis…")
        QApplication.processEvents()

        cfg = self._current_ui_config()
        pid = self._current.provider_id

        # Get API key
        api_key = ""
        if self._current.secret_key_name:
            api_key = self._secrets.get_secret(self._current.secret_key_name) or ""

        # Instantiate provider (same as pipeline)
        from ...providers import get_provider_instance
        try:
            provider = get_provider_instance(pid, api_key, cfg, mock=False)
        except Exception as e:
            self.an_test_output.setPlainText(f"❌ Init failed: {e}")
            return

        if hasattr(provider, "validate_config"):
            err = provider.validate_config()
            if err:
                self.an_test_output.setPlainText(f"❌ Config error: {err}")
                return

        # Build prompt — uses default analysis prompt (per-group prompts are in Keywords → Groups)
        from ...pipeline.stages.analysis import DEFAULT_ANALYSIS_PROMPT
        prompt_template = DEFAULT_ANALYSIS_PROMPT
        prompt = prompt_template.replace("{url}", url)
        prompt = prompt.replace("{content}", (content or "")[:2000])
        prompt = prompt.replace("{author}", author or "")

        lines = []
        lines.append(f"Provider: {pid} ({type(provider).__name__})")
        lines.append(f"URL: {url}")
        if author:
            lines.append(f"Author: {author}")
        if content:
            lines.append(f"Content: {len(content)} chars")
        lines.append(f"Prompt length: {len(prompt)} chars")

        if self.chk_show_analysis_prompt.isChecked():
            lines.append("")
            lines.append("── Constructed Prompt ──")
            lines.append(prompt)
            lines.append("")

        lines.append("")
        lines.append("── Calling provider… ──")
        self.an_test_output.setPlainText("\n".join(lines))
        QApplication.processEvents()

        # Call provider — same dispatch as pipeline
        import time as _time
        t0 = _time.perf_counter()
        try:
            if hasattr(provider, "analyze"):
                raw = provider.analyze(prompt)
            elif hasattr(provider, "generate"):
                raw = provider.generate(prompt)
            else:
                self.an_test_output.setPlainText("❌ Provider has no analyze() or generate() method.")
                return
            latency = round((_time.perf_counter() - t0) * 1000)
        except Exception as e:
            latency = round((_time.perf_counter() - t0) * 1000)
            lines.append(f"❌ Error ({latency} ms): {e}")
            self.an_test_output.setPlainText("\n".join(lines))
            return

        lines.append(f"✅ Response received ({latency} ms)")
        lines.append("")

        # Tool usage metadata (Gemini urlContext / googleSearch)
        if hasattr(provider, "_last_response") and provider._last_response:
            resp_data = provider._last_response
            cands = resp_data.get("candidates", [])
            if cands:
                cand = cands[0]
                url_ctx = cand.get("urlContextMetadata") or cand.get("url_context_metadata")
                if url_ctx:
                    urls_info = url_ctx.get("urlMetadata") or url_ctx.get("url_metadata", [])
                    lines.append("── Tool: URL Context ──")
                    for u in urls_info:
                        r_url = u.get("retrievedUrl") or u.get("retrieved_url", "?")
                        r_status = u.get("urlRetrievalStatus") or u.get("url_retrieval_status", "?")
                        lines.append(f"  {r_url} → {r_status}")
                    lines.append("")

                grounding = cand.get("groundingMetadata") or cand.get("grounding_metadata")
                if grounding:
                    queries = grounding.get("webSearchQueries") or grounding.get("web_search_queries", [])
                    lines.append(f"── Tool: Google Search ({len(queries)} queries) ──")
                    for q in queries[:5]:
                        lines.append(f"  • {q}")
                    lines.append("")

                if not url_ctx and not grounding:
                    lines.append("⚠ No tool usage detected in response")
                    lines.append(f"  Response keys: {list(cand.keys())}")
                    lines.append("")

        # Parse JSON — same logic as AnalysisStage._analyze_lead
        try:
            cleaned = self._extract_json(raw)
            parsed = json.loads(cleaned)

            lines.append("── Parsed Result ──")
            lines.append(f"  Score:       {parsed.get('score', '–')}")
            lines.append(f"  Reason:      {parsed.get('reason', '–')}")
            lines.append(f"  Client Name: {parsed.get('client_name', '–')}")
            lines.append(f"  Contact:     {parsed.get('contact', '–')}")
            lines.append(f"  Domain:      {parsed.get('domain', '–')}")

            if self.chk_show_raw.isChecked():
                lines.append("")
                lines.append("── Raw JSON ──")
                lines.append(json.dumps(parsed, indent=2, ensure_ascii=False))
        except (json.JSONDecodeError, ValueError):
            lines.append("── Raw Response (not valid JSON) ──")
            lines.append(raw[:2000])

        self.an_test_output.setPlainText("\n".join(lines))

    def refresh(self):
        providers = self._db.get_providers()
        active_id = self._db.get_active_provider_id()

        self.provider_list.clear()
        self.active_combo.blockSignals(True)
        self.active_combo.clear()

        for p in providers:
            status = "✅" if p.enabled else "❌"
            active = " ◀ ACTIVE" if p.provider_id == active_id else ""
            self.provider_list.addItem(f"{status} {p.display_name}{active}")
            if p.enabled:
                self.active_combo.addItem(p.provider_id)

        # Set active
        idx = self.active_combo.findText(active_id)
        if idx >= 0:
            self.active_combo.setCurrentIndex(idx)
        self.active_combo.blockSignals(False)

        if providers:
            self.provider_list.setCurrentRow(0)
