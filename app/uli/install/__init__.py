"""Install orchestration helpers.

Job exports are lazy so importing :mod:`uli.install.runner` from the GRUB layer
does not create an install.job -> grub -> install package cycle.
"""

from typing import Any

from uli.install.isos import IsoArtifact, resolve_iso

__all__ = ["IsoArtifact", "get_job", "resolve_iso", "start_install"]


def __getattr__(name: str) -> Any:
    if name in {"get_job", "start_install"}:
        from uli.install import job

        return getattr(job, name)
    raise AttributeError(name)
