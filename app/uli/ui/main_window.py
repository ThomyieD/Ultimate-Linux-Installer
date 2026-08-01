from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from uli.i18n import get_language, set_language, tr
from uli.ui.pages.download import DownloadPage
from uli.ui.pages.done import DonePage
from uli.ui.pages.distros import DistrosPage
from uli.ui.pages.manage import ManagePage
from uli.ui.pages.mode import ModePage
from uli.ui.pages.network import NetworkPage
from uli.ui.pages.progress import ProgressPage
from uli.ui.pages.settings import SettingsPage
from uli.ui.pages.storage import StoragePage
from uli.ui.state import WizardState


class MainWindow(QMainWindow):
    def __init__(self, *, language: str, dry_run: bool, simulate_disk: bool) -> None:
        super().__init__()
        self.dry_run = dry_run
        self.simulate_disk = simulate_disk
        self.state = WizardState(language=language)
        self.setWindowTitle(tr("app.title"))
        self.resize(1100, 720)
        self.setMinimumSize(960, 640)

        root = QWidget()
        root.setObjectName("CentralRoot")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 24, 28, 0)
        layout.setSpacing(18)

        header = QHBoxLayout()
        brand = QLabel("ULI")
        brand.setObjectName("Brand")
        titles = QVBoxLayout()
        self.headline = QLabel(tr("app.title"))
        self.headline.setObjectName("Headline")
        self.subline = QLabel(tr("app.subtitle"))
        self.subline.setObjectName("Subline")
        titles.addWidget(self.headline)
        titles.addWidget(self.subline)
        header.addWidget(brand, 0, Qt.AlignmentFlag.AlignTop)
        header.addSpacing(16)
        header.addLayout(titles, 1)

        self.lang = QComboBox()
        self.lang.addItem(tr("lang.de"), "de")
        self.lang.addItem(tr("lang.en"), "en")
        self.lang.setCurrentIndex(0 if language == "de" else 1)
        self.lang.currentIndexChanged.connect(self._on_language)
        header.addWidget(self.lang, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        body = QHBoxLayout()
        self.stack = QStackedWidget()
        self.badge = QLabel("1")
        self.badge.setObjectName("StepBadge")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.pages = [
            NetworkPage(self),
            ModePage(self),
            ManagePage(self),
            DistrosPage(self),
            DownloadPage(self),
            SettingsPage(self),
            StoragePage(self),
            ProgressPage(self),
            DonePage(self),
        ]
        for page in self.pages:
            self.stack.addWidget(page)

        body.addWidget(self.stack, 1)
        body.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(body, 1)

        footer = QFrame()
        footer.setObjectName("Footer")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(28, 16, 28, 16)
        self.btn_back = QPushButton(tr("nav.back"))
        self.btn_back.setObjectName("Ghost")
        self.btn_next = QPushButton(tr("nav.next"))
        self.btn_next.setObjectName("Primary")
        self.btn_back.clicked.connect(self.back)
        self.btn_next.clicked.connect(self.next)
        fl.addWidget(self.btn_back)
        fl.addStretch(1)
        fl.addWidget(self.btn_next)
        layout.addWidget(footer)

        self._flow: list[int] = [0, 1, 3, 4, 5, 6, 7, 8]
        self._flow_pos = 0
        self._goto_flow(0)

    def _on_language(self) -> None:
        lang = self.lang.currentData()
        set_language(lang)
        self.state.language = lang
        self.retranslate()

    def retranslate(self) -> None:
        self.setWindowTitle(tr("app.title"))
        self.headline.setText(tr("app.title"))
        self.subline.setText(tr("app.subtitle"))
        self.btn_back.setText(tr("nav.back"))
        # refresh lang combo labels without resetting selection
        idx = self.lang.currentIndex()
        self.lang.blockSignals(True)
        self.lang.clear()
        self.lang.addItem(tr("lang.de"), "de")
        self.lang.addItem(tr("lang.en"), "en")
        self.lang.setCurrentIndex(idx)
        self.lang.blockSignals(False)
        for page in self.pages:
            page.retranslate()
        self._update_nav_labels()

    def _update_nav_labels(self) -> None:
        page = self.pages[self.stack.currentIndex()]
        self.btn_next.setText(page.next_label())
        self.btn_back.setEnabled(self._flow_pos > 0 and page.allow_back())

    def _rebuild_flow(self) -> None:
        mode = self.state.mode
        if mode in {"add", "remove"}:
            self._flow = [0, 1, 2, 3, 4, 5, 6, 7, 8]
        else:
            self._flow = [0, 1, 3, 4, 5, 6, 7, 8]

    def _goto_flow(self, pos: int) -> None:
        self._flow_pos = pos
        page_index = self._flow[pos]
        self.stack.setCurrentIndex(page_index)
        self.badge.setText(str(pos + 1))
        page = self.pages[page_index]
        page.on_enter()
        self._update_nav_labels()

    def back(self) -> None:
        if self._flow_pos <= 0:
            return
        self._goto_flow(self._flow_pos - 1)

    def next(self) -> None:
        page = self.pages[self.stack.currentIndex()]
        ok, message = page.validate()
        if not ok:
            QMessageBox.warning(self, tr("app.title"), message)
            return
        page.on_leave()
        if self.stack.currentIndex() == 1:
            self._rebuild_flow()
            # re-find mode page position
            self._flow_pos = self._flow.index(1)
        if self._flow_pos >= len(self._flow) - 1:
            return
        self._goto_flow(self._flow_pos + 1)
