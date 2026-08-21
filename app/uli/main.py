from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="uli", description="Ultimate Linux Installer")
    parser.add_argument(
        "--ui",
        choices=("web", "qt"),
        default="web",
        help="User interface (default: web)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Web UI bind host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8787,
        help="Web UI port (default: 8787)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Never perform destructive disk operations",
    )
    parser.add_argument(
        "--simulate-disk",
        action="store_true",
        default=False,
        help="Use simulated disks (for desktop testing without real disks)",
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
        from jsonschema import Draft202012Validator

        from uli.core.plan import load_plan

        plan = load_plan(args.headless_plan)
        schema_candidates = (
            Path(__file__).resolve().parents[2] / "schemas" / "installation_plan.schema.json",
            Path("/usr/share/uli/schemas/installation_plan.schema.json"),
        )
        schema_path = next((path for path in schema_candidates if path.is_file()), None)
        if schema_path is None:
            raise RuntimeError("Installation plan schema is not installed")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(plan.to_dict())
        print(plan.to_yaml())
        return 0

    if args.ui == "qt":
        if not args.dry_run:
            parser.error("The legacy Qt UI is simulation-only; use --dry-run")
        from uli.i18n import set_language
        from uli.ui.app import run_ui

        set_language(args.lang)
        return run_ui(
            language=args.lang,
            dry_run=args.dry_run,
            simulate_disk=args.simulate_disk,
        )

    from uli.i18n import set_language
    from uli.web.server import run_server

    set_language(args.lang)
    run_server(
        host=args.host,
        port=args.port,
        dry_run=args.dry_run,
        simulate_disk=args.simulate_disk,
        language=args.lang,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
