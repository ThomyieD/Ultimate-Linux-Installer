from __future__ import annotations

import stat
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from uli.core.plan import (
    BootloaderConfig,
    DiskTarget,
    DistroSelection,
    InstallationPlan,
    LocaleConfig,
    PartitionSpec,
    UserConfig,
)
from uli.install import job
from uli.install.apt_preflight import AptPreflightError
from uli.state.machine import InstallState
from uli.storage.executor import StorageGuard
from uli.web.server import create_app

SSH_TEST_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKeyMaterialForRedaction alice@example"
SSH_TEST_KEY_2 = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAISecondKeyMaterialForRedaction bob@example"
)
PASSWORD_HASH = "$6$rounds=10000$saltsalt$hashhashhashhashhashhashhashhashhashhash"
PASSWORD_HASH_2 = (
    "$6$rounds=10000$othersalt$otherhashotherhashotherhashotherhashotherhash"
)


@pytest.fixture(autouse=True)
def _reset_job_state() -> None:
    with job._lock:
        job._job = job.InstallJob()
    yield
    with job._lock:
        job._job = job.InstallJob()


def _plan(
    *,
    password_hash: str = PASSWORD_HASH,
    ssh_keys: list[str] | None = None,
) -> InstallationPlan:
    return InstallationPlan(
        mode="simple",
        disk=DiskTarget(id="disk0", path="/dev/sda", size_bytes=40 * 1024**3, wipe=True),
        partitions=[
            PartitionSpec(
                role="esp",
                size_mib=1024,
                filesystem="fat32",
                label="EFI",
                partuuid="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                uuid="12AB-34CD",
            ),
            PartitionSpec(
                role="root",
                size_mib=28 * 1024,
                filesystem="ext4",
                distribution="debian:server",
                label="deb-root",
                partuuid="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                uuid="11111111-1111-4111-8111-111111111111",
            ),
            PartitionSpec(
                role="swap",
                size_mib=8192,
                filesystem="swap",
                label="swap",
                partuuid="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                uuid="22222222-2222-4222-8222-222222222222",
            ),
        ],
        distributions=[
            DistroSelection(
                "debian",
                "server",
                "Debian Server",
                release="trixie",
                hostname="debian-server",
            )
        ],
        user=UserConfig(
            username="alice",
            password_hash=password_hash,
            ssh_keys=list(ssh_keys if ssh_keys is not None else [SSH_TEST_KEY]),
            sudo=True,
            install_ssh_server=True,
        ),
        locale=LocaleConfig(language="de_DE.UTF-8", timezone="Europe/Berlin", keyboard="de"),
        bootloader=BootloaderConfig(theme="uli-lenovo"),
        confirmed=True,
    )


def test_apt_preflight_runs_before_storage_and_blocks_wipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []

    monkeypatch.setattr(job, "_writable_cache_root", lambda: tmp_path)
    monkeypatch.setattr(job, "default_state_path", lambda: tmp_path / "state.json")
    monkeypatch.setattr(
        job,
        "verify_plan_sources",
        lambda selections, cache, progress=None: [cache / "debian-trixie-InRelease"],
    )
    monkeypatch.setattr(job, "validate_uefi_environment", lambda dry_run=False: None)
    monkeypatch.setattr(job, "_preflight_installation", lambda plan, dry_run=False: None)

    def fake_preflight(plan, work_dir, *, dry_run, runner=None, log=None):
        order.append("apt")
        if log:
            log("apt preflight simulated failure")
        raise AptPreflightError("simulated unresolved package")

    def boom_apply(self, plan):
        order.append("storage")
        raise AssertionError("StorageGuard must not run after apt preflight failure")

    monkeypatch.setattr(job, "run_apt_preflight", fake_preflight)
    monkeypatch.setattr(StorageGuard, "apply_plan", boom_apply)

    started = job.start_install(_plan(), dry_run=False)
    assert started["status"] == "running"
    thread = job._job._thread
    assert thread is not None
    thread.join(timeout=5)
    status = job.get_job()
    assert status["status"] == "error"
    assert "simulated unresolved package" in status["error"]
    assert order == ["apt"]
    log_path = Path(status["artifact_dir"]) / "install.log"
    assert log_path.is_file()
    assert stat.S_IMODE(log_path.stat().st_mode) == 0o600
    text = log_path.read_text(encoding="utf-8")
    assert PASSWORD_HASH not in text
    assert SSH_TEST_KEY not in text
    assert job.get_install_log_path() == log_path.resolve()


def test_install_log_keeps_full_history_beyond_memory_window(tmp_path: Path) -> None:
    log_path = tmp_path / "install.log"
    log_path.write_text("", encoding="utf-8")
    log_path.chmod(0o600)
    with job._lock:
        job._job = job.InstallJob()
        job._job._secret_needles = (PASSWORD_HASH, SSH_TEST_KEY)
        job._job.artifact_dir = str(tmp_path)
        job._job._log_path = str(log_path)

    job._log(f"start {PASSWORD_HASH}")
    for index in range(520):
        job._log(f"line-{index}")
    job._log(f"end {SSH_TEST_KEY}")

    status = job.get_job()
    assert len(status["log"]) == 80
    with job._lock:
        assert len(job._job.log) == 500
        assert job._job.log[0].startswith("line-")
        assert "end <redacted>" in job._job.log[-1]
    assert "end <redacted>" in status["log"][-1]
    file_text = log_path.read_text(encoding="utf-8")
    assert "start <redacted>" in file_text
    assert "line-0\n" in file_text
    assert "line-519\n" in file_text
    assert "end <redacted>" in file_text
    assert PASSWORD_HASH not in file_text
    assert SSH_TEST_KEY not in file_text
    assert len(file_text.splitlines()) >= 522


def test_install_log_download_endpoint(tmp_path: Path) -> None:
    client = TestClient(create_app(dry_run=True, simulate_disk=True))
    token = client.get("/api/health").json()["csrf_token"]
    client.headers.update({"X-ULI-CSRF": token})

    missing = client.get("/api/install/log")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "install_log_unavailable"

    log_path = tmp_path / "install.log"
    log_path.write_text("", encoding="utf-8")
    log_path.chmod(0o600)
    with job._lock:
        job._job = job.InstallJob()
        job._job.artifact_dir = str(tmp_path)
        job._job._log_path = str(log_path)
        job._job._secret_needles = (PASSWORD_HASH, SSH_TEST_KEY)

    job._log("failure marker")
    job._log(f"secret={PASSWORD_HASH}")
    job._log(f"key={SSH_TEST_KEY}")
    expected = log_path.read_text(encoding="utf-8")
    assert PASSWORD_HASH not in expected
    assert SSH_TEST_KEY not in expected
    assert "<redacted>" in expected

    response = client.get("/api/install/log")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "no-store" in response.headers.get("cache-control", "")
    content_disposition = response.headers.get("content-disposition", "")
    assert "install.log" in content_disposition
    assert response.text == expected
    assert PASSWORD_HASH not in response.text
    assert SSH_TEST_KEY not in response.text


def test_stale_worker_cleanup_does_not_disable_successor_redaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Old worker must not clear secrets after a successor job has started."""

    plan1 = _plan(password_hash=PASSWORD_HASH, ssh_keys=[SSH_TEST_KEY])
    plan2 = _plan(password_hash=PASSWORD_HASH_2, ssh_keys=[SSH_TEST_KEY_2])
    between_done_and_cleanup = threading.Event()
    release_cleanup = threading.Event()
    job2_running = threading.Event()
    release_job2 = threading.Event()
    terminal_count = 0
    original_set = job._set

    def gated_set(**values: object) -> None:
        nonlocal terminal_count
        original_set(**values)
        if values.get("status") in {"done", "error"}:
            terminal_count += 1
            if terminal_count == 1:
                between_done_and_cleanup.set()
                assert release_cleanup.wait(timeout=5), "stale cleanup was not released"

    def fake_run(plan: InstallationPlan, *, dry_run: bool = False):
        del dry_run
        if plan.plan_id == plan2.plan_id:
            job2_running.set()
            assert release_job2.wait(timeout=5), "second job was not released"
        state = InstallState(plan_id=plan.plan_id, status="validated")
        path = tmp_path / f"{plan.plan_id}-state.json"
        state.save(path)
        return state, path

    monkeypatch.setattr(job, "_set", gated_set)
    monkeypatch.setattr(job, "_run", fake_run)

    started1 = job.start_install(plan1, dry_run=True)
    assert started1["status"] == "running"
    thread1 = job._job._thread
    assert thread1 is not None
    assert between_done_and_cleanup.wait(timeout=5), "job1 never reached terminal status"
    assert job.get_job()["status"] == "done"

    started2 = job.start_install(plan2, dry_run=True)
    assert started2["status"] == "running"
    assert job2_running.wait(timeout=5), "job2 never entered _run"
    with job._lock:
        assert job._job._secret_needles == (PASSWORD_HASH_2, SSH_TEST_KEY_2)

    release_cleanup.set()
    thread1.join(timeout=5)
    assert not thread1.is_alive()

    with job._lock:
        assert job._job.status == "running"
        assert job._job._secret_needles == (PASSWORD_HASH_2, SSH_TEST_KEY_2)

    job._log(f"diag hash={PASSWORD_HASH_2} key={SSH_TEST_KEY_2}")
    status = job.get_job()
    joined = "\n".join(status["log"])
    assert PASSWORD_HASH_2 not in joined
    assert SSH_TEST_KEY_2 not in joined
    assert "diag hash=<redacted> key=<redacted>" in joined

    release_job2.set()
    thread2 = job._job._thread
    assert thread2 is not None
    thread2.join(timeout=5)
    assert not thread2.is_alive()
    assert job.get_job()["status"] == "done"
