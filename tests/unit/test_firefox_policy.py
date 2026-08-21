from __future__ import annotations

import json
from pathlib import Path


def test_firefox_kiosk_policy_suppresses_first_run_and_secret_storage() -> None:
    policy_path = Path(__file__).parents[2] / "assets/firefox/policies.json"
    policies = json.loads(policy_path.read_text(encoding="utf-8"))["policies"]

    assert policies["SkipTermsOfUse"] is True
    assert policies["OverrideFirstRunPage"] == ""
    assert policies["OverridePostUpdatePage"] == ""
    assert policies["DontCheckDefaultBrowser"] is True
    assert policies["DisableTelemetry"] is True
    assert policies["OfferToSaveLogins"] is False
    assert policies["PasswordManagerEnabled"] is False
    assert policies["Preferences"]["browser.aboutwelcome.enabled"] == {
        "Value": False,
        "Status": "locked",
    }
