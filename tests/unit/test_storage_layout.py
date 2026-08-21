from __future__ import annotations

import pytest
from uli.core.plan import DistroSelection, PartitionSpec
from uli.storage.layout import (
    SAFETY_MIB,
    custom_root_layout,
    equal_root_layout,
    validate_layout,
)

GIB = 1024**3


def _distros() -> list[DistroSelection]:
    return [
        DistroSelection("ubuntu", "desktop", "Ubuntu Desktop"),
        DistroSelection("fedora", "workstation", "Fedora Workstation"),
    ]


def test_equal_layout_uses_exact_configured_swap_and_data_sizes() -> None:
    parts, warnings = equal_root_layout(
        128 * GIB,
        _distros(),
        swap_size_mib=4096,
        data_size_mib=12_288,
    )

    roots = [part for part in parts if part.role == "root"]
    assert len({part.size_mib for part in roots}) == 1
    assert next(part for part in parts if part.role == "swap").size_mib == 4096
    assert next(part for part in parts if part.role == "data").size_mib == 12_288
    assert warnings == []
    assert sum(part.size_mib for part in parts) <= 128 * 1024 - SAFETY_MIB


def test_equal_layout_soft_preview_warns_but_real_plan_is_strict() -> None:
    with pytest.raises(ValueError, match="minimum sizes"):
        equal_root_layout(40 * GIB, _distros())

    parts, warnings = equal_root_layout(
        40 * GIB,
        _distros(),
        strict_minimums=False,
    )
    assert len([part for part in parts if part.role == "root"]) == 2
    assert {warning.split(":")[0] for warning in warnings} >= {
        "swap_reduced",
        "below_minimum",
    }


def test_custom_layout_preserves_individual_and_auxiliary_sizes() -> None:
    parts = custom_root_layout(
        128 * GIB,
        {"ubuntu:desktop": 25 * 1024, "fedora:workstation": 30 * 1024},
        _distros(),
        swap_size_mib=3072,
        data_size_mib=8192,
    )

    roots = [part for part in parts if part.role == "root"]
    assert [part.size_mib for part in roots] == [25 * 1024, 30 * 1024]
    assert [part.distribution for part in roots] == [
        "ubuntu:desktop",
        "fedora:workstation",
    ]
    assert next(part for part in parts if part.role == "swap").size_mib == 3072
    assert next(part for part in parts if part.role == "data").size_mib == 8192


def test_layout_preassigns_unique_gpt_partuuids() -> None:
    parts, _warnings = equal_root_layout(128 * GIB, _distros())
    ids = [part.partuuid for part in parts]

    assert all(ids)
    assert len(ids) == len(set(ids))


def test_generated_ext4_labels_fit_filesystem_limit() -> None:
    distros = [
        DistroSelection(
            "distribution-with-an-extremely-long-name",
            "desktop-with-an-extremely-long-name",
            "Long Linux",
        )
    ]
    parts, _warnings = equal_root_layout(
        64 * GIB,
        distros,
        include_data=False,
    )
    root = next(part for part in parts if part.role == "root")

    assert root.label is not None
    assert len(root.label.encode("ascii")) <= 16


def test_same_distribution_variants_have_unambiguous_partition_owners() -> None:
    distros = [
        DistroSelection("ubuntu", "desktop", "Ubuntu Desktop"),
        DistroSelection("ubuntu", "server", "Ubuntu Server"),
    ]
    parts, _warnings = equal_root_layout(128 * GIB, distros)
    assert [part.distribution for part in parts if part.role == "root"] == [
        "ubuntu:desktop",
        "ubuntu:server",
    ]


def test_partition_spec_rejects_oversized_ext4_label() -> None:
    with pytest.raises(ValueError, match="16 bytes"):
        PartitionSpec(
            role="root",
            size_mib=20 * 1024,
            filesystem="ext4",
            label="seventeen-chars---",
        )


def test_validate_layout_rejects_capacity_overflow() -> None:
    parts = [
        PartitionSpec(role="esp", size_mib=1024, filesystem="fat32", label="EFI"),
        PartitionSpec(
            role="root",
            size_mib=63 * 1024,
            filesystem="ext4",
            distribution="ubuntu",
            label="root-ubuntu",
        ),
    ]

    assert "Partition sizes exceed disk capacity" in validate_layout(parts, 64 * GIB)


def test_disabled_auxiliary_partition_rejects_nonzero_size() -> None:
    with pytest.raises(ValueError, match="swap is disabled"):
        equal_root_layout(
            64 * GIB,
            [DistroSelection("ubuntu", "desktop", "Ubuntu")],
            include_swap=False,
            swap_size_mib=1024,
            include_data=False,
        )
