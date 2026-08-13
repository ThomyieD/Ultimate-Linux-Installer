from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from uli.i18n import tr


class NoticeDialog(QDialog):
    """Styled modal notice — replaces stock QMessageBox look."""

    def __init__(self, parent, *, title: str, body: str) -> None:
        super().__init__(parent)
        self.setObjectName("NoticeDialog")
        self.setWindowTitle(tr("app.title"))
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 24)
        root.setSpacing(12)

        t = QLabel(title)
        t.setObjectName("NoticeTitle")
        t.setWordWrap(True)
        b = QLabel(body)
        b.setObjectName("NoticeBody")
        b.setWordWrap(True)
        root.addWidget(t)
        root.addWidget(b)
        root.addSpacing(8)

        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton(tr("dialog.ok"))
        ok.setObjectName("Primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        root.addLayout(row)


def show_notice(parent, *, title: str, body: str) -> None:
    NoticeDialog(parent, title=title, body=body).exec()
