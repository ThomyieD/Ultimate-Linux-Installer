from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from uli.core.plan import DiskTarget, DistroSelection, InstallationPlan, PartitionSpec, UserConfig


def test_current_plan_matches_public_schema() -> None:
    plan = InstallationPlan(
        mode="simple",
        disk=DiskTarget("disk", "/dev/sda", 64 * 1024**3),
        partitions=[
            PartitionSpec("esp", 1024, "fat32", label="EFI"),
            PartitionSpec("root", 30 * 1024, "ext4", "debian:server", "root-debian"),
        ],
        distributions=[DistroSelection("debian", "server", "Debian Server")],
        user=UserConfig("uliuser", "$6$test$hash"),
    )
    schema = json.loads(
        Path("schemas/installation_plan.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(plan.to_dict())
