from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem

from uli.core.catalog import catalog_for_mode
from uli.core.plan import DistroSelection
from uli.i18n import tr
from uli.ui.pages.base import BasePage


class DistrosPage(BasePage):
    def __init__(self, wizard) -> None:
        super().__init__(wizard)
        self.set_texts("distros.title", "distros.select_multi")
        self.hint = QLabel()
        self.hint.setObjectName("Subline")
        self.list = QListWidget()
        self.list.itemChanged.connect(self._sync_selection)
        self.root.addWidget(self.hint)
        self.root.addWidget(self.list, 1)

    def retranslate(self) -> None:
        super().retranslate()
        self.on_enter()

    def on_enter(self) -> None:
        mode = self.wizard.state.mode or "simple"
        title = tr("distros.simple") if mode == "simple" else tr("distros.multi")
        self._title.setText(title)
        self.hint.setText(
            tr("distros.select_one") if mode == "simple" else tr("distros.select_multi")
        )
        self.list.clear()
        self.list.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection
            if mode == "simple"
            else QListWidget.SelectionMode.MultiSelection
        )
        family_keys = {
            "debian": "distros.family.debian",
            "redhat": "distros.family.redhat",
            "arch": "distros.family.arch",
            "special": "distros.family.special",
        }
        current_family = None
        for entry in catalog_for_mode(mode if mode != "remove" else "add"):
            if entry.family != current_family:
                current_family = entry.family
                header = QListWidgetItem(f"—— {tr(family_keys.get(entry.family, entry.family))} ——")
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                self.list.addItem(header)
            item = QListWidgetItem(entry.display_name)
            item.setData(
                Qt.ItemDataRole.UserRole,
                DistroSelection(
                    id=entry.id,
                    variant=entry.variant,
                    display_name=entry.display_name,
                ),
            )
            if mode != "simple":
                item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsUserCheckable
                )
                item.setCheckState(Qt.CheckState.Unchecked)
            self.list.addItem(item)

        # restore previous selection
        selected_keys = {(d.id, d.variant) for d in self.wizard.state.selected}
        for i in range(self.list.count()):
            item = self.list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if not data:
                continue
            if (data.id, data.variant) in selected_keys:
                if mode == "simple":
                    item.setSelected(True)
                else:
                    item.setCheckState(Qt.CheckState.Checked)

    def _sync_selection(self) -> None:
        pass

    def _collect(self) -> list[DistroSelection]:
        mode = self.wizard.state.mode or "simple"
        selected: list[DistroSelection] = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if not data:
                continue
            if mode == "simple":
                if item.isSelected():
                    selected.append(data)
            elif item.checkState() == Qt.CheckState.Checked:
                selected.append(data)
        return selected

    def on_leave(self) -> None:
        self.wizard.state.selected = self._collect()

    def validate(self) -> tuple[bool, str]:
        selected = self._collect()
        mode = self.wizard.state.mode or "simple"
        if not selected:
            return False, tr("error.no_distro")
        if mode == "simple" and len(selected) != 1:
            return False, tr("distros.select_one")
        if any(s.id == "proxmox" for s in selected) and mode != "simple":
            return False, tr("distros.proxmox.only_simple")
        self.wizard.state.selected = selected
        return True, ""
