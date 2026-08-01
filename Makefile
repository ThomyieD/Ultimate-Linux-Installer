.PHONY: install test run iso qemu themes

install:
	python3 -m pip install -e ".[dev]"

test:
	python3 -m pytest -q

run:
	ULI_SIMULATE_DISK=1 ULI_DRY_RUN=1 python3 -m uli.main --dry-run --lang de

themes:
	bash scripts/generate-theme-assets.sh

iso:
	bash scripts/build-iso.sh

qemu:
	bash scripts/run-qemu.sh
