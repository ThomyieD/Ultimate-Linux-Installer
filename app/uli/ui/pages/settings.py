from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from uli.i18n import tr
from uli.security.secrets import fetch_github_keys, fetch_launchpad_keys, fingerprint_ssh_key
from uli.ui.pages.base import BasePage


class SettingsPage(BasePage):
    def __init__(self, wizard) -> None:
        super().__init__(wizard)
        self.set_texts("settings.title")
        form = QFormLayout()
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password2 = QLineEdit()
        self.password2.setEchoMode(QLineEdit.EchoMode.Password)
        self.timezone = QLineEdit("Europe/Berlin")
        self.keyboard = QLineEdit("de")
        self.theme = QComboBox()
        self.theme.addItem(tr("settings.theme.lenovo"), "uli-lenovo")
        self.theme.addItem(tr("settings.theme.uli"), "uli-dark")
        self.equal = QCheckBox(tr("settings.equal_size"))
        self.equal.setChecked(True)
        form.addRow(tr("settings.username"), self.username)
        form.addRow(tr("settings.password"), self.password)
        form.addRow(tr("settings.password_confirm"), self.password2)
        form.addRow(tr("settings.timezone"), self.timezone)
        form.addRow(tr("settings.keyboard"), self.keyboard)
        form.addRow(tr("settings.theme"), self.theme)
        self.root.addLayout(form)
        self.root.addWidget(self.equal)

        ssh_box = QVBoxLayout()
        ssh_label = QLabel(tr("settings.ssh_keys"))
        self.ssh_user = QLineEdit()
        self.ssh_user.setPlaceholderText("Launchpad / GitHub username")
        row = QHBoxLayout()
        self.btn_lp = QPushButton(tr("settings.ssh_launchpad"))
        self.btn_gh = QPushButton(tr("settings.ssh_github"))
        self.btn_lp.clicked.connect(self._load_launchpad)
        self.btn_gh.clicked.connect(self._load_github)
        row.addWidget(self.btn_lp)
        row.addWidget(self.btn_gh)
        self.ssh_keys = QTextEdit()
        self.ssh_keys.setPlaceholderText(tr("settings.ssh_manual"))
        self.ssh_fp = QLabel()
        self.ssh_fp.setObjectName("Subline")
        self.ssh_keys.textChanged.connect(self._update_fp)
        ssh_box.addWidget(ssh_label)
        ssh_box.addWidget(self.ssh_user)
        ssh_box.addLayout(row)
        ssh_box.addWidget(self.ssh_keys)
        ssh_box.addWidget(self.ssh_fp)
        self.root.addLayout(ssh_box)
        self.root.addStretch(1)

    def retranslate(self) -> None:
        super().retranslate()
        self.equal.setText(tr("settings.equal_size"))
        self.btn_lp.setText(tr("settings.ssh_launchpad"))
        self.btn_gh.setText(tr("settings.ssh_github"))
        idx = self.theme.currentIndex()
        self.theme.blockSignals(True)
        self.theme.clear()
        self.theme.addItem(tr("settings.theme.lenovo"), "uli-lenovo")
        self.theme.addItem(tr("settings.theme.uli"), "uli-dark")
        self.theme.setCurrentIndex(max(0, idx))
        self.theme.blockSignals(False)

    def _load_launchpad(self) -> None:
        user = self.ssh_user.text().strip()
        if not user:
            return
        try:
            keys = fetch_launchpad_keys(user)
            self.ssh_keys.setPlainText("\n".join(keys))
        except Exception as exc:  # noqa: BLE001
            self.ssh_fp.setText(str(exc))

    def _load_github(self) -> None:
        user = self.ssh_user.text().strip()
        if not user:
            return
        try:
            keys = fetch_github_keys(user)
            self.ssh_keys.setPlainText("\n".join(keys))
        except Exception as exc:  # noqa: BLE001
            self.ssh_fp.setText(str(exc))

    def _update_fp(self) -> None:
        fps = []
        for line in self.ssh_keys.toPlainText().splitlines():
            if line.strip():
                fps.append(fingerprint_ssh_key(line.strip()))
        self.ssh_fp.setText("\n".join(fps))

    def on_leave(self) -> None:
        st = self.wizard.state
        st.username = self.username.text().strip()
        st.password = self.password.text()
        st.password_confirm = self.password2.text()
        st.timezone = self.timezone.text().strip() or "Europe/Berlin"
        st.keyboard = self.keyboard.text().strip() or "de"
        st.theme = self.theme.currentData()
        st.equal_sizes = self.equal.isChecked()
        st.ssh_keys = [ln.strip() for ln in self.ssh_keys.toPlainText().splitlines() if ln.strip()]

    def validate(self) -> tuple[bool, str]:
        self.on_leave()
        st = self.wizard.state
        if not st.username:
            return False, tr("error.username_required")
        if st.password != st.password_confirm:
            return False, tr("error.password_mismatch")
        return True, ""
