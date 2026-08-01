from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from uli.i18n import tr


class BasePage(QWidget):
    def __init__(self, wizard) -> None:
        super().__init__()
        self.wizard = wizard
        self._title = QLabel()
        self._title.setObjectName("Headline")
        self._sub = QLabel()
        self._sub.setObjectName("Subline")
        self._sub.setWordWrap(True)
        self.root = QVBoxLayout(self)
        self.root.setSpacing(16)
        self.root.addWidget(self._title)
        self.root.addWidget(self._sub)

    def set_texts(self, title_key: str, sub_key: str | None = None) -> None:
        self._title_key = title_key
        self._sub_key = sub_key
        self._title.setText(tr(title_key))
        self._sub.setText(tr(sub_key) if sub_key else "")
        self._sub.setVisible(bool(sub_key))

    def retranslate(self) -> None:
        if hasattr(self, "_title_key"):
            self._title.setText(tr(self._title_key))
        if hasattr(self, "_sub_key") and self._sub_key:
            self._sub.setText(tr(self._sub_key))

    def on_enter(self) -> None:
        return None

    def on_leave(self) -> None:
        return None

    def validate(self) -> tuple[bool, str]:
        return True, ""

    def next_label(self) -> str:
        return tr("nav.next")

    def allow_back(self) -> bool:
        return True
