from __future__ import annotations

from pathlib import Path

WEB_APP = Path(__file__).resolve().parents[2] / "app" / "uli" / "web" / "static" / "app.js"


def test_settings_password_validation_matches_the_api_minimum() -> None:
    source = WEB_APP.read_text(encoding="utf-8")

    assert 'minlength="8"' in source
    assert "state.password.length < 8" in source
    assert 't("error.password_too_short")' in source


def test_api_error_formatter_never_coerces_validation_objects_to_object_object() -> None:
    source = WEB_APP.read_text(encoding="utf-8")

    assert "function formatApiError(payload" in source
    assert "item.msg ?? item.message ?? item.type" in source
    assert "formatApiError(payload, response.statusText" in source


def test_ui_defaults_and_disk_too_small_and_log_download() -> None:
    source = WEB_APP.read_text(encoding="utf-8")
    assert "includeData: false" in source
    assert "function previewErrorHtml" in source
    assert "storage.disk_too_small" in source
    assert "/api/install/log" in source
    assert "progress.download_log" in source
