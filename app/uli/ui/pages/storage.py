from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QLabel, QListWidget, QListWidgetItem, QTextEdit

from uli.core.adapters import get_adapter
from uli.core.plan import (
    BootloaderConfig,
    DiskTarget,
    InstallationPlan,
    LocaleConfig,
    UserConfig,
)
from uli.i18n import tr
from uli.security.secrets import hash_password
from uli.storage.disks import get_disks
from uli.storage.layout import equal_root_layout, validate_layout
from uli.ui.pages.base import BasePage


class StoragePage(BasePage):
    def __init__(self, wizard) -> None:
        super().__init__(wizard)
        self.set_texts("storage.title", "storage.warning")
        self.disk = QComboBox()
        self.root.addWidget(QLabel(tr("storage.disk")))
        self.root.addWidget(self.disk)
        self.usb_note = QLabel(tr("storage.usb_excluded"))
        self.usb_note.setObjectName("Subline")
        self.root.addWidget(self.usb_note)
        self.parts = QListWidget()
        self.root.addWidget(self.parts, 1)
        self.summary = QTextEdit()
        self.summary.setReadOnly(True)
        self.root.addWidget(self.summary)
        self.disk.currentIndexChanged.connect(self._rebuild)

    def retranslate(self) -> None:
        super().retranslate()
        self.usb_note.setText(tr("storage.usb_excluded"))

    def on_enter(self) -> None:
        self.disk.clear()
        disks = get_disks(simulate=self.wizard.simulate_disk)
        for d in disks:
            label = f"{d.model or d.path}  ({d.size_gib:.0f} GiB)  [{d.path}]"
            self.disk.addItem(label, d)
        if disks:
            self.disk.setCurrentIndex(0)
        self._rebuild()

    def _rebuild(self) -> None:
        self.parts.clear()
        d = self.disk.currentData()
        if not d:
            return
        mins = {a.info.id: a.info.minimum_root_gib for a in [get_adapter(x.id) for x in self.wizard.state.selected]}
        parts = equal_root_layout(
            d.size_bytes,
            self.wizard.state.selected,
            include_swap=self.wizard.state.include_swap,
            include_data=self.wizard.state.include_data and self.wizard.state.mode == "multiboot",
            minimum_root_gib=mins,
        )
        self.wizard.state.partitions = parts
        self.wizard.state.disk_id = d.id
        self.wizard.state.disk_path = d.path
        self.wizard.state.disk_size_bytes = d.size_bytes
        for p in parts:
            if p.role == "root":
                name = p.label or p.distribution or "root"
                text = tr("storage.root", name=name) + f" — {p.size_mib/1024:.1f} GiB"
            elif p.role == "esp":
                text = f"{tr('storage.esp')} — {p.size_mib} MiB"
            elif p.role == "swap":
                text = f"{tr('storage.swap')} — {p.size_mib/1024:.1f} GiB"
            else:
                text = f"{tr('storage.data')} — {p.size_mib/1024:.1f} GiB"
            self.parts.addItem(QListWidgetItem(text))

        plan = self._build_plan(confirmed=False)
        self.summary.setPlainText(plan.to_yaml())

    def _build_plan(self, *, confirmed: bool) -> InstallationPlan:
        st = self.wizard.state
        return InstallationPlan(
            mode=st.mode or "simple",
            disk=DiskTarget(
                id=st.disk_id or "unknown",
                path=st.disk_path or "",
                size_bytes=st.disk_size_bytes,
                wipe=st.mode in {"simple", "multiboot"},
            ),
            partitions=list(st.partitions),
            distributions=list(st.selected),
            user=UserConfig(
                username=st.username,
                password_hash=hash_password(st.password) if st.password else None,
                ssh_keys=list(st.ssh_keys),
                sudo=True,
            ),
            bootloader=BootloaderConfig(theme=st.theme, timeout_seconds=5),
            locale=LocaleConfig(
                language="de_DE.UTF-8" if st.language == "de" else "en_US.UTF-8",
                timezone=st.timezone,
                keyboard=st.keyboard,
            ),
            confirmed=confirmed,
        )

    def on_leave(self) -> None:
        self._rebuild()

    def validate(self) -> tuple[bool, str]:
        if not self.wizard.state.disk_path:
            return False, tr("error.no_disk")
        errors = validate_layout(self.wizard.state.partitions, self.wizard.state.disk_size_bytes)
        if errors:
            return False, "\n".join(errors)
        return True, ""

    def next_label(self) -> str:
        return tr("nav.install")
