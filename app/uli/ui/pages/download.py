from __future__ import annotations

from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QProgressBar, QVBoxLayout

from uli.core.adapters import get_adapter
from uli.i18n import tr
from uli.ui.pages.base import BasePage


class DownloadPage(BasePage):
    def __init__(self, wizard) -> None:
        super().__init__(wizard)
        self.set_texts("download.title", "download.overview")
        self.list = QListWidget()
        self.bars: dict[str, QProgressBar] = {}
        self.meta = QLabel()
        self.meta.setObjectName("Subline")
        self.meta.setWordWrap(True)
        self.root.addWidget(self.meta)
        self.root.addWidget(self.list, 1)
        self.container = QVBoxLayout()
        self.root.addLayout(self.container)

    def on_enter(self) -> None:
        self.list.clear()
        while self.container.count():
            item = self.container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.bars.clear()
        lines = []
        for distro in self.wizard.state.selected:
            adapter = get_adapter(distro.id)
            release = adapter.resolve_release(distro)
            self.list.addItem(QListWidgetItem(f"{distro.display_name} — {release.get('version', '?')}"))
            bar = QProgressBar()
            bar.setRange(0, 100)
            # In desktop dry-run we simulate readiness
            bar.setValue(100 if self.wizard.dry_run else 0)
            bar.setFormat(f"{distro.display_name}: {tr('download.done' if self.wizard.dry_run else 'download.waiting')}")
            self.container.addWidget(bar)
            self.bars[f"{distro.id}:{distro.variant}"] = bar
            lines.append(f"{distro.display_name}: {release.get('mirror') or release.get('iso_page') or ''}")
        self.meta.setText("\n".join(lines) or tr("download.overview"))

    def validate(self) -> tuple[bool, str]:
        return True, ""
