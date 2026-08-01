from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class I18n:
    """Simple JSON-based translator with German as default."""

    def __init__(self, language: str = "de") -> None:
        self._language = language if language in {"de", "en"} else "de"
        self._strings: dict[str, str] = {}
        self._fallback: dict[str, str] = {}
        self.reload()

    @property
    def language(self) -> str:
        return self._language

    def set_language(self, language: str) -> None:
        if language not in {"de", "en"}:
            raise ValueError(f"Unsupported language: {language}")
        self._language = language
        self.reload()

    def reload(self) -> None:
        base = Path(__file__).resolve().parent
        self._fallback = self._load(base / "de.json")
        self._strings = self._load(base / f"{self._language}.json")

    @staticmethod
    def _load(path: Path) -> dict[str, str]:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()}

    def t(self, key: str, **kwargs: Any) -> str:
        template = self._strings.get(key) or self._fallback.get(key) or key
        if kwargs:
            try:
                return template.format(**kwargs)
            except (KeyError, ValueError):
                return template
        return template


# Module-level helper used by UI code
_translator = I18n("de")


def set_language(language: str) -> None:
    _translator.set_language(language)


def get_language() -> str:
    return _translator.language


def tr(key: str, **kwargs: Any) -> str:
    return _translator.t(key, **kwargs)
