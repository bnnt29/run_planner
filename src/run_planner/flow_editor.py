#!/usr/bin/env python3
"""
Ablaufplan-Editor  –  PyQt5
============================
Entry point for the split modules.
"""

import sys
import argparse
from pathlib import Path

here = Path(__file__).resolve().parent
pkg_parent = here.parent
if str(pkg_parent) not in sys.path:
    sys.path.insert(0, str(pkg_parent))

try:
    from run_planner.ui import MainWindow
except ImportError:
    from ui import MainWindow

from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication


def main():
    parser = argparse.ArgumentParser(
        description="Ablaufplan-Editor – Load workflow configurations from JSON files"
    )
    parser.add_argument(
        "json_file",
        nargs="?",
        default=None,
        help="Path to JSON configuration file to load"
    )
    args = parser.parse_args()
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Dunkle Fusion-Palette als Fallback
    pal = QPalette()
    pal.setColor(QPalette.Window,          QColor("#0F172A"))
    pal.setColor(QPalette.WindowText,      QColor("#E2E8F0"))
    pal.setColor(QPalette.Base,            QColor("#1E293B"))
    pal.setColor(QPalette.AlternateBase,   QColor("#273349"))
    pal.setColor(QPalette.Text,            QColor("#E2E8F0"))
    pal.setColor(QPalette.ButtonText,      QColor("#E2E8F0"))
    pal.setColor(QPalette.Button,          QColor("#334155"))
    pal.setColor(QPalette.Highlight,       QColor("#2563EB"))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(pal)

    win = MainWindow(json_path=args.json_file)
    app.aboutToQuit.connect(win.scene.cancel_validation)
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
