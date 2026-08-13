from __future__ import annotations

import time

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from uli.i18n import tr
from uli.network.connectivity import (
    check_internet,
    connect_wifi,
    ethernet_carrier,
    has_wifi_radio,
    list_wifi_networks,
)
from uli.ui.pages.base import BasePage


class _CheckWorker(QThread):
    result = Signal(bool)

    def __init__(self, *, min_seconds: float = 1.4) -> None:
        super().__init__()
        self.min_seconds = min_seconds

    def run(self) -> None:
        started = time.monotonic()
        ok = check_internet()
        elapsed = time.monotonic() - started
        remain = self.min_seconds - elapsed
        if remain > 0:
            time.sleep(remain)
        self.result.emit(ok)


class _ScanWorker(QThread):
    result = Signal(list)

    def run(self) -> None:
        self.result.emit(list_wifi_networks(rescan=True))


class _ConnectWorker(QThread):
    result = Signal(bool, str)

    def __init__(self, ssid: str, password: str) -> None:
        super().__init__()
        self.ssid = ssid
        self.password = password

    def run(self) -> None:
        ok, err = connect_wifi(self.ssid, self.password)
        self.result.emit(ok, err)


class NetworkPage(BasePage):
    def __init__(self, wizard) -> None:
        super().__init__(wizard)
        self.set_texts("network.title", "network.lead")

        self.status = QLabel()
        self.status.setObjectName("StatusBusy")
        self.status.setWordWrap(True)
        self.root.addWidget(self.status)

        self.panel = QFrame()
        self.panel.setObjectName("Surface")
        self.panel.setVisible(False)
        panel_lay = QVBoxLayout(self.panel)
        panel_lay.setContentsMargins(22, 20, 22, 20)
        panel_lay.setSpacing(14)

        self.guide = QLabel()
        self.guide.setObjectName("PageSubtitle")
        self.guide.setWordWrap(True)
        panel_lay.addWidget(self.guide)

        self.wifi_section = QWidget()
        wifi_lay = QVBoxLayout(self.wifi_section)
        wifi_lay.setContentsMargins(0, 0, 0, 0)
        wifi_lay.setSpacing(10)

        self.wifi_label = QLabel()
        self.wifi_label.setObjectName("SectionLabel")
        wifi_lay.addWidget(self.wifi_label)

        self.wifi_list = QListWidget()
        self.wifi_list.setMinimumHeight(180)
        self.wifi_list.setMaximumHeight(240)
        self.wifi_list.currentItemChanged.connect(self._on_wifi_selected)
        wifi_lay.addWidget(self.wifi_list)

        self.wifi_pw = QLineEdit()
        self.wifi_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.wifi_pw.setPlaceholderText(tr("network.password"))
        wifi_lay.addWidget(self.wifi_pw)

        self.hidden_toggle = QCheckBox(tr("network.hidden"))
        self.hidden_toggle.toggled.connect(self._on_hidden_toggled)
        wifi_lay.addWidget(self.hidden_toggle)

        self.hidden_ssid = QLineEdit()
        self.hidden_ssid.setPlaceholderText(tr("network.hidden_ssid"))
        self.hidden_ssid.setVisible(False)
        wifi_lay.addWidget(self.hidden_ssid)

        panel_lay.addWidget(self.wifi_section)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.btn_connect = QPushButton(tr("network.connect"))
        self.btn_connect.setObjectName("Primary")
        self.btn_connect.clicked.connect(self._connect_wifi)
        self.btn_scan = QPushButton(tr("network.scan"))
        self.btn_scan.setObjectName("Ghost")
        self.btn_scan.clicked.connect(self._scan_wifi)
        self.btn_retry = QPushButton(tr("network.retry"))
        self.btn_retry.setObjectName("Ghost")
        self.btn_retry.clicked.connect(self._start_check)
        actions.addWidget(self.btn_connect)
        actions.addWidget(self.btn_scan)
        actions.addStretch(1)
        actions.addWidget(self.btn_retry)
        panel_lay.addLayout(actions)

        self.action_status = QLabel()
        self.action_status.setObjectName("StatusBusy")
        self.action_status.setWordWrap(True)
        self.action_status.hide()
        panel_lay.addWidget(self.action_status)

        self.root.addWidget(self.panel)
        self.root.addStretch(1)

        self._check_worker: _CheckWorker | None = None
        self._scan_worker: _ScanWorker | None = None
        self._connect_worker: _ConnectWorker | None = None
        self._busy = False

    def retranslate(self) -> None:
        super().retranslate()
        self.wifi_label.setText(tr("network.wifi").upper())
        self.wifi_pw.setPlaceholderText(tr("network.password"))
        self.hidden_toggle.setText(tr("network.hidden"))
        self.hidden_ssid.setPlaceholderText(tr("network.hidden_ssid"))
        self.btn_connect.setText(tr("network.connect"))
        self.btn_scan.setText(tr("network.scan"))
        self.btn_retry.setText(tr("network.retry"))
        if self.wizard.state.online:
            self._set_status("ok", tr("network.ok"))
            self.guide.setText(tr("network.lead_ok"))
        elif self.panel.isVisible():
            self._refresh_guide()

    def on_enter(self) -> None:
        self._start_check()

    def _set_status(self, kind: str, text: str) -> None:
        names = {
            "ok": "StatusOk",
            "warn": "StatusWarn",
            "busy": "StatusBusy",
            "error": "StatusError",
        }
        self.status.setObjectName(names.get(kind, "StatusBusy"))
        self.status.setText(text)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _set_action_status(self, kind: str, text: str) -> None:
        if not text:
            self.action_status.hide()
            return
        names = {
            "ok": "StatusOk",
            "warn": "StatusWarn",
            "busy": "StatusBusy",
            "error": "StatusError",
        }
        self.action_status.setObjectName(names.get(kind, "StatusBusy"))
        self.action_status.setText(text)
        self.action_status.style().unpolish(self.action_status)
        self.action_status.style().polish(self.action_status)
        self.action_status.show()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        enabled = not busy
        self.btn_connect.setEnabled(enabled)
        self.btn_scan.setEnabled(enabled)
        self.btn_retry.setEnabled(enabled)
        self.wifi_list.setEnabled(enabled)
        self.wifi_pw.setEnabled(enabled)
        self.hidden_toggle.setEnabled(enabled)
        self.hidden_ssid.setEnabled(enabled)

    def _refresh_guide(self) -> None:
        eth = ethernet_carrier()
        wifi = has_wifi_radio()
        lines = [tr("network.guide_intro")]
        if eth is False:
            lines.append(tr("network.guide_lan"))
        elif eth is True:
            lines.append(tr("network.guide_lan_up"))
        else:
            lines.append(tr("network.guide_lan"))
        if wifi:
            lines.append(tr("network.guide_wifi"))
        else:
            lines.append(tr("network.guide_no_wifi"))
        self.guide.setText("\n".join(lines))
        self.wifi_section.setVisible(wifi)

    def _start_check(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self._set_status("busy", tr("network.checking"))
        self._set_action_status("busy", "")
        self.panel.setVisible(False)
        self._check_worker = _CheckWorker(min_seconds=1.5)
        self._check_worker.result.connect(self._on_check_result)
        self._check_worker.start()

    def _on_check_result(self, ok: bool) -> None:
        self.wizard.state.online = ok
        self._set_busy(False)
        if ok:
            self._set_status("ok", tr("network.ok"))
            self.panel.setVisible(False)
            return
        self._set_status("error", tr("network.fail"))
        self.panel.setVisible(True)
        self.wifi_label.setText(tr("network.wifi").upper())
        self._refresh_guide()
        if has_wifi_radio():
            self._scan_wifi()

    def _scan_wifi(self) -> None:
        if not has_wifi_radio():
            return
        if self._busy:
            return
        self._set_busy(True)
        self._set_action_status("busy", tr("network.scanning"))
        self._scan_worker = _ScanWorker()
        self._scan_worker.result.connect(self._on_scan_result)
        self._scan_worker.start()

    def _on_scan_result(self, networks: list) -> None:
        self._set_busy(False)
        current = self._selected_ssid()
        self.wifi_list.clear()
        if not networks:
            self._set_action_status("warn", tr("network.scan_empty"))
            return
        self._set_action_status("busy", "")
        for net in networks:
            label = net.ssid
            if net.signal:
                label = f"{net.ssid}    {net.signal}%"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, net.ssid)
            self.wifi_list.addItem(item)
            if net.ssid == current:
                self.wifi_list.setCurrentItem(item)
        if self.wifi_list.currentItem() is None and self.wifi_list.count():
            self.wifi_list.setCurrentRow(0)

    def _on_wifi_selected(self, current: QListWidgetItem | None, _previous) -> None:
        if current and not self.hidden_toggle.isChecked():
            self.hidden_ssid.clear()

    def _on_hidden_toggled(self, checked: bool) -> None:
        self.hidden_ssid.setVisible(checked)
        self.wifi_list.setEnabled(not checked and not self._busy)
        if checked:
            self.wifi_list.clearSelection()
            self.hidden_ssid.setFocus()

    def _selected_ssid(self) -> str:
        if self.hidden_toggle.isChecked():
            return self.hidden_ssid.text().strip()
        item = self.wifi_list.currentItem()
        if not item:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or "")

    def _connect_wifi(self) -> None:
        ssid = self._selected_ssid()
        if not ssid:
            self._set_action_status("error", tr("network.need_ssid"))
            return
        password = self.wifi_pw.text()
        self._set_busy(True)
        self._set_action_status("busy", tr("network.connecting", ssid=ssid))
        self._connect_worker = _ConnectWorker(ssid, password)
        self._connect_worker.result.connect(self._on_connect_result)
        self._connect_worker.start()

    def _on_connect_result(self, ok: bool, err: str) -> None:
        self._set_busy(False)
        if ok:
            self._set_action_status("ok", tr("network.connect_ok"))
            self._start_check()
            return
        self._set_action_status("error", tr("network.connect_fail"))
        if err and err not in {"empty_ssid", "nmcli_missing"}:
            # Keep UI calm; detail stays in status as secondary line.
            self.action_status.setText(f"{tr('network.connect_fail')}\n{err[:160]}")

    def validate(self) -> tuple[bool, str]:
        if self.wizard.state.online:
            return True, ""
        return False, tr("network.need_online")
