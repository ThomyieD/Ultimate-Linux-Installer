"""Background install job: download ISOs, write artifacts, partition disk."""

from __future__ import annotations

import json
import shutil
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from uli.bootloader.grub import render_efi_bootorder_fix, render_grub_cfg
from uli.core.adapters import get_adapter
from uli.core.plan import (
    BootloaderConfig,
    DiskTarget,
    DistroSelection,
    InstallationPlan,
    LocaleConfig,
    UserConfig,
)
from uli.downloads import DownloadItem, download_file
from uli.install.isos import resolve_iso
from uli.security.secrets import hash_password
from uli.state.machine import InstallState, default_state_path
from uli.storage.executor import StorageGuard
from uli.storage.layout import equal_root_layout


@dataclass
class InstallJob:
    status: str = "idle"  # idle|running|done|error
    phase: str = ""
    message: str = ""
    percent: int = 0
    error: str = ""
    artifact_dir: str = ""
    downloads: list[dict[str, Any]] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    dry_run: bool = True
    _thread: threading.Thread | None = field(default=None, repr=False)


_job = InstallJob()
_lock = threading.Lock()


def get_job() -> dict[str, Any]:
    with _lock:
        return {
            "status": _job.status,
            "phase": _job.phase,
            "message": _job.message,
            "percent": _job.percent,
            "error": _job.error,
            "artifact_dir": _job.artifact_dir,
            "downloads": list(_job.downloads),
            "log": list(_job.log[-40:]),
            "dry_run": _job.dry_run,
        }


def _set(**kwargs: Any) -> None:
    with _lock:
        for k, v in kwargs.items():
            setattr(_job, k, v)


def _log(msg: str) -> None:
    with _lock:
        _job.log.append(msg)
        if len(_job.log) > 200:
            _job.log = _job.log[-200:]


def _build_plan(wizard: dict[str, Any], *, confirmed: bool) -> InstallationPlan:
    selected_raw = wizard.get("selected") or []
    selections = [
        DistroSelection(
            id=str(s["id"]),
            variant=str(s.get("variant") or "standard"),
            display_name=str(s.get("display_name") or s["id"]),
        )
        for s in selected_raw
        if s.get("id")
    ]
    if not selections:
        raise RuntimeError("no_distro")

    disk_path = str(wizard.get("disk_path") or "")
    disk_id = str(wizard.get("disk_id") or disk_path)
    size = int(wizard.get("disk_size_bytes") or 0)
    if not disk_path or size <= 0:
        raise RuntimeError("no_disk")

    mins = {}
    for sel in selections:
        try:
            mins[sel.id] = get_adapter(sel.id).info.minimum_root_gib
        except Exception:
            mins[sel.id] = 20

    mode = str(wizard.get("mode") or "simple")
    parts, _warnings = equal_root_layout(
        size,
        selections,
        include_swap=bool(wizard.get("include_swap", True)),
        include_data=bool(wizard.get("include_data", True)) and mode == "multiboot",
        minimum_root_gib=mins,
        strict_minimums=False,
    )

    password = str(wizard.get("password") or "")
    lang = str(wizard.get("language") or "de")
    return InstallationPlan(
        mode=mode,  # type: ignore[arg-type]
        disk=DiskTarget(id=disk_id, path=disk_path, size_bytes=size, wipe=True),
        partitions=parts,
        distributions=selections,
        user=UserConfig(
            username=str(wizard.get("username") or "uli"),
            password_hash=hash_password(password) if password else None,
        ),
        bootloader=BootloaderConfig(theme=str(wizard.get("theme") or "uli-lenovo")),
        locale=LocaleConfig(
            language="de_DE.UTF-8" if lang == "de" else "en_US.UTF-8",
            timezone=str(wizard.get("timezone") or "Europe/Berlin"),
            keyboard=str(wizard.get("keyboard") or "de"),
        ),
        confirmed=confirmed,
    )


def start_install(wizard: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    with _lock:
        if _job.status == "running":
            return get_job()
        _job.status = "running"
        _job.phase = "prepare"
        _job.message = "prepare"
        _job.percent = 1
        _job.error = ""
        _job.artifact_dir = ""
        _job.downloads = []
        _job.log = []
        _job.dry_run = dry_run

    def runner() -> None:
        try:
            _run(wizard, dry_run=dry_run)
            _set(status="done", phase="done", percent=100, message="done")
        except Exception as exc:
            _log(traceback.format_exc())
            _set(status="error", error=str(exc), message="error")

    t = threading.Thread(target=runner, name="uli-install", daemon=True)
    _job._thread = t
    t.start()
    return get_job()


def _writable_cache_root() -> Path:
    """Prefer /var/cache/uli when writable; otherwise fall back to user/tmp."""
    candidates = [
        Path("/var/cache/uli"),
        Path.home() / ".cache" / "uli",
        Path("/tmp/uli-cache"),
    ]
    for root in candidates:
        try:
            root.mkdir(parents=True, exist_ok=True)
            probe = root / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return root
        except OSError:
            continue
    raise RuntimeError("No writable cache directory for downloads/artifacts")


def _run(wizard: dict[str, Any], *, dry_run: bool) -> None:
    _set(phase="prepare", message="Building installation plan…", percent=5)
    plan = _build_plan(wizard, confirmed=True)
    out = _writable_cache_root() / plan.plan_id
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    _set(artifact_dir=str(out))
    plan.save(out / "plan.yaml")
    _log(f"plan={plan.plan_id} disk={plan.disk.path} cache={out.parent}")

    # Downloads
    iso_dir = out / "iso"
    iso_dir.mkdir(parents=True, exist_ok=True)
    total = max(len(plan.distributions), 1)
    for idx, sel in enumerate(plan.distributions):
        _set(
            phase="download",
            message=f"Resolving {sel.display_name}…",
            percent=10 + int(idx / total * 40),
        )
        artifact = resolve_iso(sel)
        dest = iso_dir / artifact.name
        item_state = {
            "id": f"{sel.id}:{sel.variant}",
            "name": sel.display_name,
            "file": artifact.name,
            "url": artifact.url,
            "status": "fetching",
            "percent": 0,
            "bytes": 0,
            "total": 0,
        }
        with _lock:
            _job.downloads.append(item_state)

        def on_progress(downloaded: int, total_bytes: int, _item=item_state, _idx=idx) -> None:
            pct = int(downloaded * 100 / total_bytes) if total_bytes else 0
            with _lock:
                _item["bytes"] = downloaded
                _item["total"] = total_bytes
                _item["percent"] = pct
                base = 10 + int(_idx / total * 40)
                _job.percent = min(49, base + int(pct * 0.4 / total))
                _job.message = f"Downloading {_item['name']} ({pct}%)"

        _log(f"download {artifact.url}")
        download_file(
            DownloadItem(
                name=artifact.name,
                url=artifact.url,
                destination=dest,
                sha256=artifact.sha256,
            ),
            timeout=120,
            progress=on_progress,
        )
        with _lock:
            item_state["status"] = "done"
            item_state["percent"] = 100
        _log(f"saved {dest}")

    # Automation artifacts
    _set(phase="artifacts", message="Writing autoinstall / hooks…", percent=55)
    for sel in plan.distributions:
        adapter = get_adapter(sel.id)
        files = adapter.generate_automation(plan, sel)
        dist_dir = out / sel.id / sel.variant
        dist_dir.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            (dist_dir / name).write_text(content, encoding="utf-8")
        hooks = adapter.post_install_hooks(plan, sel)
        (dist_dir / "post-hooks.sh").write_text("\n\n".join(hooks) + "\n", encoding="utf-8")
    (out / "grub.cfg").write_text(render_grub_cfg(plan), encoding="utf-8")
    (out / "reclaim-bootorder.sh").write_text(render_efi_bootorder_fix(), encoding="utf-8")

    # Partitioning
    _set(phase="partition", message="Partitioning target disk…", percent=70)
    guard = StorageGuard(dry_run=dry_run)
    cmds = guard.apply_partition_table(plan.disk.path, plan.partitions, confirmed=True)
    (out / "partition-commands.sh").write_text("\n".join(cmds) + "\n", encoding="utf-8")
    _log("partition commands written")
    if dry_run:
        _log("dry-run: partitions not applied")
    else:
        _log("partitions applied")

    # Stage note — full OS unattended install from ISO is next milestone;
    # we record a clear status file so the UI stays honest.
    status = {
        "plan_id": plan.plan_id,
        "downloaded": [d.name for d in (iso_dir.iterdir() if iso_dir.exists() else [])],
        "partitioned": not dry_run,
        "dry_run": dry_run,
        "next": "autoinstall_from_iso",
        "message": (
            "ISOs downloaded and target prepared. "
            "Unattended OS install from the ISO image is the next implementation step."
        ),
    }
    (out / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")

    state = InstallState(
        plan_id=plan.plan_id,
        status="installing",
        remaining=[f"{d.id}:{d.variant}" for d in plan.distributions],
    )
    try:
        state.save(default_state_path())
    except OSError:
        state.save(out / "install-state.json")

    _set(phase="bootloader", message="Bootloader config prepared…", percent=90)
    time.sleep(0.4)
    _set(phase="done", message="Preparation complete", percent=100)
