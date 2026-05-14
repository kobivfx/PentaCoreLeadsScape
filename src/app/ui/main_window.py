"""Main application window with sidebar navigation."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QSettings
from PySide6.QtGui import QIcon, QFont, QAction
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QStackedWidget, QVBoxLayout, QWidget, QSplitter,
    QStatusBar, QProgressBar, QMenuBar,
)

from ..core.config import DB_PATH, DATA_DIR
from ..core.db import DatabaseManager
from ..core.secrets_manager import SecretsManager
from .pages.dashboard import DashboardPage
from .pages.leads import LeadsPage
from .pages.keywords import KeywordsPage
from .pages.actors import ActorsPage
from .pages.providers_page import ProvidersPage
from .pages.runs_logs import RunsLogsPage
from .pages.settings_page import SettingsPage
from .pages.clients_page import ClientsPage


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pentacore LeadsScraper")
        self.setMinimumSize(1200, 750)
        self.resize(1400, 850)

        # Core services
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        settings = QSettings("Pentacore", "LeadsScraper2")
        last_db = settings.value("last_db_path", "")
        db_path = Path(last_db) if last_db and Path(last_db).exists() else DB_PATH
        self.db = DatabaseManager(db_path)
        self.secrets = SecretsManager(db_path)
        if db_path != DB_PATH:
            self.setWindowTitle(f"Pentacore LeadsScraper – {db_path.name}")

        # Worker tracking
        self._worker = None
        self._thread = None

        self._build_ui()
        self._build_statusbar()

    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar
        sidebar = QWidget()
        sidebar.setFixedWidth(200)
        sidebar.setStyleSheet("""
            QWidget { background: #1e1e2e; }
            QListWidget { background: transparent; border: none; color: #cdd6f4; font-size: 14px; }
            QListWidget::item { padding: 12px 16px; border-radius: 4px; margin: 2px 8px; }
            QListWidget::item:selected { background: #45475a; color: #89b4fa; }
            QListWidget::item:hover { background: #313244; }
        """)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 10, 0, 10)

        title = QLabel("PentaScraper")
        title.setStyleSheet("color: #89b4fa; font-size: 18px; font-weight: bold; padding: 12px 16px;")
        sidebar_layout.addWidget(title)

        self.nav_list = QListWidget()
        nav_items = [
            ("Dashboard", "📊"),
            ("Leads", "🎯"),
            ("Clients", "🏢"),
            ("Groups", "🔑"),
            ("Actors", "🤖"),
            ("Providers", "🧠"),
            ("Runs & Logs", "📋"),
            ("Settings", "⚙️"),
        ]
        for label, icon in nav_items:
            item = QListWidgetItem(f"  {icon}  {label}")
            item.setSizeHint(QSize(180, 44))
            self.nav_list.addItem(item)

        self.nav_list.setCurrentRow(0)
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        sidebar_layout.addWidget(self.nav_list)
        sidebar_layout.addStretch()

        main_layout.addWidget(sidebar)

        # Pages stack
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("QStackedWidget { background: #f5f5f5; }")

        self.dashboard_page = DashboardPage(self.db, self.secrets, self)
        self.leads_page = LeadsPage(self.db, self)
        self.clients_page = ClientsPage(self.db, self)
        self.keywords_page = KeywordsPage(self.db, self)
        self.actors_page = ActorsPage(self.db, self)
        self.providers_page = ProvidersPage(self.db, self.secrets, self)
        self.runs_page = RunsLogsPage(self.db, self)
        self.settings_page = SettingsPage(self.db, self.secrets, self)

        self.stack.addWidget(self.dashboard_page)
        self.stack.addWidget(self.leads_page)
        self.stack.addWidget(self.clients_page)
        self.stack.addWidget(self.keywords_page)
        self.stack.addWidget(self.actors_page)
        self.stack.addWidget(self.providers_page)
        self.stack.addWidget(self.runs_page)
        self.stack.addWidget(self.settings_page)

        main_layout.addWidget(self.stack)

        # Connect dashboard signals
        self.dashboard_page.run_requested.connect(self._start_run)
        self.dashboard_page.stop_requested.connect(self._stop_run)

        # Connect clients → leads navigation
        self.clients_page.navigate_to_leads.connect(self._navigate_to_leads)

        # Connect settings DB switch signal
        self.settings_page.db_switched.connect(self._on_db_switched)

    def _build_statusbar(self):
        self.statusBar().showMessage("Ready")
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(200)
        self.progress_bar.setVisible(False)
        self.statusBar().addPermanentWidget(self.progress_bar)

    def _on_nav_changed(self, index: int):
        self.stack.setCurrentIndex(index)
        # Refresh page data
        page = self.stack.widget(index)
        if hasattr(page, "refresh"):
            page.refresh()

    def _navigate_to_leads(self, client_name: str):
        """Switch to Leads tab and search by client_name."""
        self.nav_list.setCurrentRow(1)  # Leads tab index
        self.leads_page.search_by_client(client_name)

    def _on_db_switched(self):
        """Refresh all pages after the database file has been switched."""
        self.secrets = SecretsManager(self.db.db_path)
        self.setWindowTitle(f"Pentacore LeadsScraper – {self.db.db_path.name}")
        # Persist last used DB path
        QSettings("Pentacore", "LeadsScraper2").setValue(
            "last_db_path", str(self.db.db_path)
        )
        for i in range(self.stack.count()):
            page = self.stack.widget(i)
            if hasattr(page, "refresh"):
                page.refresh()
        self.statusBar().showMessage(f"Switched to {self.db.db_path.name}")

    # ── Pipeline control ──────────────────────────────────────
    def _start_run(self, dry_run: bool = False, mock_run: bool = False, group_ids: list = None):
        if group_ids is None:
            group_ids = ["all"]
        if self._thread and self._thread.isRunning():
            self.statusBar().showMessage("Pipeline already running!")
            return

        from .workers import start_pipeline_worker
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.statusBar().showMessage("Pipeline starting…")

        self._thread, self._worker = start_pipeline_worker(
            db=self.db,
            secrets=self.secrets,
            dry_run=dry_run,
            mock_run=mock_run,
            group_ids=group_ids,
            progress_slot=self._on_progress,
            finished_slot=self._on_finished,
            error_slot=self._on_error,
        )
        self._thread.finished.connect(self._cleanup_thread)

    def _stop_run(self):
        if self._worker:
            self._worker.cancel()
            self.statusBar().showMessage("Cancelling pipeline…")

    def _on_progress(self, msg: str, pct: int):
        self.statusBar().showMessage(msg)
        if pct >= 0:
            self.progress_bar.setValue(pct)

    def _on_finished(self, run_id: str, status: str):
        self.progress_bar.setVisible(False)
        self.statusBar().showMessage(f"Pipeline finished: {status} (run {run_id})")
        # Refresh pages
        self.dashboard_page.refresh()
        if self.stack.currentWidget() == self.leads_page:
            self.leads_page.refresh()

    def _on_error(self, error_msg: str):
        self.progress_bar.setVisible(False)
        self.statusBar().showMessage(f"Pipeline error: {error_msg}")

    def _cleanup_thread(self):
        """Called when the QThread has actually stopped."""
        self._worker = None
        self._thread = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()
