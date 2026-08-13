import json
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from uli.core.adapters import get_adapter
from uli.core.catalog import catalog_for_mode
from uli.core.plan import DistroSelection
from uli.i18n import set_language
from uli.network.connectivity import (
    check_internet,
    connect_wifi,
    ethernet_carrier,
    has_wifi_radio,
    list_wifi_networks,
    prepare_and_check,
)
from uli.storage.disks import get_disks
from uli.storage.layout import equal_root_layout
from uli.install.job import get_job, start_install
import os
import subprocess

STATIC_DIR = Path(__file__).resolve().parent / "static"


class LangBody(BaseModel):
    language: str


class WifiConnectBody(BaseModel):
    ssid: str = Field(min_length=1)
    password: str = ""


class StatePatch(BaseModel):
    mode: Optional[str] = None
    selected: Optional[list[dict[str, str]]] = None
    username: Optional[str] = None
    password: Optional[str] = None
    theme: Optional[str] = None
    disk_id: Optional[str] = None
    disk_path: Optional[str] = None
    disk_size_bytes: Optional[int] = None
    include_swap: Optional[bool] = None
    include_data: Optional[bool] = None
    timezone: Optional[str] = None
    keyboard: Optional[str] = None
    language: Optional[str] = None


def create_app(*, dry_run: bool = False, simulate_disk: bool = False) -> FastAPI:
    app = FastAPI(title="Ultimate Linux Installer", version="0.2.6")
    app.state.dry_run = dry_run
    app.state.simulate_disk = simulate_disk
    app.state.wizard = {
        "language": "de",
        "mode": "simple",
        "online": False,
        "selected": [],
        "username": "",
        "theme": "uli-lenovo",
        "disk_id": "",
        "disk_path": "",
        "disk_size_bytes": 0,
        "include_swap": True,
        "include_data": True,
    }

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "dry_run": app.state.dry_run,
            "simulate_disk": app.state.simulate_disk,
        }

    @app.get("/api/i18n/{lang}")
    def i18n(lang: str) -> dict[str, str]:
        if lang not in {"de", "en"}:
            raise HTTPException(400, "unsupported language")
        path = Path(__file__).resolve().parents[1] / "i18n" / f"{lang}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    @app.post("/api/language")
    def set_lang(payload: LangBody) -> dict[str, str]:
        if payload.language not in {"de", "en"}:
            raise HTTPException(400, "unsupported language")
        set_language(payload.language)
        app.state.wizard["language"] = payload.language
        return {"language": payload.language}

    @app.get("/api/network/status")
    def network_status() -> dict[str, Any]:
        online = check_internet(timeout=2.0)
        app.state.wizard["online"] = online
        return {
            "online": online,
            "has_wifi": has_wifi_radio(),
            "ethernet": ethernet_carrier(),
        }

    @app.post("/api/network/check")
    def network_check() -> dict[str, Any]:
        started = time.monotonic()
        status = prepare_and_check(wait_seconds=12.0)
        remain = 1.4 - (time.monotonic() - started)
        if remain > 0:
            time.sleep(remain)
        app.state.wizard["online"] = bool(status.get("online"))
        return status

    @app.post("/api/network/ethernet/up")
    def ethernet_up() -> dict[str, Any]:
        status = prepare_and_check(wait_seconds=15.0)
        app.state.wizard["online"] = bool(status.get("online"))
        return status

    @app.get("/api/network/wifi")
    def wifi_scan(rescan: bool = True) -> dict[str, Any]:
        if not has_wifi_radio():
            return {"networks": [], "has_wifi": False}
        nets = list_wifi_networks(rescan=rescan)
        return {
            "has_wifi": True,
            "networks": [
                {"ssid": n.ssid, "signal": n.signal, "security": n.security} for n in nets
            ],
        }

    @app.post("/api/network/wifi/connect")
    def wifi_connect(payload: WifiConnectBody) -> dict[str, Any]:
        ok, err = connect_wifi(payload.ssid.strip(), payload.password)
        online = False
        if ok:
            time.sleep(1.0)
            online = check_internet(timeout=3.0)
            app.state.wizard["online"] = online
        return {"ok": ok, "error": err, "online": online}

    @app.get("/api/catalog")
    def catalog(mode: str = "simple") -> dict[str, Any]:
        if mode not in {"simple", "multiboot", "add", "remove"}:
            raise HTTPException(400, "bad mode")
        use = "add" if mode == "remove" else mode
        items = []
        for entry in catalog_for_mode(use):
            items.append(
                {
                    "id": entry.id,
                    "variant": entry.variant,
                    "display_name": entry.display_name,
                    "family": entry.family,
                }
            )
        return {"mode": mode, "items": items}

    @app.get("/api/state")
    def get_state() -> dict[str, Any]:
        return dict(app.state.wizard)

    @app.post("/api/state")
    def post_state(payload: StatePatch) -> dict[str, Any]:
        data = payload.model_dump(exclude_none=True)
        app.state.wizard.update(data)
        return dict(app.state.wizard)

    @app.get("/api/disks")
    def disks() -> dict[str, Any]:
        items = []
        for d in get_disks(simulate=app.state.simulate_disk):
            items.append(
                {
                    "id": d.id,
                    "path": d.path,
                    "size_bytes": d.size_bytes,
                    "size_gib": round(d.size_gib, 1),
                    "model": d.model,
                    "serial": d.serial,
                    "transport": d.transport,
                    "is_removable": d.is_removable,
                }
            )
        return {"items": items, "simulate": bool(app.state.simulate_disk)}

    @app.get("/api/storage/preview")
    def storage_preview(disk_id: str = "") -> dict[str, Any]:
        disks_list = get_disks(simulate=app.state.simulate_disk)
        disk = next((d for d in disks_list if d.id == disk_id or d.path == disk_id), None)
        if disk is None and disks_list:
            disk = disks_list[0]
        if disk is None:
            return {"disk": None, "partitions": []}

        selected_raw = app.state.wizard.get("selected") or []
        selections = []
        mins = {}
        for item in selected_raw:
            sid = str(item.get("id") or "")
            variant = str(item.get("variant") or "standard")
            name = str(item.get("display_name") or sid)
            if not sid:
                continue
            selections.append(DistroSelection(id=sid, variant=variant, display_name=name))
            try:
                mins[sid] = get_adapter(sid).info.minimum_root_gib
            except Exception:
                mins[sid] = 20
        if not selections:
            return {
                "disk": {
                    "id": disk.id,
                    "path": disk.path,
                    "size_gib": round(disk.size_gib, 1),
                    "model": disk.model,
                },
                "partitions": [],
                "error": "no_distro",
            }

        mode = str(app.state.wizard.get("mode") or "simple")
        try:
            parts, warnings = equal_root_layout(
                disk.size_bytes,
                selections,
                include_swap=bool(app.state.wizard.get("include_swap", True)),
                include_data=bool(app.state.wizard.get("include_data", True))
                and mode == "multiboot",
                minimum_root_gib=mins,
                strict_minimums=False,
            )
        except ValueError as exc:
            return {
                "disk": {
                    "id": disk.id,
                    "path": disk.path,
                    "size_gib": round(disk.size_gib, 1),
                    "model": disk.model,
                },
                "partitions": [],
                "warnings": [],
                "error": str(exc),
            }
        app.state.wizard["disk_id"] = disk.id
        app.state.wizard["disk_path"] = disk.path
        app.state.wizard["disk_size_bytes"] = disk.size_bytes
        return {
            "disk": {
                "id": disk.id,
                "path": disk.path,
                "size_gib": round(disk.size_gib, 1),
                "model": disk.model,
            },
            "partitions": [
                {
                    "role": p.role,
                    "size_mib": p.size_mib,
                    "filesystem": p.filesystem,
                    "label": p.label,
                    "distribution": p.distribution,
                }
                for p in parts
            ],
            "warnings": warnings,
        }

    @app.post("/api/install/start")
    def install_start() -> dict[str, Any]:
        if not app.state.wizard.get("selected"):
            raise HTTPException(400, "no_distro")
        if not app.state.wizard.get("disk_path"):
            raise HTTPException(400, "no_disk")
        dry = bool(app.state.dry_run) or os.environ.get("ULI_DRY_RUN", "0") == "1"
        return start_install(dict(app.state.wizard), dry_run=dry)

    @app.get("/api/install/status")
    def install_status() -> dict[str, Any]:
        return get_job()

    @app.post("/api/system/reboot")
    def system_reboot() -> dict[str, Any]:
        # Live ISO only — best-effort reboot
        for cmd in (["systemctl", "reboot"], ["reboot"], ["shutdown", "-r", "now"]):
            try:
                subprocess.Popen(cmd)  # noqa: S603
                return {"ok": True, "cmd": cmd[0]}
            except OSError:
                continue
        raise HTTPException(500, "reboot_failed")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "index.html",
            headers={"Cache-Control": "no-store"},
        )

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


def run_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    dry_run: bool = False,
    simulate_disk: bool = False,
) -> None:
    import uvicorn

    app = create_app(dry_run=dry_run, simulate_disk=simulate_disk)
    uvicorn.run(app, host=host, port=port, log_level="info")
