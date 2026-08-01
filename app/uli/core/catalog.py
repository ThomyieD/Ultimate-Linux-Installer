"""Catalog of MVP distributions and helper queries."""

from __future__ import annotations

from dataclasses import dataclass

from uli.core.adapters import AdapterInfo, ensure_builtin_adapters, list_adapters


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    variant: str
    display_name: str
    family: str
    modes: tuple[str, ...]
    minimum_root_gib: int
    icon: str


def catalog_for_mode(mode: str) -> list[CatalogEntry]:
    ensure_builtin_adapters()
    entries: list[CatalogEntry] = []
    for adapter in list_adapters():
        info: AdapterInfo = adapter.info
        if mode not in info.installation_modes:
            continue
        for variant in info.variants:
            suffix = ""
            if variant not in {"standard", info.id}:
                suffix = f" {variant.replace('_', ' ').title()}"
            entries.append(
                CatalogEntry(
                    id=info.id,
                    variant=variant,
                    display_name=f"{info.display_name}{suffix}".strip(),
                    family=info.family,
                    modes=info.installation_modes,
                    minimum_root_gib=info.minimum_root_gib,
                    icon=info.icon,
                )
            )
    return entries
