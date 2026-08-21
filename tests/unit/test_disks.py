from __future__ import annotations

import os
import stat
from types import SimpleNamespace

from uli.storage import disks


def test_stable_disk_path_prefers_wwn_and_excludes_partition_alias(tmp_path, monkeypatch) -> None:
    target = tmp_path / "sda"
    target.touch()
    by_id = tmp_path / "by-id"
    by_id.mkdir()
    for name in ("ata-SERIAL", "wwn-WWN", "wwn-WWN-part1"):
        (by_id / name).symlink_to(target)

    real_stat = os.stat

    def block_stat(path):
        candidate = os.fspath(path)
        if candidate == str(target) or candidate.startswith(f"{by_id}{os.sep}"):
            return SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(8, 0))
        return real_stat(path)

    monkeypatch.setattr(disks.os, "stat", block_stat)

    assert disks.find_stable_disk_path(str(target), by_id_root=by_id) == str(by_id / "wwn-WWN")


def test_candidate_disks_excludes_parent_of_live_partition(monkeypatch) -> None:
    monkeypatch.setattr(disks, "read_disk_sequence", lambda _path: 42)
    monkeypatch.setattr(
        disks,
        "_lsblk_json",
        lambda: {
            "blockdevices": [
                {
                    "name": "sda",
                    "path": "/dev/sda",
                    "type": "disk",
                    "size": 128 * 1024**3,
                    "rm": 0,
                    "tran": "sata",
                    "serial": "LIVE-DISK",
                    "children": [
                        {"name": "sda1", "path": "/dev/sda1", "type": "part"}
                    ],
                },
                {
                    "name": "nvme0n1",
                    "path": "/dev/nvme0n1",
                    "type": "disk",
                    "size": 512 * 1024**3,
                    "rm": 0,
                    "tran": "nvme",
                    "serial": "TARGET-DISK",
                },
            ]
        },
    )
    monkeypatch.setattr(disks, "detect_installation_medium_paths", lambda: {"/dev/sda1"})
    monkeypatch.setattr(
        disks,
        "find_stable_disk_path",
        lambda path: f"/dev/disk/by-id/test-{path.rsplit('/', 1)[-1]}",
    )

    candidates = disks.list_candidate_disks()
    assert [item.path for item in candidates] == ["/dev/disk/by-id/test-nvme0n1"]


def test_candidate_disks_require_serial_or_wwn(monkeypatch) -> None:
    monkeypatch.setattr(
        disks,
        "_lsblk_json",
        lambda: {
            "blockdevices": [
                {
                    "name": "sda",
                    "path": "/dev/sda",
                    "type": "disk",
                    "size": 128 * 1024**3,
                    "rm": 0,
                    "tran": "sata",
                    "serial": "",
                    "wwn": "",
                }
            ]
        },
    )
    monkeypatch.setattr(disks, "detect_installation_medium_paths", set)
    assert disks.list_candidate_disks() == []


def test_candidate_disks_require_stable_by_id_alias(monkeypatch) -> None:
    monkeypatch.setattr(
        disks,
        "_lsblk_json",
        lambda: {
            "blockdevices": [
                {
                    "name": "sda",
                    "path": "/dev/sda",
                    "type": "disk",
                    "size": 128 * 1024**3,
                    "rm": 0,
                    "tran": "sata",
                    "serial": "SERIAL",
                    "wwn": "WWN",
                }
            ]
        },
    )
    monkeypatch.setattr(disks, "detect_installation_medium_paths", set)
    monkeypatch.setattr(disks, "find_stable_disk_path", lambda _path: None)

    assert disks.list_candidate_disks() == []
