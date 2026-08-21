from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QProgressBar

from uli.bootloader.grub import render_efi_bootorder_fix, render_grub_cfg
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
from uli.state.machine import InstallState, default_state_path
from uli.storage.executor import StorageGuard
from uli.ui.pages.base import BasePage


class ProgressPage(BasePage):
    def __init__(self, wizard) -> None:
        super().__init__(wizard)
        self.set_texts("progress.title")
        self.status = QLabel()
        self.status.setObjectName("Subline")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.root.addWidget(self.status)
        self.root.addWidget(self.bar)
        self.root.addStretch(1)
        self._steps: list[tuple[str, object]] = []
        self._idx = 0

    def on_enter(self) -> None:
        self._idx = 0
        self.bar.setValue(0)
        plan = self._plan(confirmed=True)
        out = Path.home() / ".cache" / "uli" / plan.plan_id
        out.mkdir(parents=True, exist_ok=True)
        plan.save(out / "plan.yaml")

        # Generate automation artifacts for each distro
        for distro in plan.distributions:
            adapter = get_adapter(distro.id)
            files = adapter.generate_automation(plan, distro)
            dist_dir = out / distro.id / distro.variant
            dist_dir.mkdir(parents=True, exist_ok=True)
            for name, content in files.items():
                (dist_dir / name).write_text(content, encoding="utf-8")
            hooks = adapter.post_install_hooks(plan, distro)
            (dist_dir / "post-hooks.sh").write_text("\n\n".join(hooks), encoding="utf-8")

        (out / "grub.cfg").write_text(render_grub_cfg(plan), encoding="utf-8")
        (out / "reclaim-bootorder.sh").write_text(render_efi_bootorder_fix(), encoding="utf-8")

        guard = StorageGuard(dry_run=True)
        cmds = guard.apply_plan(plan)
        (out / "partition-commands.sh").write_text("\n".join(cmds) + "\n", encoding="utf-8")

        state = InstallState(
            plan_id=plan.plan_id,
            status="installing",
            remaining=[f"{d.id}:{d.variant}" for d in plan.distributions],
        )
        state.save(default_state_path())

        self._artifacts = out
        self._animate()

    def _plan(self, *, confirmed: bool) -> InstallationPlan:
        st = self.wizard.state
        return InstallationPlan(
            mode=st.mode or "simple",
            disk=DiskTarget(
                id=st.disk_id or "unknown",
                path=st.disk_path or "",
                size_bytes=st.disk_size_bytes,
                wipe=True,
            ),
            partitions=list(st.partitions),
            distributions=list(st.selected),
            user=UserConfig(
                username=st.username,
                password_hash=hash_password(st.password) if st.password else None,
                ssh_keys=list(st.ssh_keys),
            ),
            bootloader=BootloaderConfig(theme=st.theme),
            locale=LocaleConfig(
                language="de_DE.UTF-8" if st.language == "de" else "en_US.UTF-8",
                timezone=st.timezone,
                keyboard=st.keyboard,
            ),
            confirmed=confirmed,
        )

    def _animate(self) -> None:
        labels = [
            tr("progress.partitioning"),
            *[tr("progress.installing", name=d.display_name) for d in self.wizard.state.selected],
            tr("progress.bootloader"),
            tr("progress.hooks"),
        ]
        total = max(len(labels), 1)

        def tick(i: int = 0) -> None:
            if i >= total:
                self.bar.setValue(100)
                self.status.setText(str(self._artifacts))
                # auto-advance after short delay
                QTimer.singleShot(600, self.wizard.next)
                return
            self.status.setText(labels[i])
            self.bar.setValue(int((i + 1) / total * 100))
            QTimer.singleShot(450, lambda: tick(i + 1))

        tick(0)

    def allow_back(self) -> bool:
        return False

    def next_label(self) -> str:
        return tr("nav.next")

    def validate(self) -> tuple[bool, str]:
        return True, ""
