from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient
from uli.security.secrets import validate_ssh_public_key
from uli.web.server import create_app, run_server


def _client() -> TestClient:
    client = TestClient(create_app(dry_run=True, simulate_disk=True))
    token = client.get("/api/health").json()["csrf_token"]
    client.headers.update({"X-ULI-CSRF": token})
    return client


def test_mutating_api_requires_csrf_and_local_origin() -> None:
    client = TestClient(create_app(dry_run=True, simulate_disk=True))
    assert client.post("/api/state", json={"mode": "simple"}).status_code == 403

    token = client.get("/api/health").json()["csrf_token"]
    response = client.post(
        "/api/state",
        json={"mode": "simple"},
        headers={"X-ULI-CSRF": token, "Origin": "https://attacker.example"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "cross_site_request_blocked"

    malformed = client.post(
        "/api/state",
        json={"mode": "simple"},
        headers={"X-ULI-CSRF": token, "Origin": "http://[broken"},
    )
    assert malformed.status_code == 403
    untrusted_host = client.get("/api/health", headers={"Host": "attacker.example"})
    assert untrusted_host.status_code == 400


def _valid_state() -> dict[str, object]:
    return {
        "mode": "simple",
        "selected": [{"id": "ubuntu", "variant": "server"}],
        "username": "uliuser",
        "password": "a-reasonable-password",
        "timezone": "Europe/Berlin",
        "keyboard": "de",
        "language": "de",
        "hostnames": {"ubuntu:server": "ubuntu-server"},
        "ssh_keys": [],
        "install_ssh_server": True,
        "disable_password_auth": False,
        "theme": "uli-lenovo",
        "boot_timeout_seconds": 5,
        "boot_default": "ubuntu:server",
        "partition_strategy": "equal",
        "root_sizes_mib": {"ubuntu:server": 65_536},
        "include_swap": True,
        "swap_size_mib": 8192,
        "include_data": True,
        "data_size_mib": 65_536,
        "disk_id": "sim-nvme-512",
    }


def test_state_rejects_device_fields_and_never_returns_password() -> None:
    client = _client()
    assert client.post("/api/state", json={"disk_path": "/dev/sda"}).status_code == 422

    response = client.post("/api/state", json=_valid_state())
    assert response.status_code == 200
    state = response.json()
    assert state["has_password"] is True
    assert "password" not in state
    assert "password_hash" not in state
    assert "a-reasonable-password" not in response.text

    public = client.get("/api/state").json()
    assert "password" not in public
    assert "password_hash" not in public


def test_state_rejects_short_password_with_structured_validation_error() -> None:
    client = _client()
    response = client.post("/api/state", json={"password": "short"})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert detail[0]["loc"] == ["body", "password"]
    assert detail[0]["type"] == "too_short"
    assert detail[0]["ctx"]["min_length"] == 8


@pytest.mark.parametrize(
    "username",
    (
        "root",
        "daemon",
        "bin",
        "sys",
        "sync",
        "games",
        "man",
        "lp",
        "mail",
        "news",
        "uucp",
        "proxy",
        "www-data",
        "backup",
        "list",
        "irc",
        "_apt",
        "nobody",
        "systemd-network",
        "systemd-timesync",
        "messagebus",
        "polkitd",
        "sssd",
        "gnome-remote-desktop",
        "kernoops",
    ),
)
def test_state_rejects_reserved_system_usernames_before_preview(username: str) -> None:
    client = _client()
    response = client.post("/api/state", json={"username": username})

    assert response.status_code == 400
    assert response.json()["detail"] == "reserved_username"
    assert client.get("/api/state").json()["username"] == ""


def test_state_supports_utc_but_rejects_special_or_traversing_timezones() -> None:
    client = _client()
    assert client.post("/api/state", json={"timezone": "UTC"}).status_code == 200

    for timezone in ("posix/Europe/Berlin", "right/Europe/Berlin", "Europe/../Etc/UTC"):
        response = client.post("/api/state", json={"timezone": timezone})
        assert response.status_code == 400
        assert response.json()["detail"] == "invalid_timezone"


def test_catalog_disables_unreleased_distributions_and_modes() -> None:
    client = _client()
    catalog = client.get("/api/catalog", params={"mode": "simple"}).json()["items"]
    enabled = {(item["id"], item["variant"]) for item in catalog if item["enabled"]}
    assert enabled == {
        ("debian", "desktop"),
        ("debian", "server"),
        ("ubuntu", "desktop"),
        ("ubuntu", "server"),
    }
    remove = client.get("/api/catalog", params={"mode": "remove"}).json()["items"]
    assert remove and not any(item["enabled"] for item in remove)


def test_preview_is_stable_and_confirmation_is_bound_to_revision() -> None:
    client = _client()
    assert client.post("/api/state", json=_valid_state()).status_code == 200

    first = client.get("/api/storage/preview", params={"disk_id": "sim-nvme-512"}).json()
    second = client.get("/api/storage/preview", params={"disk_id": "sim-nvme-512"}).json()
    assert first["plan_fingerprint"] == second["plan_fingerprint"]
    fingerprint = first["plan_fingerprint"]

    confirmation = client.post(
        "/api/install/confirm",
        json={
            "disk_id": "sim-nvme-512",
            "plan_fingerprint": fingerprint,
            "acknowledged": True,
        },
    )
    assert confirmation.status_code == 200
    token = confirmation.json()["confirmation_token"]

    token2 = client.post(
        "/api/install/confirm",
        json={
            "disk_id": "sim-nvme-512",
            "plan_fingerprint": fingerprint,
            "acknowledged": True,
        },
    ).json()["confirmation_token"]
    assert client.post("/api/state", json={"boot_timeout_seconds": 9}).status_code == 200
    start = client.post("/api/install/start", json={"confirmation_token": token})
    assert start.status_code == 409
    assert start.json()["detail"] == "invalid_or_used_confirmation"
    changed = client.post("/api/install/start", json={"confirmation_token": token2})
    assert changed.status_code == 409
    assert changed.json()["detail"] == "invalid_or_used_confirmation"


def test_full_dry_run_job_completes_honestly(monkeypatch, tmp_path) -> None:
    from uli.install import job

    monkeypatch.setattr(
        job,
        "verify_plan_sources",
        lambda _selections, cache, progress=None: [cache / "verified-InRelease"],
    )
    monkeypatch.setattr(job, "_writable_cache_root", lambda: tmp_path)
    monkeypatch.setattr(job, "default_state_path", lambda: tmp_path / "state.json")
    client = _client()
    assert client.post("/api/state", json=_valid_state()).status_code == 200
    preview = client.get(
        "/api/storage/preview", params={"disk_id": "sim-nvme-512"}
    ).json()
    confirmation = client.post(
        "/api/install/confirm",
        json={
            "disk_id": "sim-nvme-512",
            "plan_fingerprint": preview["plan_fingerprint"],
            "acknowledged": True,
        },
    ).json()

    response = client.post(
        "/api/install/start",
        json={"confirmation_token": confirmation["confirmation_token"]},
    )
    assert response.status_code == 200
    thread = job._job._thread
    assert thread is not None
    thread.join(timeout=5)
    result = client.get("/api/install/status").json()
    assert result["status"] == "done"
    assert result["completed"] == ["ubuntu:server"]
    assert result["dry_run"] is True
    assert result["installation_complete"] is False

    state = client.get("/api/state").json()
    assert state["has_password"] is False
    assert "password_hash" not in state
    combined = "\n".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.json"))
    assert "a-reasonable-password" not in combined
    assert '"password_hash": null' in combined


def test_state_rejects_unsupported_selection_and_unsafe_ssh_policy() -> None:
    client = _client()
    unsupported = _valid_state()
    unsupported["selected"] = [{"id": "fedora", "variant": "server"}]
    response = client.post("/api/state", json=unsupported)
    assert response.status_code == 409

    unsafe = _valid_state()
    unsafe["disable_password_auth"] = True
    response = client.post("/api/state", json=unsafe)
    assert response.status_code == 400
    assert "ssh_key_required" in response.json()["detail"]


def test_simulated_disk_requires_dry_run() -> None:
    try:
        create_app(dry_run=False, simulate_disk=True)
    except ValueError as exc:
        assert "dry-run" in str(exc)
    else:
        raise AssertionError("simulated disks must never be executable")


def test_real_server_refuses_non_loopback_bind() -> None:
    with pytest.raises(ValueError, match="127.0.0.1"):
        run_server(host="0.0.0.0", dry_run=False)


def test_ssh_key_validation_checks_embedded_algorithm() -> None:
    algorithm = b"ssh-ed25519"
    blob = len(algorithm).to_bytes(4, "big") + algorithm + (32).to_bytes(4, "big") + b"x" * 32
    valid = "ssh-ed25519 " + base64.b64encode(blob).decode() + " test@example"
    assert validate_ssh_public_key(valid) == valid

    mismatched = "ssh-rsa " + base64.b64encode(blob).decode()
    try:
        validate_ssh_public_key(mismatched)
    except ValueError:
        pass
    else:
        raise AssertionError("outer and embedded SSH algorithms must match")
