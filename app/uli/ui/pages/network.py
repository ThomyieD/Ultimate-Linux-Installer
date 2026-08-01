from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from uli.i18n import tr
from uli.network.connectivity import check_internet, connect_wifi
from uli.ui.pages.base import BasePage


class _CheckWorker(QThread):
    result = Signal(bool)

    def run(self) -> None:
        self.result.emit(check_internet())


class NetworkPage(BasePage):
    def __init__(self, wizard) -> None:
        super().__init__(wizard)
        self.set_texts("network.checking", "network.hint")
        self.status = QLabel()
        self.status.setObjectName("Subline")
        self.root.addWidget(self.status)

        self.cfg = QVBoxLayout()
        self.ssid = QLineEdit()
        self.ssid.setPlaceholderText(tr("network.ssid"))
        self.wifi_pw = QLineEdit()
        self.wifi_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.wifi_pw.setPlaceholderText(tr("network.password"))
        row = QHBoxLayout()
        self.btn_wifi = QPushButton(tr("network.connect"))
        self.btn_wifi.clicked.connect(self._connect_wifi)
        self.btn_retry = QPushButton(tr("network.retry"))
        self.btn_retry.clicked.connect(self._start_check)
        row.addWidget(self.btn_wifi)
        row.addWidget(self.btn_retry)
        self.cfg.addWidget(self.ssid)
        self.cfg.addWidget(self.wifi_pw)
        self.cfg.addLayout(row)
        self.root.addLayout(self.cfg)
        self.root.addStretch(1)
        self._set_config_visible(False)
        self._worker: _CheckWorker | None = None

    def retranslate(self) -> None:
        super().retranslate()
        self.ssid.setPlaceholderText(tr("network.ssid"))
        self.wifi_pw.setPlaceholderText(tr("network.password"))
        self.btn_wifi.setText(tr("network.connect"))
        self.btn_retry.setText(tr("network.retry"))

    def on_enter(self) -> None:
        self._start_check()

    def _set_config_visible(self, visible: bool) -> None:
        self.ssid.setVisible(visible)
        self.wifi_pw.setVisible(visible)
        self.btn_wifi.setVisible(visible)
        self.btn_retry.setVisible(visible)

    def _start_check(self) -> None:
        self.set_texts("network.checking", "network.hint")
        self.status.setText("")
        self._set_config_visible(False)
        self._worker = _CheckWorker()
        self._worker.result.connect(self._on_result)
        self._worker.start()

    def _on_result(self, ok: bool) -> None:
        self.wizard.state.online = ok
        if ok:
            self.set_texts("network.ok", "network.hint")
            self.status.setText("")
            self._set_config_visible(False)
        else:
            self.set_texts("network.fail", "network.hint")
            self._set_config_visible(True)

    def _connect_wifi(self) -> None:
        ok = connect_wifi(self.ssid.text().strip(), self.wifi_pw.text())
        if ok:
            self._start_check()

    def validate(self) -> tuple[bool, str]:
        # Allow continuing in dry-run/dev even offline so UI can be explored
        if self.wizard.dry_run:
            return True, ""
        return (True, "") if self.wizard.state.online else (False, tr("network.fail"))
