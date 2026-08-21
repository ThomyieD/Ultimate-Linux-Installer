"""Background orchestration for a confirmed, immutable installation plan."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import traceback
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from uli.bootloader.grub import (
    install_chef_grub,
    preflight_chef_grub_build,
    validate_chef_grub,
    validate_uefi_environment,
)
from uli.core.plan import InstallationPlan
from uli.install.apt_preflight import AptPreflightError, run_apt_preflight
from uli.install.provision import ProvisionResult, provision_plan, validate_host_timezone
from uli.install.sources import verify_plan_sources
from uli.state.machine import InstallState, default_state_path, load_state
from uli.storage.executor import StorageGuard


@dataclass
class InstallJob:
    status: str = "idle"  # idle|running|done|error
    phase: str = ""
    message: str = ""
    percent: int = 0
    error: str = ""
    artifact_dir: str = ""
    downloads: list[dict[str, Any]] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    current_distribution: str = ""
    log: list[str] = field(default_factory=list)
    dry_run: bool = True
    installation_complete: bool = False
    _state_path: str = field(default="", repr=False)
    _log_path: str = field(default="", repr=False)
    _secret_needles: tuple[str, ...] = field(default=(), repr=False)
    _generation: int = field(default=0, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)


_job = InstallJob()
_lock = threading.RLock()
_PLAN_ID = re.compile(r"^[a-f0-9]{12}$")
_REQUIRED_REAL_TOOLS = (
    "apt-get",
    "blkid",
    "chroot",
    "debootstrap",
    "efibootmgr",
    "gpgv",
    "grub-mkfont",
    "grub-mkstandalone",
    "grub-script-check",
    "lsblk",
    "mkfs.ext4",
    "mkfs.vfat",
    "mkswap",
    "mount",
    "partprobe",
    "sgdisk",
    "udevadm",
    "umount",
    "wipefs",
)


def get_job() -> dict[str, Any]:
    with _lock:
        log_path = Path(_job._log_path) if _job._log_path else None
        has_log = bool(log_path and log_path.is_file())
        return {
            "status": _job.status,
            "phase": _job.phase,
            "message": _job.message,
            "percent": _job.percent,
            "error": _job.error,
            "artifact_dir": _job.artifact_dir,
            "downloads": [dict(item) for item in _job.downloads],
            "completed": list(_job.completed),
            "current_distribution": _job.current_distribution,
            "log": list(_job.log[-80:]),
            "dry_run": _job.dry_run,
            "installation_complete": _job.installation_complete,
            "has_install_log": has_log,
            "install_log_name": "install.log" if has_log else "",
        }


def get_install_log_path() -> Path | None:
    """Return the current job's install.log or None (no client-controlled path)."""

    with _lock:
        if not _job._log_path or not _job.artifact_dir:
            return None
        log_path = Path(_job._log_path)
        artifact = Path(_job.artifact_dir)
    try:
        log_resolved = log_path.resolve()
        artifact_resolved = artifact.resolve()
    except OSError:
        return None
    if log_resolved.name != "install.log":
        return None
    if log_resolved.parent != artifact_resolved:
        return None
    if not log_resolved.is_file():
        return None
    return log_resolved


def _set(**values: Any) -> None:
    with _lock:
        for key, value in values.items():
            setattr(_job, key, value)


def _secret_needles(plan: InstallationPlan) -> tuple[str, ...]:
    needles: list[str] = []
    password_hash = plan.user.password_hash
    if isinstance(password_hash, str) and password_hash:
        needles.append(password_hash)
    for key in plan.user.ssh_keys:
        if isinstance(key, str) and key.strip():
            needles.append(key.strip())
    return tuple(needles)


def _redact(message: str, needles: tuple[str, ...]) -> str:
    text = message
    for needle in needles:
        if needle:
            text = text.replace(needle, "<redacted>")
    return text


def _log(message: str) -> None:
    with _lock:
        text = _redact(str(message), _job._secret_needles)
        _job.log.append(text)
        if len(_job.log) > 500:
            _job.log = _job.log[-500:]
        log_path = _job._log_path
    if log_path:
        try:
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(text + "\n")
        except OSError as exc:
            with _lock:
                _job.log.append(f"install.log write failed: {exc}")


def start_install(plan: InstallationPlan, *, dry_run: bool = False) -> dict[str, Any]:
    """Start one job; callers must have performed the confirmation handshake."""
    if not isinstance(plan, InstallationPlan):
        raise TypeError("start_install requires an InstallationPlan")
    if not _PLAN_ID.fullmatch(plan.plan_id):
        raise ValueError("Invalid internal plan identifier")
    plan.require_confirmed()
    if plan.mode not in {"simple", "multiboot"} or not plan.disk.wipe:
        raise ValueError("Only confirmed whole-disk simple/multiboot plans are executable")

    with _lock:
        if _job.status == "running":
            return get_job()
        _job.status = "running"
        _job.phase = "prepare"
        _job.message = "Installationsplan wird geprüft"
        _job.percent = 1
        _job.error = ""
        _job.artifact_dir = ""
        _job.downloads = []
        _job.completed = []
        _job.current_distribution = ""
        _job.log = []
        _job.dry_run = dry_run
        _job.installation_complete = False
        _job._state_path = ""
        _job._log_path = ""
        _job._generation += 1
        generation = _job._generation
        _job._secret_needles = _secret_needles(plan)

    def runner() -> None:
        try:
            state, state_path = _run(plan, dry_run=dry_run)
            state.status = "completed"
            state.current = None
            state.remaining = []
            state.error = None
            state.save(state_path)
            _set(
                status="done",
                phase="done",
                percent=100,
                message="Simulation erfolgreich" if dry_run else "Installation erfolgreich",
                installation_complete=not dry_run,
                current_distribution="",
            )
        except Exception as exc:  # noqa: BLE001 - thread boundary must record every failure
            _log(traceback.format_exc())
            with _lock:
                failed_state_path = _job._state_path
            if failed_state_path:
                try:
                    failed_state = load_state(failed_state_path)
                    if failed_state.plan_id == plan.plan_id:
                        failed_state.status = "failed"
                        failed_state.error = _redact(str(exc), _secret_needles(plan))
                        failed_state.save(failed_state_path)
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as state_error:
                    _log(f"state save failed: {state_error}")
            _set(
                status="error",
                phase="failed",
                error=_redact(str(exc), _secret_needles(plan)),
                message="Installation fehlgeschlagen",
                installation_complete=False,
            )
        finally:
            # The hash is no longer needed after account provisioning and must
            # not remain reachable through the global job/thread lifecycle.
            plan.user.password_hash = None
            with _lock:
                # Only the worker that still owns the global slot may clear
                # needles; a successor job must keep its own redaction set.
                if _job._generation == generation:
                    _job._secret_needles = ()

    thread = threading.Thread(target=runner, name="uli-install", daemon=True)
    with _lock:
        _job._thread = thread
    thread.start()
    return get_job()


def _writable_cache_root() -> Path:
    candidates = (
        Path("/var/cache/uli"),
        Path.home() / ".cache" / "uli",
        Path("/tmp/uli-cache"),
    )
    for root in candidates:
        try:
            root.mkdir(parents=True, exist_ok=True)
            probe = root / f".write-test-{threading.get_ident()}"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return root
        except OSError:
            continue
    raise RuntimeError("Kein beschreibbarer Installations-Cache verfügbar")


def _save_state(state: InstallState, preferred_path: Path, fallback: Path) -> Path:
    try:
        state.save(preferred_path)
        return preferred_path
    except OSError:
        state.save(fallback)
        return fallback


def _public_plan(plan: InstallationPlan) -> dict[str, Any]:
    payload = plan.to_dict()
    payload["user"]["password_hash"] = None
    payload["user"]["ssh_keys"] = ["<redacted>" for _key in plan.user.ssh_keys]
    payload["confirmed"] = True
    return payload


def _write_audit(out: Path, plan: InstallationPlan, *, dry_run: bool) -> None:
    audit = {
        "plan": _public_plan(plan),
        "dry_run": dry_run,
        "note": "Dry-run records commands only; it does not install an operating system."
        if dry_run
        else "Plan validated and confirmed through the destructive-operation handshake.",
    }
    (out / "audit.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _assign_dry_run_uuids(plan: InstallationPlan) -> None:
    for index, part in enumerate(plan.partitions, start=1):
        part.uuid = (
            f"F000-{index:04X}"
            if part.filesystem == "fat32"
            else f"00000000-0000-4000-8000-{index:012d}"
        )


def _open_install_log(out: Path) -> Path:
    log_path = out / "install.log"
    fd = os.open(log_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    return log_path


def _preflight_installation(plan: InstallationPlan, *, dry_run: bool) -> None:
    """Validate the complete root/GRUB plan and all host tools before wiping."""
    preview = deepcopy(plan)
    _assign_dry_run_uuids(preview)
    provision_plan(preview, dry_run=True)
    validate_chef_grub(preview, dry_run=True)
    if dry_run:
        return

    # Resolve the requested tzdata entry on the immutable live system before
    # StorageGuard gets any opportunity to issue a destructive command.
    validate_host_timezone(plan.locale.timezone)
    missing = [name for name in _REQUIRED_REAL_TOOLS if shutil.which(name) is None]
    if missing:
        raise RuntimeError("Erforderliche Installationswerkzeuge fehlen: " + ", ".join(missing))
    if not Path("/usr/lib/grub/x86_64-efi").is_dir():
        raise RuntimeError("GRUB-x86_64-efi-Module fehlen im Live-System")
    if not Path("/usr/share/grub/unicode.pf2").is_file():
        raise RuntimeError("GRUB-Unicode-Schrift fehlt im Live-System")
    theme_fonts = (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    )
    if missing_fonts := [str(path) for path in theme_fonts if not path.is_file()]:
        raise RuntimeError("GRUB-Theme-Schriften fehlen: " + ", ".join(missing_fonts))
    theme = plan.bootloader.theme
    theme_candidates = (
        Path(__file__).resolve().parents[3] / "themes" / "grub" / theme / "theme.txt",
        Path("/usr/share/uli/themes") / theme / "theme.txt",
        Path("/usr/share/uli/themes/grub") / theme / "theme.txt",
        Path("/opt/uli/themes/grub") / theme / "theme.txt",
    )
    if not any(candidate.is_file() for candidate in theme_candidates):
        raise RuntimeError(f"GRUB-Theme {theme!r} fehlt im Live-System")
    preflight_commands = preflight_chef_grub_build(preview)
    _log(f"pre-wipe GRUB build verified ({len(preflight_commands)} commands)")


def _run(plan: InstallationPlan, *, dry_run: bool) -> tuple[InstallState, Path]:
    _set(phase="prepare", message="Installationsplan wird validiert", percent=3)
    if plan.mode not in {"simple", "multiboot"}:
        raise RuntimeError(f"Modus {plan.mode!r} ist noch nicht implementiert")
    plan.require_confirmed()

    cache_root = _writable_cache_root().resolve()
    out = cache_root / plan.plan_id
    if out.parent != cache_root or not _PLAN_ID.fullmatch(out.name):
        raise RuntimeError("Unsafe internal installation cache path")
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=False)
    out.chmod(0o700)
    log_path = _open_install_log(out)
    _set(artifact_dir=str(out), _log_path=str(log_path))
    _write_audit(out, plan, dry_run=dry_run)
    _log(f"plan={plan.plan_id} target={plan.disk.id} cache={out}")

    keys = [f"{item.id}:{item.variant}" for item in plan.distributions]
    state = InstallState(plan_id=plan.plan_id, status="validated", remaining=keys)
    state_path = _save_state(state, default_state_path(), out / "install-state.json")
    _set(_state_path=str(state_path))

    # The signed repository metadata is fetched and verified before the first
    # destructive command.  Dry-run still performs this meaningful preflight.
    _set(phase="verify", message="Offizielle Paketquellen werden geprüft", percent=8)

    def source_progress(index: int, total: int, source: Any) -> None:
        percent = 8 + int((index / max(total, 1)) * 10)
        _set(
            phase="verify",
            message=f"Signaturprüfung: {source.distro_id} {source.version}",
            percent=percent,
        )

    verified = verify_plan_sources(
        plan.distributions,
        out / "sources",
        progress=source_progress,
    )
    _log("verified sources: " + ", ".join(path.name for path in verified))
    state.status = "sources_verified"
    state.save(state_path)

    # Platform/firmware/Secure-Boot support is also checked before the wipe.
    validate_uefi_environment(dry_run=dry_run)
    _preflight_installation(plan, dry_run=dry_run)

    _set(phase="verify", message="Paketauflösung wird vor dem Wipe geprüft", percent=18)
    try:
        run_apt_preflight(plan, out, dry_run=dry_run, log=_log)
    except AptPreflightError as exc:
        raise RuntimeError(str(exc)) from exc

    # Dry-run must remain host-independent, so UUID placeholders are inserted
    # only after the storage command plan is validated and recorded.
    _set(phase="partitioning", message="Datenträgerlayout wird angewendet", percent=20)
    state.status = "partitioning"
    state.save(state_path)
    guard = StorageGuard(dry_run=dry_run)
    storage_commands = guard.apply_plan(plan)
    (out / "partition-commands.txt").write_text(
        "\n".join(storage_commands) + "\n",
        encoding="utf-8",
    )
    if dry_run:
        _assign_dry_run_uuids(plan)
        _log("dry-run: partition commands validated; no device was modified")
    else:
        if any(not part.uuid for part in plan.partitions):
            raise RuntimeError("Storage completed without filesystem UUIDs")
        _log("partition table and filesystems created; UUIDs refreshed")
    state.status = "filesystems"
    state.save(state_path)

    _set(phase="installing", message="Root-Systeme werden installiert", percent=35)
    state.status = "installing"
    state.save(state_path)

    def provision_progress(phase: str, percent: int, message: str) -> None:
        mapped = 35 + int(percent * 0.48)
        current = next((key for key in keys if key in message), "")
        _set(
            phase="installing",
            message=message,
            percent=min(mapped, 83),
            current_distribution=current,
        )

    result: ProvisionResult = provision_plan(
        plan,
        dry_run=dry_run,
        progress=provision_progress,
        log=_log,
    )
    _set(completed=list(result.completed), current_distribution="")
    state.completed = list(result.completed)
    state.remaining = [key for key in keys if key not in state.completed]
    state.current = None
    state.status = "verifying"
    state.save(state_path)
    if result.completed != keys:
        raise RuntimeError("Not every selected root system completed provisioning")

    _set(phase="verifying", message="Installierte Systeme werden geprüft", percent=85)
    validate_chef_grub(plan, dry_run=dry_run)

    state.status = "bootloader"
    state.save(state_path)
    _set(phase="bootloader", message="Zentraler UEFI-Bootloader wird installiert", percent=88)

    def grub_progress(_phase: str, percent: int, message: str) -> None:
        _set(
            phase="bootloader",
            message=message,
            percent=88 + int(percent * 0.11),
        )

    grub_result = install_chef_grub(
        plan,
        dry_run=dry_run,
        progress=grub_progress,
        log=_log,
    )
    if not dry_run and not grub_result.nvram_configured:
        raise RuntimeError(
            "UEFI-Firmwareeintrag oder BootOrder konnte nicht verlässlich eingerichtet werden; "
            "der EFI/BOOT-Fallback wurde geschrieben, die Installation gilt aber nicht als fertig"
        )
    status_payload = {
        "plan_id": plan.plan_id,
        "dry_run": dry_run,
        "completed": result.completed,
        "bootloader": {
            "efi_directory": grub_result.efi_directory,
            "loader_path": grub_result.loader_path,
            "fallback_path": grub_result.fallback_path,
            "nvram_configured": grub_result.nvram_configured,
        },
        "installation_complete": not dry_run,
    }
    (out / "result.json").write_text(
        json.dumps(status_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return state, state_path
