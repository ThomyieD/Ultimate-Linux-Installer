from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from uli.i18n import tr
from uli.ui.pages.base import BasePage


class _ModeCard(QFrame):
    def __init__(self, mode_id: str, title_key: str, desc_key: str, parent_page: "ModePage") -> None:
        super().__init__()
        self.mode_id = mode_id
        self.parent_page = parent_page
        self.title_key = title_key
        self.desc_key = desc_key
        self.setObjectName("ModeCard")
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        self.title = QLabel(tr(title_key))
        self.title.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.desc = QLabel(tr(desc_key))
        self.desc.setObjectName("Subline")
        self.desc.setWordWrap(True)
        lay.addWidget(self.title)
        lay.addWidget(self.desc)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.parent_page.select(self.mode_id)
        super().mousePressEvent(event)

    def retranslate(self) -> None:
        self.title.setText(tr(self.title_key))
        self.desc.setText(tr(self.desc_key))

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)


class ModePage(BasePage):
    def __init__(self, wizard) -> None:
        super().__init__(wizard)
        self.set_texts("mode.title")
        self.cards = [
            _ModeCard("simple", "mode.simple", "mode.simple.desc", self),
            _ModeCard("multiboot", "mode.multi", "mode.multi.desc", self),
            _ModeCard("add", "mode.add", "mode.add.desc", self),
            _ModeCard("remove", "mode.remove", "mode.remove.desc", self),
        ]
        for card in self.cards:
            self.root.addWidget(card)
        self.root.addStretch(1)
        self.select("simple")

    def retranslate(self) -> None:
        super().retranslate()
        for card in self.cards:
            card.retranslate()

    def select(self, mode_id: str) -> None:
        self.wizard.state.mode = mode_id
        for card in self.cards:
            card.set_selected(card.mode_id == mode_id)

    def validate(self) -> tuple[bool, str]:
        return (True, "") if self.wizard.state.mode else (False, tr("mode.title"))
