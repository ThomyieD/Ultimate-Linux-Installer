from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from uli.i18n import set_language
from uli.ui.main_window import MainWindow


def _load_fonts() -> str:
    fonts_dir = Path(__file__).resolve().parent / "fonts"
    for path in sorted(fonts_dir.glob("*.ttf")) + sorted(fonts_dir.glob("*.otf")):
        QFontDatabase.addApplicationFont(str(path))

    preferred = [
        "Plus Jakarta Sans",
        "SF Pro Text",
        "SF Pro Display",
        "Helvetica Neue",
        "Noto Sans",
        "DejaVu Sans",
    ]
    available = set(QFontDatabase.families())
    for name in preferred:
        if name in available:
            return name
    return QApplication.font().family()


def load_stylesheet() -> str:
    path = Path(__file__).resolve().parent / "styles" / "dark.qss"
    return path.read_text(encoding="utf-8")


def run_ui(*, language: str = "de", dry_run: bool = True, simulate_disk: bool = True) -> int:
    import os

    if simulate_disk:
        os.environ["ULI_SIMULATE_DISK"] = "1"
    if dry_run:
        os.environ["ULI_DRY_RUN"] = "1"

    set_language(language)
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("Ultimate Linux Installer")
    app.setStyle("Fusion")
    family = _load_fonts()
    font = QFont(family, 12)
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(font)
    app.setStyleSheet(load_stylesheet())

    window = MainWindow(language=language, dry_run=dry_run, simulate_disk=simulate_disk)
    window.show()
    return app.exec()
