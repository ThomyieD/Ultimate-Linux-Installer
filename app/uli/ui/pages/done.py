from __future__ import annotations

from PySide6.QtWidgets import QLabel

from uli.i18n import tr
from uli.ui.pages.base import BasePage


class DonePage(BasePage):
    def __init__(self, wizard) -> None:
        super().__init__(wizard)
        self.set_texts("done.title", "done.body")
        self.body = QLabel(tr("done.body"))
        self.body.setObjectName("Subline")
        self.body.setWordWrap(True)
        self.root.addWidget(self.body)
        self.root.addStretch(1)

    def retranslate(self) -> None:
        super().retranslate()
        self.body.setText(tr("done.body"))

    def next_label(self) -> str:
        return tr("nav.finish")

    def allow_back(self) -> bool:
        return False

    def validate(self) -> tuple[bool, str]:
        # Closing the app stands in for reboot during desktop dry-run
        self.wizard.close()
        return True, ""
