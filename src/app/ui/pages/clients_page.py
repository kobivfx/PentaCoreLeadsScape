"""Clients page – deduplicated client records with detail panel."""
from __future__ import annotations

import webbrowser
from urllib.parse import urlparse

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QPoint, Signal, QThread
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QMenu, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QSplitter, QTableView, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from ...core.db import DatabaseManager
from ...core.models import Client

CLIENT_COLUMNS = [
    ("name", "Client Name"),
    ("domain", "Domain"),
    ("tag", "Type"),
    ("starred", "Starred"),
    ("contacted", "Contacted"),
    ("contact", "Contact"),
    ("client_score", "Score"),
    ("lead_count", "Leads"),
    ("created_at", "Created"),
]


class ClientsTableModel(QAbstractTableModel):
    _SORTABLE = {
        "name": "name",
        "domain": "domain",
        "tag": "tag",
        "contact": "contact",
        "client_score": "client_score",
        "lead_count": "lead_count",
        "created_at": "created_at",
        "starred": "starred",
        "contacted": "contacted",
    }

    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self._db = db
        self._clients: list[Client] = []
        self._search: str | None = None
        self._min_score: int = 0
        self._min_leads: int = 0
        self._starred: bool | None = None
        self._contacted: bool | None = None
        self._order_by: str = "lead_count DESC"

    def refresh(self, search: str | None = None, min_score: int = 0, min_leads: int = 0, 
                starred: bool | None = None, contacted: bool | None = None):
        self._search = search
        self._min_score = min_score
        self._min_leads = min_leads
        self._starred = starred
        self._contacted = contacted
        self.beginResetModel()
        self._clients = self._db.get_clients(
            search=search,
            min_score=min_score,
            min_leads=min_leads,
            starred=starred,
            contacted=contacted,
            order_by=self._order_by,
            limit=99999999,
        )
        self.endResetModel()

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder):
        col_key = CLIENT_COLUMNS[column][0]
        sql_col = self._SORTABLE.get(col_key)
        if not sql_col:
            return
        direction = "ASC" if order == Qt.SortOrder.AscendingOrder else "DESC"
        self._order_by = f"{sql_col} {direction}"
        self.refresh(self._search, self._min_score, self._min_leads, self._starred, self._contacted)

    def rowCount(self, parent=QModelIndex()):
        return len(self._clients)

    def columnCount(self, parent=QModelIndex()):
        return len(CLIENT_COLUMNS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        client = self._clients[index.row()]
        col_key = CLIENT_COLUMNS[index.column()][0]
        
        if role == Qt.ItemDataRole.BackgroundRole:
            # Apply background color to entire row if row_color is set
            if client.row_color:
                return QBrush(QColor(client.row_color))
            return None
        
        if role == Qt.ItemDataRole.DisplayRole:
            if col_key == "starred":
                return "★" if client.starred else ""
            elif col_key == "contacted":
                return "☑" if client.contacted else ""
            elif col_key == "created_at":
                # Display only date part (YYYY-MM-DD)
                val = getattr(client, col_key, "")
                return val[:10] if val else ""
            else:
                val = getattr(client, col_key, "")
                return str(val) if val is not None else ""
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col_key in ("lead_count", "client_score", "created_at", "starred", "contacted"):
                return Qt.AlignmentFlag.AlignCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return CLIENT_COLUMNS[section][1]
        return None

    def get_client_at(self, row: int) -> Client | None:
        if 0 <= row < len(self._clients):
            return self._clients[row]
        return None


class ClientAnalysisWorker(QThread):
    """Background worker for running client analysis."""
    progress = Signal(str, int)
    finished = Signal(int, list)

    def __init__(self, db: DatabaseManager, clients: list[Client], parent=None):
        super().__init__(parent)
        self._db = db
        self._clients = clients

    def run(self):
        from ...pipeline.stages.client_analysis import ClientAnalysisStage
        stage = ClientAnalysisStage(self._db)
        analyzed, errors = stage.analyze_clients(
            self._clients,
            progress_callback=lambda msg, pct: self.progress.emit(msg, pct),
        )
        self.finished.emit(analyzed, errors)


class ClientsPage(QWidget):
    navigate_to_leads = Signal(str)  # emits client_name to search in Leads

    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self._db = db
        self._worker = None
        self._current_client: Client | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(4)

        header = QLabel("Clients")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #1e1e2e;")
        header.setMaximumHeight(30)
        layout.addWidget(header)

        # Tab widget: Main view + Analysis Settings
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._build_main_tab(), "Clients")
        self.tabs.addTab(self._build_analysis_settings_tab(), "Analysis Settings")
        layout.addWidget(self.tabs)

    def _build_main_tab(self) -> QWidget:
        """Build the main Clients tab with table + detail panel."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Search and Filters bar (compact)
        search_filter_layout = QHBoxLayout()
        search_filter_layout.setContentsMargins(0, 4, 0, 4)
        search_filter_layout.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by name, domain, contact…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMaximumWidth(350)
        self.search_input.setFixedHeight(28)
        self.search_input.returnPressed.connect(self._apply_search)
        search_filter_layout.addWidget(self.search_input)

        btn_search = QPushButton("Search")
        btn_search.setMaximumWidth(70)
        btn_search.setFixedHeight(28)
        btn_search.clicked.connect(self._apply_search)
        search_filter_layout.addWidget(btn_search)

        btn_reset = QPushButton("Reset")
        btn_reset.setMaximumWidth(70)
        btn_reset.setFixedHeight(28)
        btn_reset.clicked.connect(self._reset_search)
        search_filter_layout.addWidget(btn_reset)

        # Separator
        search_filter_layout.addWidget(QLabel("|"))

        # Filters
        search_filter_layout.addWidget(QLabel("Min Score:"))
        self.filter_min_score = QSpinBox()
        self.filter_min_score.setRange(0, 100)
        self.filter_min_score.setValue(0)
        self.filter_min_score.setMaximumWidth(60)
        self.filter_min_score.setFixedHeight(28)
        self.filter_min_score.valueChanged.connect(self._apply_search)
        search_filter_layout.addWidget(self.filter_min_score)

        search_filter_layout.addWidget(QLabel("Min Leads:"))
        self.filter_min_leads = QSpinBox()
        self.filter_min_leads.setRange(0, 1000)
        self.filter_min_leads.setValue(0)
        self.filter_min_leads.setMaximumWidth(60)
        self.filter_min_leads.setFixedHeight(28)
        self.filter_min_leads.valueChanged.connect(self._apply_search)
        search_filter_layout.addWidget(self.filter_min_leads)

        search_filter_layout.addWidget(QLabel("|"))

        # Status filters
        self.filter_starred = QCheckBox("Starred")
        self.filter_starred.setFixedHeight(28)
        self.filter_starred.stateChanged.connect(self._apply_search)
        search_filter_layout.addWidget(self.filter_starred)

        self.filter_contacted = QCheckBox("Contacted")
        self.filter_contacted.setFixedHeight(28)
        self.filter_contacted.stateChanged.connect(self._apply_search)
        search_filter_layout.addWidget(self.filter_contacted)

        search_filter_layout.addStretch()

        self.count_label = QLabel("0 clients")
        self.count_label.setStyleSheet("color: #6c7086; font-weight: bold;")
        self.count_label.setMaximumWidth(100)
        search_filter_layout.addWidget(self.count_label)

        search_bar_container = QWidget()
        search_bar_container.setLayout(search_filter_layout)
        search_bar_container.setMaximumHeight(40)
        layout.addWidget(search_bar_container)

        # Splitter: table (left) + detail panel (right)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Table widget (left side)
        table_widget = QWidget()
        table_layout = QVBoxLayout(table_widget)
        table_layout.setContentsMargins(0, 0, 0, 0)

        self.model = ClientsTableModel(self._db)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 200)  # name
        self.table.setColumnWidth(1, 150)  # domain
        self.table.setColumnWidth(2, 130)  # type
        self.table.setColumnWidth(3, 55)   # starred
        self.table.setColumnWidth(4, 70)   # contacted
        self.table.setColumnWidth(5, 180)  # contact
        self.table.setColumnWidth(6, 60)   # score
        self.table.setColumnWidth(7, 55)   # leads
        self.table.setColumnWidth(8, 90)   # created
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.selectionModel().currentRowChanged.connect(self._on_row_changed)
        self.table.doubleClicked.connect(self._on_table_double_click)
        table_layout.addWidget(self.table)

        # Actions row
        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 4, 0, 0)
        actions_row.setSpacing(4)

        self.btn_reanalyze = QPushButton("Re-run Client Analysis")
        self.btn_reanalyze.setFixedHeight(28)
        self.btn_reanalyze.setStyleSheet(
            "background: #89b4fa; color: white; border: none; "
            "padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;"
        )
        self.btn_reanalyze.clicked.connect(self._reanalyze_selected)
        actions_row.addWidget(self.btn_reanalyze)

        btn_add_client = QPushButton("+ Add Client")
        btn_add_client.setFixedHeight(28)
        btn_add_client.setStyleSheet(
            "background: #a6e3a1; color: #1e1e2e; border: none; "
            "padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;"
        )
        btn_add_client.clicked.connect(self._add_client_manually)
        actions_row.addWidget(btn_add_client)

        btn_edit_client = QPushButton("✎ Edit Client")
        btn_edit_client.setFixedHeight(28)
        btn_edit_client.setStyleSheet(
            "background: #cba6f7; color: white; border: none; "
            "padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;"
        )
        btn_edit_client.clicked.connect(self._edit_client_info)
        actions_row.addWidget(btn_edit_client)

        self.btn_toggle_star = QPushButton("★ Star")
        self.btn_toggle_star.setFixedHeight(28)
        self.btn_toggle_star.setStyleSheet(
            "background: #fab387; color: white; border: none; "
            "padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;"
        )
        self.btn_toggle_star.clicked.connect(self._toggle_starred)
        actions_row.addWidget(self.btn_toggle_star)

        self.btn_toggle_contacted = QPushButton("☑ Mark Contacted")
        self.btn_toggle_contacted.setFixedHeight(28)
        self.btn_toggle_contacted.setStyleSheet(
            "background: #a6e3a1; color: #1e1e2e; border: none; "
            "padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;"
        )
        self.btn_toggle_contacted.clicked.connect(self._toggle_contacted)
        actions_row.addWidget(self.btn_toggle_contacted)

        self.btn_change_color = QPushButton("🎨 Change Color")
        self.btn_change_color.setFixedHeight(28)
        self.btn_change_color.setStyleSheet(
            "background: #f5c2e6; color: #1e1e2e; border: none; "
            "padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;"
        )
        self.btn_change_color.clicked.connect(self._change_client_color)
        actions_row.addWidget(self.btn_change_color)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #6c7086; font-size: 10px;")
        actions_row.addWidget(self.status_label)

        actions_row.addStretch()
        btn_delete = QPushButton("Delete Selected")
        btn_delete.setFixedHeight(28)
        btn_delete.setStyleSheet(
            "background: #f38ba8; color: white; border: none; "
            "padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;"
        )
        btn_delete.clicked.connect(self._bulk_delete)
        actions_row.addWidget(btn_delete)
        table_layout.addLayout(actions_row)

        splitter.addWidget(table_widget)

        # Detail panel (right side)
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        detail_scroll.setMinimumWidth(340)
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(8, 0, 0, 0)
        detail_layout.setSpacing(4)

        self.detail_name = QLabel("Select a client")
        self.detail_name.setWordWrap(True)
        self.detail_name.setStyleSheet("font-size: 15px; font-weight: bold; margin-bottom: 2px;")
        detail_layout.addWidget(self.detail_name)

        self.detail_domain = QLabel()
        self.detail_domain.setWordWrap(True)
        self.detail_domain.setStyleSheet("color: #6c7086; margin-bottom: 8px; font-size: 11px;")
        detail_layout.addWidget(self.detail_domain)

        # Info group
        info_group = QGroupBox("Client Information")
        info_layout = QVBoxLayout(info_group)
        info_layout.setSpacing(2)
        info_layout.setContentsMargins(4, 4, 4, 4)

        # Revenue Scale
        info_layout.addWidget(QLabel("Revenue Scale:"))
        self.detail_revenue_scale = QTextEdit()
        self.detail_revenue_scale.setReadOnly(True)
        self.detail_revenue_scale.setMaximumHeight(50)
        info_layout.addWidget(self.detail_revenue_scale)

        # Introduction
        info_layout.addWidget(QLabel("Introduction:"))
        self.detail_introduction = QTextEdit()
        self.detail_introduction.setReadOnly(True)
        self.detail_introduction.setMaximumHeight(160)
        info_layout.addWidget(self.detail_introduction)

        # Reason
        info_layout.addWidget(QLabel("Analysis Reason:"))
        self.detail_reason = QTextEdit()
        self.detail_reason.setReadOnly(True)
        self.detail_reason.setMaximumHeight(160)
        info_layout.addWidget(self.detail_reason)

        detail_layout.addWidget(info_group)

        # Stats group
        stats_group = QGroupBox("Statistics")
        stats_form = QFormLayout(stats_group)

        self.detail_score_label = QLabel("–")
        stats_form.addRow("Score:", self.detail_score_label)

        self.detail_tag_label = QLabel("–")
        stats_form.addRow("Type:", self.detail_tag_label)

        self.detail_leads_label = QLabel("–")
        stats_form.addRow("Associated Leads:", self.detail_leads_label)

        self.detail_contact_label = QLabel("–")
        self.detail_contact_label.setWordWrap(True)
        stats_form.addRow("Contact:", self.detail_contact_label)

        self.detail_updated_label = QLabel("–")
        stats_form.addRow("Last Updated:", self.detail_updated_label)

        detail_layout.addWidget(stats_group)

        # Notes group
        notes_group = QGroupBox("Notes")
        notes_layout = QVBoxLayout(notes_group)
        notes_layout.setSpacing(4)
        notes_layout.setContentsMargins(4, 4, 4, 4)

        self.detail_notes = QPlainTextEdit()
        self.detail_notes.setPlaceholderText("Add notes about this client…")
        self.detail_notes.setMinimumHeight(100)
        self.detail_notes.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        notes_layout.addWidget(self.detail_notes)

        self.btn_save_notes = QPushButton("Save Notes")
        self.btn_save_notes.clicked.connect(self._save_client_notes)
        notes_layout.addWidget(self.btn_save_notes)

        detail_layout.addWidget(notes_group)

        detail_layout.addStretch()
        detail_scroll.setWidget(detail_widget)

        splitter.addWidget(detail_scroll)
        splitter.setSizes([600, 350])

        layout.addWidget(splitter)
        return page

    def _build_analysis_settings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)

        hint = QLabel(
            "Edit the prompt template used for client analysis. "
            "Available placeholders: {name}, {domain}"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #6c7086; margin-bottom: 8px;")
        layout.addWidget(hint)

        self.prompt_editor = QPlainTextEdit()
        self.prompt_editor.setMinimumHeight(200)
        self.prompt_editor.setPlaceholderText("Enter client analysis prompt template…")
        layout.addWidget(self.prompt_editor)

        # Load current prompt
        from ...pipeline.stages.client_analysis import DEFAULT_CLIENT_ANALYSIS_PROMPT
        saved = self._db.get_setting("client_analysis_prompt", "")
        self.prompt_editor.setPlainText(saved or DEFAULT_CLIENT_ANALYSIS_PROMPT)

        # Save / Reset buttons
        btn_row = QHBoxLayout()
        btn_save = QPushButton("Save Prompt")
        btn_save.setStyleSheet(
            "background: #a6e3a1; color: #1e1e2e; border: none; "
            "padding: 6px 12px; border-radius: 4px; font-weight: bold;"
        )
        btn_save.clicked.connect(self._save_prompt)
        btn_row.addWidget(btn_save)

        btn_reset_prompt = QPushButton("Reset to Default")
        btn_reset_prompt.clicked.connect(self._reset_prompt)
        btn_row.addWidget(btn_reset_prompt)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addStretch()
        return page

    def _apply_search(self):
        s = self.search_input.text().strip() or None
        min_score = self.filter_min_score.value()
        min_leads = self.filter_min_leads.value()
        starred = self.filter_starred.isChecked() or None  
        contacted = self.filter_contacted.isChecked() or None
        self.model.refresh(search=s, min_score=min_score, min_leads=min_leads, starred=starred, contacted=contacted)
        self._update_count()
        self._clear_detail_panel()

    def _reset_search(self):
        self.search_input.clear()
        self.filter_min_score.setValue(0)
        self.filter_min_leads.setValue(0)
        self.filter_starred.setChecked(False)
        self.filter_contacted.setChecked(False)
        self.model.refresh()
        self._update_count()
        self._clear_detail_panel()

    def _update_count(self):
        """Update count label (shows filtered count from model)."""
        count = self.model.rowCount()
        self.count_label.setText(f"{count} client{'s' if count != 1 else ''}")

    def refresh(self):
        s = self.search_input.text().strip() or None
        min_score = self.filter_min_score.value()
        min_leads = self.filter_min_leads.value()
        starred = self.filter_starred.isChecked() or None
        contacted = self.filter_contacted.isChecked() or None
        self.model.refresh(search=s, min_score=min_score, min_leads=min_leads, starred=starred, contacted=contacted)
        self._update_count()
        self._clear_detail_panel()

    def _on_row_changed(self, current: QModelIndex, previous: QModelIndex):
        """Handle client row selection – load details into right panel."""
        if not current.isValid():
            self._clear_detail_panel()
            return
        
        client = self.model.get_client_at(current.row())
        if client:
            self._load_client_details(client)
        else:
            self._clear_detail_panel()

    def _load_client_details(self, client: Client):
        """Load client details into the right panel."""
        self._current_client = client
        
        self.detail_name.setText(client.name or "–")
        self.detail_domain.setText(client.domain or "–")
        
        self.detail_revenue_scale.setPlainText(client.revenue_scale or "")
        self.detail_introduction.setPlainText(client.introduction or "")
        self.detail_reason.setPlainText(client.client_reason or "")
        self.detail_notes.setPlainText(client.notes or "")
        
        self.detail_score_label.setText(str(client.client_score) if client.client_score else "–")
        self.detail_tag_label.setText(client.tag or "–")
        self.detail_leads_label.setText(str(client.lead_count))
        self.detail_contact_label.setText(client.contact or "–")
        self.detail_updated_label.setText(str(client.updated_at)[:19] if client.updated_at else "–")

    def _clear_detail_panel(self):
        """Clear all detail panel fields."""
        self._current_client = None
        self.detail_name.setText("Select a client")
        self.detail_domain.setText("")
        self.detail_revenue_scale.clear()
        self.detail_introduction.clear()
        self.detail_reason.clear()
        self.detail_notes.clear()
        self.detail_score_label.setText("–")
        self.detail_tag_label.setText("–")
        self.detail_leads_label.setText("–")
        self.detail_contact_label.setText("–")
        self.detail_updated_label.setText("–")

    def _save_prompt(self):
        """Save the edited client analysis prompt."""
        text = self.prompt_editor.toPlainText().strip()
        self._db.set_setting("client_analysis_prompt", text)
        QMessageBox.information(self, "Saved", "Client analysis prompt saved.")

    def _reset_prompt(self):
        """Reset prompt to default."""
        from ...pipeline.stages.client_analysis import DEFAULT_CLIENT_ANALYSIS_PROMPT
        self.prompt_editor.setPlainText(DEFAULT_CLIENT_ANALYSIS_PROMPT)
        self._db.set_setting("client_analysis_prompt", "")

    def _save_client_notes(self):
        """Save manual notes for the currently selected client."""
        if not self._current_client:
            return
        notes = self.detail_notes.toPlainText()
        self._db.update_client_notes(self._current_client.client_id, notes)
        self._current_client = self._db.get_client(self._current_client.client_id)
        QMessageBox.information(self, "Saved", "Notes saved successfully.")

    def _add_client_manually(self):
        """Open dialog to manually create a new client."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Add Client")
        dlg.setMinimumWidth(420)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        name_edit = QLineEdit()
        name_edit.setPlaceholderText("Client / company name")
        form.addRow("Name *:", name_edit)

        domain_edit = QLineEdit()
        domain_edit.setPlaceholderText("e.g. example.com")
        form.addRow("Domain:", domain_edit)

        contact_edit = QLineEdit()
        contact_edit.setPlaceholderText("e.g. email or phone")
        form.addRow("Contact:", contact_edit)

        tag_edit = QLineEdit()
        tag_edit.setPlaceholderText("e.g. Game Studio, Agency, 3D Animation Studio")
        form.addRow("Type:", tag_edit)

        notes_edit = QPlainTextEdit()
        notes_edit.setPlaceholderText("Add notes about this client…")
        notes_edit.setFixedHeight(100)
        form.addRow("Notes:", notes_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        name = name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Required", "Name is required.")
            return

        domain = domain_edit.text().strip()
        contact = contact_edit.text().strip()
        notes = notes_edit.toPlainText().strip()

        client = self._db.insert_client_manual(name, domain, notes, contact=contact, tag=tag_edit.text().strip())
        if client:
            self.model.refresh()
            self._update_count()
            QMessageBox.information(self, "Added", f"Client '{name}' added successfully.")
        else:
            QMessageBox.warning(self, "Duplicate", "A client with this name and domain already exists.")

    def _edit_client_info(self):
        """Open dialog to edit name, domain and contact of the selected client."""
        if not self._current_client:
            QMessageBox.information(self, "No Selection", "Select a client first.")
            return
        client = self._current_client

        dlg = QDialog(self)
        dlg.setWindowTitle("Edit Client")
        dlg.setMinimumWidth(420)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        name_edit = QLineEdit(client.name or "")
        form.addRow("Name *:", name_edit)

        domain_edit = QLineEdit(client.domain or "")
        form.addRow("Domain:", domain_edit)

        contact_edit = QLineEdit(client.contact or "")
        contact_edit.setPlaceholderText("e.g. email or phone")
        form.addRow("Contact:", contact_edit)

        tag_edit = QLineEdit(client.tag or "")
        tag_edit.setPlaceholderText("e.g. Game Studio, Agency, 3D Animation Studio")
        form.addRow("Type:", tag_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        name = name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Required", "Name is required.")
            return

        self._db.update_client_info(
            client.client_id,
            name,
            domain_edit.text().strip(),
            contact_edit.text().strip(),
            tag=tag_edit.text().strip(),
        )
        self._current_client = self._db.get_client(client.client_id)
        self.model.refresh()
        self._load_client_details(self._current_client)

    def _reanalyze_selected(self):
        """Re-run client analysis for selected clients (or all if none selected)."""
        indexes = self.table.selectionModel().selectedRows()
        clients = []
        if indexes:
            for idx in indexes:
                c = self.model.get_client_at(idx.row())
                if c:
                    clients.append(c)
        else:
            # If no selection, use current client
            if self._current_client:
                clients = [self._current_client]
            else:
                # Otherwise analyze all
                clients = self._db.get_clients(search=None)

        if not clients:
            QMessageBox.information(self, "No Clients", "No clients to analyze.")
            return

        answer = QMessageBox.question(
            self, "Client Analysis",
            f"Run analysis on {len(clients)} client(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.btn_reanalyze.setEnabled(False)
        self.status_label.setText("Analyzing…")
        self._worker = ClientAnalysisWorker(self._db, clients, self)
        self._worker.progress.connect(lambda msg, _: self.status_label.setText(msg))
        self._worker.finished.connect(self._on_analysis_done)
        self._worker.start()

    def _on_analysis_done(self, count: int, errors: list):
        self.btn_reanalyze.setEnabled(True)
        self.refresh()
        if self._current_client:
            # Reload current client details
            updated = self._db.get_client(self._current_client.client_id)
            if updated:
                self._load_client_details(updated)
        msg = f"Analyzed {count} client(s)"
        if errors:
            msg += f" ({len(errors)} errors)"
        self.status_label.setText(msg)

    def _toggle_starred(self):
        """Toggle starred status for selected clients."""
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            QMessageBox.information(self, "No Selection", "Select client(s) to star.")
            return
        
        count = 0
        for idx in indexes:
            c = self.model.get_client_at(idx.row())
            if c:
                new_starred = not c.starred
                self._db.toggle_client_starred(c.client_id, new_starred)
                count += 1
        
        if count > 0:
            self.refresh()
            action = "starred" if new_starred else "unstarred"
            self.status_label.setText(f"{count} client(s) {action}")

    def _toggle_contacted(self):
        """Toggle contacted status for selected clients."""
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            QMessageBox.information(self, "No Selection", "Select client(s) to mark.")
            return
        
        count = 0
        for idx in indexes:
            c = self.model.get_client_at(idx.row())
            if c:
                new_contacted = not c.contacted
                self._db.toggle_client_contacted(c.client_id, new_contacted)
                count += 1
        
        if count > 0:
            self.refresh()
            action = "marked as contacted" if new_contacted else "unmarked as contacted"
            self.status_label.setText(f"{count} client(s) {action}")

    def _bulk_delete(self):
        """Delete selected clients."""
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            QMessageBox.information(self, "No Selection", "Select client(s) to delete.")
            return
        
        ids = []
        names = []
        for idx in indexes:
            c = self.model.get_client_at(idx.row())
            if c:
                ids.append(c.client_id)
                names.append(c.name)
        
        if not ids:
            return
        
        msg = f"Permanently delete {len(ids)} client(s)?\n\n" + "\n".join(names[:5])
        if len(names) > 5:
            msg += f"\n... and {len(names) - 5} more"
        
        answer = QMessageBox.question(
            self, "Delete Clients",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        
        self._db.bulk_delete_clients(ids)
        self.model.refresh()
        self._update_count()
        self._clear_detail_panel()

    def _show_context_menu(self, pos: QPoint):
        """Show context menu on right-click with copy options."""
        if not self._current_client:
            return
        
        menu = QMenu(self)
        
        domain_action = menu.addAction(f"Copy Domain: {self._current_client.domain}")
        domain_action.triggered.connect(
            lambda: self._copy_to_clipboard(self._current_client.domain)
        )
        
        if self._current_client.contact:
            contact_action = menu.addAction(f"Copy Contact: {self._current_client.contact}")
            contact_action.triggered.connect(
                lambda: self._copy_to_clipboard(self._current_client.contact)
            )
        
        menu.exec(self.table.mapToGlobal(pos))

    def _on_table_double_click(self, index: QModelIndex):
        """Handle double-click on table cell."""
        if not index.isValid():
            return

        client = self.model.get_client_at(index.row())
        if not client:
            return

        col_key = CLIENT_COLUMNS[index.column()][0]

        # Double-click on Leads column → navigate to Leads tab filtered by client name
        if col_key == "lead_count":
            if client.name:
                self.navigate_to_leads.emit(client.name)
            return

        # Double-click on Domain column → open in browser
        if col_key != "domain":
            return

        if not client.domain:
            return
        
        domain = client.domain.strip()
        if not domain:
            return
        
        # Add protocol if missing
        if not domain.startswith(('http://', 'https://', 'ftp://')):
            url = f"https://{domain}"
        else:
            url = domain
        
        # Open in default browser
        try:
            webbrowser.open(url)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open domain:\\n{e}")

    def _copy_to_clipboard(self, text: str):
        """Copy text to clipboard."""
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        self.status_label.setText(f"✓ Copied: {text[:50]}{'...' if len(text) > 50 else ''}")

    def _change_client_color(self):
        """Show color picker dialog to change colors of selected clients."""
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            QMessageBox.information(self, "No Selection", "Select client(s) to change color.")
            return
        
        # Color palette with 12 colors
        colors = [
            ("#FFB4B4", "Light Red"),
            ("#FFD9B4", "Light Orange"),
            ("#FFFFB4", "Light Yellow"),
            ("#B4FFB4", "Light Green"),
            ("#B4FFFF", "Light Cyan"),
            ("#B4D9FF", "Light Blue"),
            ("#D9B4FF", "Light Purple"),
            ("#FFB4E8", "Light Pink"),
            ("#FF9999", "Medium Red"),
            ("#99CCFF", "Medium Blue"),
            ("#99FF99", "Medium Green"),
            ("#FFCC99", "Medium Orange"),
        ]
        
        dlg = QDialog(self)
        dlg.setWindowTitle("Select Color")
        dlg.setMinimumWidth(400)
        layout = QVBoxLayout(dlg)
        
        # Color buttons grid
        color_group = QGroupBox("Choose a color:")
        color_layout = QHBoxLayout(color_group)
        color_layout.setSpacing(4)
        color_layout.setContentsMargins(4, 4, 4, 4)
        
        selected_color = None
        
        def make_color_button(color_hex, color_name):
            nonlocal selected_color
            btn = QPushButton()
            btn.setFixedSize(60, 60)
            btn.setStyleSheet(f"background-color: {color_hex}; border: 2px solid #ccc; border-radius: 4px;")
            btn.setToolTip(color_name)
            def on_click():
                nonlocal selected_color
                selected_color = color_hex
                dlg.accept()
            btn.clicked.connect(on_click)
            return btn
        
        for color_hex, color_name in colors:
            color_layout.addWidget(make_color_button(color_hex, color_name))
        
        layout.addWidget(color_group)
        
        # Clear color option
        btn_clear = QPushButton("Clear Color")
        btn_clear.setStyleSheet(
            "background: #f5f5f5; color: #1e1e2e; border: 1px solid #ccc; "
            "padding: 6px 12px; border-radius: 4px; font-weight: bold;"
        )
        def on_clear():
            nonlocal selected_color
            selected_color = ""
            dlg.accept()
        btn_clear.clicked.connect(on_clear)
        layout.addWidget(btn_clear)
        
        # Cancel button
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(dlg.reject)
        layout.addWidget(btn_cancel)
        
        if dlg.exec() != QDialog.DialogCode.Accepted or selected_color is None:
            return
        
        # Get selected client IDs
        client_ids = []
        for idx in indexes:
            c = self.model.get_client_at(idx.row())
            if c:
                client_ids.append(c.client_id)
        
        if client_ids:
            self._db.bulk_update_client_colors(client_ids, selected_color)
            self.model.refresh()
            self._update_count()
            self.status_label.setText(f"{len(client_ids)} client(s) color changed")

