from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any, Protocol

from uli.core.plan import DistroSelection, InstallationPlan


@dataclass(frozen=True)
class AdapterInfo:
    id: str
    family: str
    display_name: str
    variants: tuple[str, ...]
    installation_modes: tuple[str, ...]
    automation: str
    minimum_root_gib: int
    supports_desktop: bool
    supports_server: bool
    icon: str = "linux"


class DistroAdapter(Protocol):
    info: AdapterInfo

    def resolve_release(self, selection: DistroSelection) -> dict[str, Any]:
        """Return download metadata for the newest supported release."""

    def generate_automation(
        self, plan: InstallationPlan, selection: DistroSelection
    ) -> dict[str, str]:
        """Return mapping of relative filename -> file contents."""

    def post_install_hooks(self, plan: InstallationPlan, selection: DistroSelection) -> list[str]:
        """Shell snippets applied in the installed system (chroot)."""


_REGISTRY: dict[str, DistroAdapter] = {}


def register(adapter: DistroAdapter) -> DistroAdapter:
    _REGISTRY[adapter.info.id] = adapter
    return adapter


def get_adapter(distro_id: str) -> DistroAdapter:
    ensure_builtin_adapters()
    if distro_id not in _REGISTRY:
        raise KeyError(f"Unknown distribution adapter: {distro_id}")
    return _REGISTRY[distro_id]


def list_adapters() -> list[DistroAdapter]:
    ensure_builtin_adapters()
    return sorted(_REGISTRY.values(), key=lambda a: a.info.display_name.lower())


def ensure_builtin_adapters() -> None:
    if _REGISTRY:
        return
    import sys
    from pathlib import Path

    # Dev: <repo>/app/uli/core → parents[3] = repo root
    # Live: .../dist-packages/uli/core → parents[2] = dist-packages (adapters beside uli)
    here = Path(__file__).resolve()
    candidates = [
        here.parents[3],
        here.parents[2],
        Path("/usr/local/share/uli"),
        Path("/opt/uli"),
    ]
    root = next((p for p in candidates if (p / "adapters" / "__init__.py").is_file()), None)
    if root is None:
        raise RuntimeError("adapters package not found on sys.path candidates")
    path = str(root)
    if path not in sys.path:
        sys.path.insert(0, path)
    for module in (
        "adapters.debian",
        "adapters.ubuntu",
        "adapters.fedora",
        "adapters.arch",
        "adapters.proxmox",
    ):
        import_module(module)
