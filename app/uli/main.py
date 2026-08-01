from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="uli", description="Ultimate Linux Installer")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Never perform destructive disk operations",
    )
    parser.add_argument(
        "--simulate-disk",
        action="store_true",
        default=True,
        help="Use simulated disks when not running from the live ISO (default)",
    )
    parser.add_argument(
        "--lang",
        choices=("de", "en"),
        default="de",
        help="UI language (default: de)",
    )
    parser.add_argument(
        "--headless-plan",
        metavar="PATH",
        help="Validate/print an installation plan JSON/YAML and exit",
    )
    args = parser.parse_args(argv)

    if args.headless_plan:
        from uli.core.plan import load_plan

        plan = load_plan(args.headless_plan)
        print(plan.to_yaml())
        return 0

    from uli.ui.app import run_ui

    return run_ui(language=args.lang, dry_run=args.dry_run, simulate_disk=args.simulate_disk)


if __name__ == "__main__":
    sys.exit(main())
