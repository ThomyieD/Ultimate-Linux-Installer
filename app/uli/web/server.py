"""FastAPI backend for the primary live-ISO wizard.

The browser is deliberately treated as untrusted.  It may select opaque IDs and
configuration values, but it never supplies a device path, a disk size, a
partition command, or the final installation plan.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import secrets
import subprocess
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Response
from fastapi.requests import Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from starlette.middleware.trustedhost import TrustedHostMiddleware

from uli import __version__
from uli.core.adapters import get_adapter
from uli.core.catalog import CatalogEntry, catalog_for_mode
from uli.core.plan import (
    BootloaderConfig,
    DiskTarget,
    DistroSelection,
    InstallationPlan,
    LocaleConfig,
    NetworkConfig,
    UserConfig,
)
from uli.i18n import set_language
from uli.install.job import get_install_log_path, get_job, start_install
from uli.install.provision import (
    RESERVED_SYSTEM_USERNAMES,
    SUPPORTED_KEYBOARDS,
    is_safe_timezone_name,
)
from uli.install.sources import SUPPORTED_SELECTIONS, source_for
from uli.network.connectivity import (
    check_internet,
    connect_wifi,
    ethernet_carrier,
    has_wifi_radio,
    list_devices,
    list_wifi_networks,
    prepare_and_check,
)
from uli.security.secrets import (
    fetch_github_keys,
    fetch_launchpad_keys,
    fingerprint_ssh_key,
    hash_password,
    validate_ssh_public_key,
)
from uli.storage.disks import get_disks
from uli.storage.layout import DiskInfo, DiskTooSmallError, custom_root_layout, equal_root_layout

STATIC_DIR = Path(__file__).resolve().parent / "static"
_USERNAME = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_HOSTNAME = re.compile(r"^(?=.{1,63}$)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
_REMOTE_ACCOUNT = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_-]{0,38}[A-Za-z0-9])?$")
_KEYBOARDS = SUPPORTED_KEYBOARDS
_THEMES = {"uli-lenovo", "uli-dark"}
_CONFIRMATION_TTL_SECONDS = 120
_MAX_MULTIBOOT_ROOTS = 7


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LangBody(StrictModel):
    language: Literal["de", "en"]


class WifiConnectBody(StrictModel):
    ssid: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(default=SecretStr(""), max_length=256)


class SelectionBody(StrictModel):
    id: str = Field(min_length=1, max_length=32)
    variant: str = Field(default="standard", min_length=1, max_length=32)
    display_name: str | None = Field(default=None, max_length=96)


class StatePatch(StrictModel):
    mode: Literal["simple", "multiboot"] | None = None
    selected: list[SelectionBody] | None = Field(default=None, max_length=_MAX_MULTIBOOT_ROOTS)
    username: str | None = Field(default=None, max_length=32)
    password: SecretStr | None = Field(default=None, min_length=8, max_length=128)
    theme: Literal["uli-lenovo", "uli-dark"] | None = None
    disk_id: str | None = Field(default=None, max_length=160)
    include_swap: bool | None = None
    include_data: bool | None = None
    swap_size_mib: int | None = Field(default=None, ge=256, le=64 * 1024)
    data_size_mib: int | None = Field(default=None, ge=1024, le=8 * 1024 * 1024)
    partition_strategy: Literal["equal", "individual"] | None = None
    root_sizes_mib: dict[str, int] | None = None
    timezone: str | None = Field(default=None, max_length=128)
    keyboard: str | None = Field(default=None, max_length=32)
    language: Literal["de", "en"] | None = None
    hostnames: dict[str, str] | None = None
    ssh_keys: list[str] | None = Field(default=None, max_length=50)
    install_ssh_server: bool | None = None
    disable_password_auth: bool | None = None
    boot_timeout_seconds: int | None = Field(default=None, ge=1, le=60)
    boot_default: str | None = Field(default=None, max_length=80)


class SshImportBody(StrictModel):
    provider: Literal["launchpad", "github"]
    username: str = Field(min_length=1, max_length=40)


class ConfirmBody(StrictModel):
    disk_id: str = Field(min_length=1, max_length=160)
    plan_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    acknowledged: Literal[True]


class StartBody(StrictModel):
    confirmation_token: str = Field(min_length=32, max_length=256)


def _default_wizard(language: str) -> dict[str, Any]:
    return {
        "language": language,
        "mode": "simple",
        "online": False,
        "selected": [],
        "username": "",
        "password_hash": None,
        "theme": "uli-lenovo",
        "disk_id": "",
        "include_swap": True,
        "swap_size_mib": 8192,
        "include_data": False,
        "data_size_mib": 65536,
        "partition_strategy": "equal",
        "root_sizes_mib": {},
        "timezone": "Europe/Berlin",
        "keyboard": "de",
        "hostnames": {},
        "ssh_keys": [],
        "install_ssh_server": True,
        "disable_password_auth": False,
        "boot_timeout_seconds": 5,
        "boot_default": "",
    }


def _public_wizard(wizard: dict[str, Any]) -> dict[str, Any]:
    public = {key: deepcopy(value) for key, value in wizard.items() if key != "password_hash"}
    public["has_password"] = bool(wizard.get("password_hash"))
    return public


def _disk_public(disk: DiskInfo) -> dict[str, Any]:
    return {
        "id": disk.id,
        "path": disk.path,
        "size_bytes": disk.size_bytes,
        "size_gib": round(disk.size_gib, 1),
        "model": disk.model,
        "serial": disk.serial,
        "wwn": disk.wwn,
        "disk_sequence": disk.disk_sequence,
        "transport": disk.transport,
        "is_removable": disk.is_removable,
    }


def _find_disk(app: FastAPI, disk_id: str) -> DiskInfo:
    matches = [
        disk
        for disk in get_disks(simulate=bool(app.state.simulate_disk))
        if secrets.compare_digest(disk.id, disk_id)
    ]
    if len(matches) != 1:
        raise HTTPException(404, "unknown_disk")
    return matches[0]


def _same_disk(left: DiskInfo, right: DiskInfo) -> bool:
    return (
        left.id == right.id
        and left.path == right.path
        and left.size_bytes == right.size_bytes
        and left.serial == right.serial
        and left.model == right.model
        and left.wwn == right.wwn
        and left.major_minor == right.major_minor
        and left.disk_sequence == right.disk_sequence
    )


def _catalog_entry(mode: str, distro_id: str, variant: str) -> CatalogEntry | None:
    if mode not in {"simple", "multiboot"}:
        return None
    return next(
        (
            entry
            for entry in catalog_for_mode(mode)
            if entry.id == distro_id and entry.variant == variant
        ),
        None,
    )


def _selection_key(selection: dict[str, Any] | DistroSelection) -> str:
    if isinstance(selection, DistroSelection):
        return f"{selection.id}:{selection.variant}"
    return f"{selection['id']}:{selection['variant']}"


def _normalize_selections(mode: str, values: list[SelectionBody]) -> list[dict[str, str]]:
    if not values:
        return []
    if mode == "simple" and len(values) != 1:
        raise HTTPException(400, "simple_requires_exactly_one_distribution")
    if mode == "multiboot" and not 2 <= len(values) <= _MAX_MULTIBOOT_ROOTS:
        raise HTTPException(400, "multiboot_requires_two_to_seven_distributions")

    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in values:
        entry = _catalog_entry(mode, value.id, value.variant)
        if entry is None:
            raise HTTPException(400, f"unknown_distribution:{value.id}:{value.variant}")
        if (entry.id, entry.variant) not in SUPPORTED_SELECTIONS:
            raise HTTPException(409, f"distribution_not_released:{entry.id}:{entry.variant}")
        key = f"{entry.id}:{entry.variant}"
        if key in seen:
            raise HTTPException(400, f"duplicate_distribution:{key}")
        seen.add(key)
        normalized.append(
            {"id": entry.id, "variant": entry.variant, "display_name": entry.display_name}
        )
    return normalized


def _validate_configuration(wizard: dict[str, Any], *, require_complete: bool) -> None:
    selected = wizard.get("selected") or []
    if require_complete and not selected:
        raise ValueError("no_distro")
    mode = str(wizard.get("mode") or "")
    if mode not in {"simple", "multiboot"}:
        raise ValueError("unsupported_mode")
    if selected and mode == "simple" and len(selected) != 1:
        raise ValueError("simple_requires_exactly_one_distribution")
    if selected and mode == "multiboot" and not 2 <= len(selected) <= _MAX_MULTIBOOT_ROOTS:
        raise ValueError("multiboot_requires_two_to_seven_distributions")
    seen_selections: set[str] = set()
    for item in selected:
        entry = _catalog_entry(mode, str(item.get("id")), str(item.get("variant")))
        if entry is None or (entry.id, entry.variant) not in SUPPORTED_SELECTIONS:
            raise ValueError("unsupported_distribution")
        key = _selection_key(item)
        if key in seen_selections:
            raise ValueError("duplicate_distribution")
        seen_selections.add(key)

    username = str(wizard.get("username") or "")
    if require_complete and not _USERNAME.fullmatch(username):
        raise ValueError("invalid_username")
    if username and not _USERNAME.fullmatch(username):
        raise ValueError("invalid_username")
    if username in RESERVED_SYSTEM_USERNAMES:
        raise ValueError("reserved_username")
    if require_complete and not wizard.get("password_hash"):
        raise ValueError("password_required")

    timezone = str(wizard.get("timezone") or "")
    if not is_safe_timezone_name(timezone):
        raise ValueError("invalid_timezone")
    if wizard.get("keyboard") not in _KEYBOARDS:
        raise ValueError("invalid_keyboard")
    if wizard.get("theme") not in _THEMES:
        raise ValueError("invalid_theme")

    keys = [validate_ssh_public_key(str(key)) for key in wizard.get("ssh_keys") or []]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate_ssh_key")
    if wizard.get("disable_password_auth"):
        if not wizard.get("install_ssh_server"):
            raise ValueError("ssh_password_policy_without_server")
        if not keys:
            raise ValueError("ssh_key_required_when_password_login_is_disabled")

    selection_keys = {_selection_key(item) for item in selected}
    hostnames = wizard.get("hostnames") or {}
    if require_complete and set(hostnames) != selection_keys:
        raise ValueError("hostnames_do_not_match_selections")
    values: list[str] = []
    for key, hostname in hostnames.items():
        if key not in selection_keys or not _HOSTNAME.fullmatch(str(hostname)):
            raise ValueError("invalid_hostname")
        values.append(str(hostname))
    if len(values) != len(set(values)):
        raise ValueError("duplicate_hostname")

    default_entry = str(wizard.get("boot_default") or "")
    if require_complete and default_entry not in selection_keys:
        raise ValueError("invalid_boot_default")
    if default_entry and default_entry not in selection_keys:
        raise ValueError("invalid_boot_default")

    root_sizes = wizard.get("root_sizes_mib") or {}
    if len(root_sizes) > _MAX_MULTIBOOT_ROOTS:
        raise ValueError("too_many_root_sizes")
    for key, size in root_sizes.items():
        if key not in selection_keys:
            raise ValueError("root_size_for_unknown_distribution")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise ValueError("invalid_root_size")
    if (
        wizard.get("partition_strategy") == "individual"
        and require_complete
        and set(root_sizes) != selection_keys
    ):
        raise ValueError("custom_root_sizes_do_not_match_selections")


def _build_plan(wizard: dict[str, Any], disk: DiskInfo) -> tuple[InstallationPlan, list[str]]:
    _validate_configuration(wizard, require_complete=True)
    mode = str(wizard["mode"])
    if mode not in {"simple", "multiboot"}:
        raise ValueError("unsupported_mode")

    selections: list[DistroSelection] = []
    minimums: dict[str, int] = {}
    hostnames = wizard["hostnames"]
    for item in wizard["selected"]:
        entry = _catalog_entry(mode, item["id"], item["variant"])
        if entry is None or (entry.id, entry.variant) not in SUPPORTED_SELECTIONS:
            raise ValueError(f"unsupported_distribution:{item['id']}:{item['variant']}")
        source = source_for(
            DistroSelection(entry.id, entry.variant, entry.display_name)
        )
        selection = DistroSelection(
            id=entry.id,
            variant=entry.variant,
            display_name=entry.display_name,
            release=source.version,
            hostname=hostnames[f"{entry.id}:{entry.variant}"],
        )
        selections.append(selection)
        minimums[f"{entry.id}:{entry.variant}"] = get_adapter(entry.id).info.minimum_root_gib

    layout_options = {
        "include_swap": bool(wizard["include_swap"]),
        "include_data": bool(wizard["include_data"]),
        "swap_size_mib": int(wizard["swap_size_mib"]) if wizard["include_swap"] else None,
        "data_size_mib": int(wizard["data_size_mib"]) if wizard["include_data"] else None,
        "minimum_root_gib": minimums,
        "strict_minimums": True,
    }
    if wizard["partition_strategy"] == "individual":
        partitions = custom_root_layout(
            disk.size_bytes,
            dict(wizard["root_sizes_mib"]),
            selections,
            **layout_options,
        )
        warnings: list[str] = []
    else:
        partitions, warnings = equal_root_layout(
            disk.size_bytes,
            selections,
            **layout_options,
        )

    language = "de_DE.UTF-8" if wizard["language"] == "de" else "en_US.UTF-8"
    plan = InstallationPlan(
        mode=mode,  # type: ignore[arg-type]
        disk=DiskTarget(
            id=disk.id,
            path=disk.path,
            size_bytes=disk.size_bytes,
            wipe=True,
            model=disk.model,
            serial=disk.serial,
            wwn=disk.wwn,
            major_minor=disk.major_minor,
            disk_sequence=disk.disk_sequence,
        ),
        partitions=partitions,
        distributions=selections,
        user=UserConfig(
            username=wizard["username"],
            password_hash=wizard["password_hash"],
            ssh_keys=list(wizard["ssh_keys"]),
            sudo=True,
            disable_password_auth=bool(wizard["disable_password_auth"]),
            install_ssh_server=bool(wizard["install_ssh_server"]),
        ),
        bootloader=BootloaderConfig(
            theme=wizard["theme"],
            timeout_seconds=int(wizard["boot_timeout_seconds"]),
            default_entry=wizard["boot_default"],
        ),
        locale=LocaleConfig(
            language=language,
            timezone=wizard["timezone"],
            keyboard=wizard["keyboard"],
        ),
        network=NetworkConfig(method="dhcp", persist=True),
        confirmed=False,
    )
    return plan, warnings


def _fingerprint(plan: InstallationPlan) -> str:
    encoded = json.dumps(
        plan.to_dict(),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _invalidate_preview(app: FastAPI) -> None:
    app.state.preview_plan = None
    app.state.preview_disk = None
    app.state.preview_fingerprint = ""
    app.state.preview_revision = -1
    app.state.confirmations.clear()


def create_app(
    *,
    dry_run: bool = False,
    simulate_disk: bool = False,
    language: str = "de",
) -> FastAPI:
    if language not in {"de", "en"}:
        raise ValueError("language must be 'de' or 'en'")
    if simulate_disk and not dry_run:
        raise ValueError("simulated disks are permitted only together with --dry-run")
    set_language(language)
    app = FastAPI(title="Ultimate Linux Installer", version=__version__)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"],
    )
    app.state.dry_run = dry_run
    app.state.simulate_disk = simulate_disk
    app.state.wizard = _default_wizard(language)
    app.state.revision = 0
    app.state.preview_plan = None
    app.state.preview_disk = None
    app.state.preview_fingerprint = ""
    app.state.preview_revision = -1
    app.state.confirmations: dict[str, dict[str, Any]] = {}
    app.state.state_lock = threading.RLock()
    app.state.csrf_token = secrets.token_urlsafe(48)

    @app.middleware("http")
    async def local_request_gate(request: Request, call_next: Any) -> Any:
        """Block cross-site/DNS-rebinding writes to the root installer API."""
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin:
                origin_host = ""
                try:
                    origin_host = urlsplit(origin).hostname or ""
                    origin_is_loopback = ipaddress.ip_address(origin_host).is_loopback
                except ValueError:
                    origin_is_loopback = False
                if origin_host.lower() == "localhost":
                    origin_is_loopback = True
                if not origin_is_loopback:
                    return JSONResponse({"detail": "cross_site_request_blocked"}, status_code=403)
            if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
                return JSONResponse({"detail": "cross_site_request_blocked"}, status_code=403)
            supplied = request.headers.get("x-uli-csrf", "")
            if not secrets.compare_digest(supplied, app.state.csrf_token):
                return JSONResponse({"detail": "csrf_token_required"}, status_code=403)
        return await call_next(request)

    @app.get("/api/health")
    def health(response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        return {
            "ok": True,
            "version": __version__,
            "dry_run": bool(app.state.dry_run),
            "simulate_disk": bool(app.state.simulate_disk),
            "csrf_token": app.state.csrf_token,
        }

    @app.get("/api/i18n/{lang}")
    def i18n(lang: str) -> dict[str, str]:
        if lang not in {"de", "en"}:
            raise HTTPException(400, "unsupported_language")
        path = Path(__file__).resolve().parents[1] / "i18n" / f"{lang}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    @app.post("/api/language")
    def set_lang(payload: LangBody) -> dict[str, str]:
        set_language(payload.language)
        with app.state.state_lock:
            app.state.wizard["language"] = payload.language
            app.state.revision += 1
            _invalidate_preview(app)
        return {"language": payload.language}

    @app.get("/api/network/status")
    def network_status() -> dict[str, Any]:
        online = check_internet(timeout=2.0)
        with app.state.state_lock:
            app.state.wizard["online"] = online
        return {
            "online": online,
            "has_wifi": has_wifi_radio(),
            "ethernet": ethernet_carrier(),
            "devices": [
                {
                    "name": device.name,
                    "type": device.type,
                    "state": device.state,
                    "connection": device.connection,
                }
                for device in list_devices()
            ],
        }

    @app.post("/api/network/check")
    def network_check() -> dict[str, Any]:
        started = time.monotonic()
        status = prepare_and_check(wait_seconds=12.0)
        remaining = 1.4 - (time.monotonic() - started)
        if remaining > 0:
            time.sleep(remaining)
        with app.state.state_lock:
            app.state.wizard["online"] = bool(status.get("online"))
        return status

    @app.post("/api/network/ethernet/up")
    def ethernet_up() -> dict[str, Any]:
        status = prepare_and_check(wait_seconds=15.0)
        with app.state.state_lock:
            app.state.wizard["online"] = bool(status.get("online"))
        return status

    @app.get("/api/network/wifi")
    def wifi_scan(rescan: bool = True) -> dict[str, Any]:
        if not has_wifi_radio():
            return {"networks": [], "has_wifi": False}
        networks = list_wifi_networks(rescan=rescan)
        return {
            "has_wifi": True,
            "networks": [
                {"ssid": item.ssid, "signal": item.signal, "security": item.security}
                for item in networks
            ],
        }

    @app.post("/api/network/wifi/connect")
    def wifi_connect(payload: WifiConnectBody) -> dict[str, Any]:
        ok, error = connect_wifi(payload.ssid.strip(), payload.password.get_secret_value())
        online = False
        if ok:
            time.sleep(1.0)
            online = check_internet(timeout=3.0)
            with app.state.state_lock:
                app.state.wizard["online"] = online
        return {"ok": ok, "error": error, "online": online}

    @app.get("/api/catalog")
    def catalog(mode: str = "simple") -> dict[str, Any]:
        if mode not in {"simple", "multiboot", "add", "remove"}:
            raise HTTPException(400, "bad_mode")
        catalog_mode = mode if mode in {"simple", "multiboot"} else "simple"
        items: list[dict[str, Any]] = []
        for entry in catalog_for_mode(catalog_mode):
            released = (entry.id, entry.variant) in SUPPORTED_SELECTIONS
            version = ""
            if released:
                version = source_for(
                    DistroSelection(entry.id, entry.variant, entry.display_name)
                ).version
            items.append(
                {
                    "id": entry.id,
                    "variant": entry.variant,
                    "display_name": entry.display_name,
                    "family": entry.family,
                    "minimum_root_gib": entry.minimum_root_gib,
                    "icon": entry.icon,
                    "version": version,
                    "enabled": released and mode in {"simple", "multiboot"},
                    "reason": "Noch nicht für eine reale Installation freigegeben"
                    if not released
                    else "",
                }
            )
        return {"mode": mode, "items": items}

    @app.get("/api/sources")
    def sources(mode: str = "simple") -> dict[str, Any]:
        if mode not in {"simple", "multiboot"}:
            raise HTTPException(409, "mode_not_implemented")
        with app.state.state_lock:
            selected = deepcopy(app.state.wizard.get("selected") or [])
        items: list[dict[str, Any]] = []
        for value in selected:
            selection = DistroSelection(
                id=value["id"],
                variant=value["variant"],
                display_name=value["display_name"],
            )
            try:
                source = source_for(selection)
            except ValueError as exc:
                items.append(
                    {
                        **value,
                        "enabled": False,
                        "reason": str(exc),
                    }
                )
                continue
            items.append(
                {
                    **source.public_dict(),
                    "id": selection.id,
                    "variant": selection.variant,
                    "display_name": selection.display_name,
                    "enabled": True,
                }
            )
        return {"items": items}

    @app.post("/api/ssh/import")
    def ssh_import(payload: SshImportBody) -> dict[str, Any]:
        username = payload.username.strip()
        if not _REMOTE_ACCOUNT.fullmatch(username):
            raise HTTPException(400, "invalid_remote_account")
        try:
            keys = (
                fetch_launchpad_keys(username)
                if payload.provider == "launchpad"
                else fetch_github_keys(username)
            )
        except Exception as exc:
            raise HTTPException(502, f"ssh_key_import_failed:{type(exc).__name__}") from exc
        unique = list(dict.fromkeys(keys))
        return {
            "keys": [
                {
                    "key": key,
                    "fingerprint": fingerprint_ssh_key(key).partition(" ")[2],
                    "selected": True,
                }
                for key in unique
            ]
        }

    @app.get("/api/state")
    def get_state() -> dict[str, Any]:
        with app.state.state_lock:
            return _public_wizard(app.state.wizard)

    @app.post("/api/state")
    def post_state(payload: StatePatch) -> dict[str, Any]:
        raw = payload.model_dump(exclude_none=True)
        password = raw.pop("password", None)
        with app.state.state_lock:
            candidate = deepcopy(app.state.wizard)
            mode = str(raw.get("mode", candidate["mode"]))
            if "selected" in raw:
                selected_models = payload.selected or []
                raw["selected"] = _normalize_selections(mode, selected_models)
            candidate.update(raw)
            if "selected" in raw:
                active = {_selection_key(item) for item in candidate["selected"]}
                if "hostnames" not in raw:
                    candidate["hostnames"] = {
                        key: value
                        for key, value in candidate.get("hostnames", {}).items()
                        if key in active
                    }
                if "root_sizes_mib" not in raw:
                    candidate["root_sizes_mib"] = {
                        key: value
                        for key, value in candidate.get("root_sizes_mib", {}).items()
                        if key in active
                    }
                if "boot_default" not in raw and candidate.get("boot_default") not in active:
                    candidate["boot_default"] = ""
            if password is not None:
                candidate["password_hash"] = hash_password(password.get_secret_value())
            candidate["username"] = str(candidate.get("username") or "").strip()
            candidate["timezone"] = str(candidate.get("timezone") or "").strip()
            candidate["hostnames"] = {
                str(key): str(value).strip()
                for key, value in (candidate.get("hostnames") or {}).items()
            }
            try:
                candidate["ssh_keys"] = [
                    validate_ssh_public_key(str(key)) for key in candidate.get("ssh_keys") or []
                ]
                _validate_configuration(candidate, require_complete=False)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            app.state.wizard = candidate
            app.state.revision += 1
            _invalidate_preview(app)
            return _public_wizard(candidate)

    @app.get("/api/disks")
    def disks() -> dict[str, Any]:
        return {
            "items": [
                _disk_public(disk)
                for disk in get_disks(simulate=bool(app.state.simulate_disk))
            ],
            "simulate": bool(app.state.simulate_disk),
        }

    @app.get("/api/storage/preview")
    def storage_preview(disk_id: str = "") -> dict[str, Any]:
        if not disk_id:
            raise HTTPException(400, "no_disk")
        disk = _find_disk(app, disk_id)
        with app.state.state_lock:
            cached_plan: InstallationPlan | None = app.state.preview_plan
            cached_disk: DiskInfo | None = app.state.preview_disk
            if (
                cached_plan is not None
                and cached_disk is not None
                and app.state.preview_revision == app.state.revision
                and _same_disk(cached_disk, disk)
            ):
                plan = cached_plan
                warnings = []
                fingerprint = app.state.preview_fingerprint
            else:
                try:
                    plan, warnings = _build_plan(app.state.wizard, disk)
                except DiskTooSmallError as exc:
                    return {
                        "disk": _disk_public(disk),
                        "partitions": [],
                        "warnings": [],
                        "error": exc.code,
                        "error_code": exc.code,
                        "required_mib": exc.required_mib,
                        "available_mib": exc.available_mib,
                        "plan_fingerprint": "",
                    }
                except (TypeError, ValueError) as exc:
                    return {
                        "disk": _disk_public(disk),
                        "partitions": [],
                        "warnings": [],
                        "error": str(exc),
                        "plan_fingerprint": "",
                    }
                fingerprint = _fingerprint(plan)
                app.state.wizard["disk_id"] = disk.id
                app.state.preview_plan = plan
                app.state.preview_disk = deepcopy(disk)
                app.state.preview_fingerprint = fingerprint
                app.state.preview_revision = app.state.revision
                app.state.confirmations.clear()
        return {
            "disk": _disk_public(disk),
            "partitions": [
                {
                    "role": part.role,
                    "size_mib": part.size_mib,
                    "filesystem": part.filesystem,
                    "label": part.label,
                    "distribution": part.distribution,
                }
                for part in plan.partitions
            ],
            "warnings": warnings,
            "error": "",
            "plan_fingerprint": fingerprint,
        }

    @app.post("/api/install/confirm")
    def install_confirm(payload: ConfirmBody) -> dict[str, Any]:
        if get_job()["status"] == "running":
            raise HTTPException(409, "installation_already_running")
        if not app.state.dry_run and not check_internet(timeout=3.0):
            raise HTTPException(409, "internet_required")
        disk = _find_disk(app, payload.disk_id)
        with app.state.state_lock:
            plan: InstallationPlan | None = app.state.preview_plan
            preview_disk: DiskInfo | None = app.state.preview_disk
            if (
                plan is None
                or preview_disk is None
                or app.state.preview_revision != app.state.revision
                or not secrets.compare_digest(
                    payload.plan_fingerprint, app.state.preview_fingerprint
                )
                or plan.disk.id != payload.disk_id
                or not _same_disk(preview_disk, disk)
            ):
                raise HTTPException(409, "plan_or_disk_changed")
            token = secrets.token_urlsafe(48)
            app.state.confirmations.clear()
            app.state.confirmations[token] = {
                "created": time.monotonic(),
                "fingerprint": app.state.preview_fingerprint,
                "revision": app.state.revision,
                "disk": deepcopy(disk),
                "plan": deepcopy(plan),
            }
        return {
            "confirmation_token": token,
            "expires_in_seconds": _CONFIRMATION_TTL_SECONDS,
        }

    @app.post("/api/install/start")
    def install_start(payload: StartBody) -> dict[str, Any]:
        if get_job()["status"] == "running":
            raise HTTPException(409, "installation_already_running")
        with app.state.state_lock:
            confirmation = app.state.confirmations.pop(payload.confirmation_token, None)
            if confirmation is None:
                raise HTTPException(409, "invalid_or_used_confirmation")
            if time.monotonic() - confirmation["created"] > _CONFIRMATION_TTL_SECONDS:
                raise HTTPException(409, "confirmation_expired")
            if confirmation["revision"] != app.state.revision:
                raise HTTPException(409, "configuration_changed")
            plan = confirmation["plan"]
            expected_disk = confirmation["disk"]

        current_disk = _find_disk(app, expected_disk.id)
        if not _same_disk(expected_disk, current_disk):
            raise HTTPException(409, "disk_changed")
        plan.disk.path = current_disk.path
        plan.disk.size_bytes = current_disk.size_bytes
        plan.disk.model = current_disk.model
        plan.disk.serial = current_disk.serial
        plan.disk.wwn = current_disk.wwn
        plan.disk.major_minor = current_disk.major_minor
        plan.disk.disk_sequence = current_disk.disk_sequence
        plan.confirmed = True
        dry = bool(app.state.dry_run) or os.environ.get("ULI_DRY_RUN", "0") == "1"
        result = start_install(plan, dry_run=dry)
        with app.state.state_lock:
            app.state.preview_plan = None
            app.state.preview_disk = None
            app.state.preview_fingerprint = ""
            app.state.confirmations.clear()
            app.state.wizard["password_hash"] = None
        return result

    @app.get("/api/install/status")
    def install_status() -> dict[str, Any]:
        return get_job()

    @app.get("/api/install/log")
    def install_log_download() -> FileResponse:
        path = get_install_log_path()
        if path is None:
            raise HTTPException(404, "install_log_unavailable")
        return FileResponse(
            path,
            media_type="text/plain; charset=utf-8",
            filename="install.log",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/system/reboot")
    def system_reboot() -> dict[str, Any]:
        job = get_job()
        if (
            job["status"] != "done"
            or job.get("dry_run")
            or not job.get("installation_complete")
        ):
            raise HTTPException(409, "installation_not_complete")
        for command in (["systemctl", "reboot"], ["reboot"], ["shutdown", "-r", "now"]):
            try:
                subprocess.Popen(command)
                return {"ok": True, "cmd": command[0]}
            except OSError:
                continue
        raise HTTPException(500, "reboot_failed")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def run_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    dry_run: bool = False,
    simulate_disk: bool = False,
    language: str = "de",
) -> None:
    if not dry_run and host.lower() not in {"127.0.0.1", "localhost"}:
        raise ValueError("A real installer backend may bind only to 127.0.0.1 or localhost")

    import uvicorn

    app = create_app(
        dry_run=dry_run,
        simulate_disk=simulate_disk,
        language=language,
    )
    uvicorn.run(app, host=host, port=port, log_level="info")
