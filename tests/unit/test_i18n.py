from __future__ import annotations

from uli.i18n import I18n


def test_german_default_and_english_switch():
    i18n = I18n("de")
    assert "Installationsart" in i18n.t("mode.title")
    i18n.set_language("en")
    assert "installation type" in i18n.t("mode.title").lower()


def test_fallback_to_german_for_missing_key():
    i18n = I18n("en")
    # Unknown keys return the key itself
    assert i18n.t("does.not.exist") == "does.not.exist"
