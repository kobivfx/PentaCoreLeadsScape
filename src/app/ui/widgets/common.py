"""Reusable UI widgets."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSpinBox, QTextEdit, QVBoxLayout, QWidget, QGroupBox, QFormLayout,
    QCheckBox, QDoubleSpinBox, QPlainTextEdit,
)


class SecretLineEdit(QLineEdit):
    """Line edit that masks its contents and provides a toggle."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEchoMode(QLineEdit.EchoMode.Password)
        self._show_action = self.addAction(
            self.style().standardIcon(self.style().StandardPixmap.SP_FileDialogInfoView),
            QLineEdit.ActionPosition.TrailingPosition,
        )
        self._show_action.triggered.connect(self._toggle)
        self._visible = False

    def _toggle(self):
        self._visible = not self._visible
        self.setEchoMode(
            QLineEdit.EchoMode.Normal if self._visible else QLineEdit.EchoMode.Password
        )


class FilterBar(QWidget):
    """Reusable filter bar for tables."""
    filtersChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filtersChanged)
        layout.addWidget(self.search)

    def add_combo(self, label: str, items: list[str]) -> QComboBox:
        lbl = QLabel(label)
        combo = QComboBox()
        combo.addItems([""] + items)
        combo.currentTextChanged.connect(self.filtersChanged)
        self.layout().addWidget(lbl)
        self.layout().addWidget(combo)
        return combo


class JsonEditor(QPlainTextEdit):
    """Plain text editor with basic JSON formatting."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        import json

    def set_json(self, data):
        import json
        try:
            if isinstance(data, str):
                data = json.loads(data)
            self.setPlainText(json.dumps(data, indent=2))
        except Exception:
            self.setPlainText(str(data))

    def get_json(self) -> dict:
        import json
        return json.loads(self.toPlainText())


def confirm_dialog(parent, title: str, message: str) -> bool:
    reply = QMessageBox.question(parent, title, message,
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    return reply == QMessageBox.StandardButton.Yes


def info_dialog(parent, title: str, message: str):
    QMessageBox.information(parent, title, message)


def error_dialog(parent, title: str, message: str):
    QMessageBox.critical(parent, title, message)
