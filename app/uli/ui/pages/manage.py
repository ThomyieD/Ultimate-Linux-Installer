from __future__ import annotations

from PySide6.QtWidgets import QLabel

from uli.i18n import tr
from uli.ui.pages.base import BasePage


class ManagePage(BasePage):
    def __init__(self, wizard) -> None:
        super().__init__(wizard)
        self.set_texts("manage.title", "manage.placeholder")
        note = QLabel(tr("manage.placeholder"))
        note.setObjectName("Subline")
        note.setWordWrap(True)
        self.root.addWidget(note)
        self.root.addStretch(1)
