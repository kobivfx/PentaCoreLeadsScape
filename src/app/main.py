"""LeadsScraper2 – UI entry point."""
import sys
from pathlib import Path

# Ensure src is on path
src = str(Path(__file__).resolve().parents[1])
if src not in sys.path:
    sys.path.insert(0, src)

from app.core.logging_config import setup_logging


def main():
    setup_logging()

    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt

    app = QApplication(sys.argv)
    app.setApplicationName("LeadsScraper 2")
    app.setStyle("Fusion")

    # Apply global stylesheet
    app.setStyleSheet("""
        QWidget { font-family: "Segoe UI", Arial, sans-serif; }
        QTableWidget, QTableView {
            gridline-color: #e0e0e0;
            selection-background-color: #89b4fa;
            selection-color: white;
        }
        QGroupBox {
            font-weight: bold;
            border: 1px solid #e0e0e0;
            border-radius: 6px;
            margin-top: 12px;
            padding-top: 16px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 6px;
        }
        QPushButton {
            padding: 6px 14px;
            border-radius: 4px;
            border: 1px solid #ccc;
            background: #f5f5f5;
        }
        QPushButton:hover {
            background: #e8e8e8;
        }
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
            padding: 5px;
            border: 1px solid #ccc;
            border-radius: 4px;
        }
    """)

    from app.ui.main_window import MainWindow
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
