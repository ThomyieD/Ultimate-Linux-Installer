"""Isolated APT update/resolve checks that run before any disk wipe."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from uli.core.plan import DistroSelection, InstallationPlan
from uli.install.provision import apt_package_names, distro_sources_list
from uli.install.runner import CommandRunner

LogCallback = Callable[[str], None]

_FORBIDDEN_APT_FLAGS = (
    "trusted=yes",
    "--allow-unauthenticated",
    "--allow-insecure-repositories",
    "--no-check-gpg",
)


class AptPreflightError(RuntimeError):
    """Signed APT metadata could not be updated or packages could not resolve."""


def _assert_safe_argv(argv: tuple[str, ...]) -> None:
    joined = " ".join(argv)
    for token in _FORBIDDEN_APT_FLAGS:
        if token in joined:
            raise AptPreflightError(f"Unsafe APT option refused: {token}")
    lowered = joined.lower()
    for needle in (
        "acquire::allowinsecurerepositories=true",
        "acquire::allowinsecurerepositories=1",
        "acquire::allowinsecurerepositories=yes",
        "apt::get::allowunauthenticated=true",
        "apt::get::allowunauthenticated=1",
        "apt::get::allowunauthenticated=yes",
    ):
        if needle in lowered:
            raise AptPreflightError(f"Unsafe APT option refused: {needle}")


def _groups_by_distro(plan: InstallationPlan) -> list[tuple[str, list[DistroSelection]]]:
    """Group selections by archive identity while preserving plan order."""

    order: list[str] = []
    groups: dict[str, list[DistroSelection]] = {}
    for selection in plan.distributions:
        if selection.id not in groups:
            order.append(selection.id)
            groups[selection.id] = []
        groups[selection.id].append(selection)
    return [(distro_id, groups[distro_id]) for distro_id in order]


def _packages_for_group(
    selections: list[DistroSelection],
    plan: InstallationPlan,
) -> tuple[str, ...]:
    packages: set[str] = set()
    for selection in selections:
        packages.update(apt_package_names(selection, plan))
    return tuple(sorted(packages))


def run_apt_preflight(
    plan: InstallationPlan,
    work_dir: Path,
    *,
    dry_run: bool,
    runner: CommandRunner | None = None,
    log: LogCallback | None = None,
) -> None:
    """Verify package names resolve against official signed sources before wipe."""

    emit = log or (lambda _message: None)
    if dry_run:
        emit("apt preflight skipped (dry-run; no network)")
        return

    if runner is None:
        runner = CommandRunner(dry_run=False, log=emit)
    elif runner.dry_run:
        raise AptPreflightError(
            "APT preflight refuses a dry-run command runner while dry_run=False"
        )

    work_dir = work_dir.resolve()
    preflight_root = work_dir / "apt-preflight"
    if preflight_root.exists():
        shutil.rmtree(preflight_root)
    preflight_root.mkdir(parents=True, exist_ok=False)
    preflight_root.chmod(0o700)

    try:
        for distro_id, selections in _groups_by_distro(plan):
            _run_one(distro_id, selections, plan, preflight_root, runner=runner, log=emit)
        emit("apt preflight ok: package resolution verified before wipe")
    finally:
        shutil.rmtree(preflight_root, ignore_errors=True)


def _run_one(
    distro_id: str,
    selections: list[DistroSelection],
    plan: InstallationPlan,
    preflight_root: Path,
    *,
    runner: CommandRunner,
    log: LogCallback,
) -> None:
    # Variants of one distro share the archive; use the first selection for sources.
    sources_text, keyring = distro_sources_list(selections[0])
    if not Path(keyring).is_file():
        raise AptPreflightError(f"Archive keyring missing for preflight: {keyring}")
    if "signed-by=" not in sources_text or "https://" not in sources_text:
        raise AptPreflightError("APT preflight refuses sources without HTTPS signed-by")
    for token in _FORBIDDEN_APT_FLAGS:
        if token in sources_text:
            raise AptPreflightError(f"Unsafe APT source option refused: {token}")

    root = Path(
        tempfile.mkdtemp(
            prefix=f"{distro_id}-",
            dir=str(preflight_root),
        )
    )
    etc_apt = root / "etc" / "apt"
    lists = root / "var" / "lib" / "apt" / "lists"
    cache = root / "var" / "cache" / "apt" / "archives"
    dpkg = root / "var" / "lib" / "dpkg"
    for path in (etc_apt, lists, cache / "partial", dpkg):
        path.mkdir(parents=True, exist_ok=True)
    (dpkg / "status").write_text("", encoding="utf-8")
    (etc_apt / "sources.list").write_text(sources_text, encoding="utf-8")
    (etc_apt / "apt.conf.d").mkdir(parents=True, exist_ok=True)

    apt_opts = (
        f"-oDir={root}",
        f"-oDir::State={root / 'var' / 'lib' / 'apt'}",
        f"-oDir::Cache={root / 'var' / 'cache' / 'apt'}",
        f"-oDir::Etc={etc_apt}",
        "-oDir::Etc::sourcelist=sources.list",
        "-oDir::Etc::sourceparts=-",
        f"-oDir::State::Status={dpkg / 'status'}",
        "-oAPT::Architecture=amd64",
        "-oAPT::Architectures=amd64",
        "-oAPT::Get::AllowUnauthenticated=false",
        "-oAcquire::AllowInsecureRepositories=false",
        "-oAcquire::AllowDowngradeToInsecureRepositories=false",
        "-oDebug::NoLocking=1",
    )
    update_argv = ("apt-get", *apt_opts, "update")
    _assert_safe_argv(update_argv)
    try:
        runner.run(update_argv, env={"DEBIAN_FRONTEND": "noninteractive", "LC_ALL": "C.UTF-8"})
    except Exception as exc:
        raise AptPreflightError(
            f"APT update failed for {distro_id} before wipe: {exc}"
        ) from exc

    packages = _packages_for_group(selections, plan)
    if distro_id == "debian" and "tasksel" not in packages:
        raise AptPreflightError("Debian preflight package set must include tasksel")
    if (
        distro_id == "debian"
        and any(item.variant == "desktop" for item in selections)
        and "task-gnome-desktop" not in packages
    ):
        raise AptPreflightError("Debian desktop preflight must include task-gnome-desktop")

    simulate_argv = ("apt-get", *apt_opts, "install", "-s", "-y", "--", *packages)
    _assert_safe_argv(simulate_argv)
    try:
        runner.run(
            simulate_argv,
            env={"DEBIAN_FRONTEND": "noninteractive", "LC_ALL": "C.UTF-8"},
        )
    except Exception as exc:
        raise AptPreflightError(
            f"APT package resolution failed for {distro_id} before wipe: {exc}"
        ) from exc
    log(f"apt preflight resolved {distro_id} ({len(packages)} packages)")
