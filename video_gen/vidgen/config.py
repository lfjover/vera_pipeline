"""Settings loaded from environment variables, optionally from a .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .comfy import DEFAULT_URL

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"


def load_env_file(path: Path = DEFAULT_ENV_FILE) -> None:
    """Minimal .env reader: KEY=value lines; existing environment variables win."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _get(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


@dataclass
class Settings:
    comfy_url: str = DEFAULT_URL
    comfy_token: str | None = None
    output_dir: Path = PROJECT_ROOT / "output"
    timeout: float = 3600

    @classmethod
    def from_env(cls, env_file: Path | None = DEFAULT_ENV_FILE) -> "Settings":
        if env_file is not None:
            load_env_file(env_file)
        output = _get("VIDGEN_OUTPUT_DIR")
        return cls(
            comfy_url=_get("COMFY_URL") or DEFAULT_URL,
            comfy_token=_get("COMFY_TOKEN"),
            output_dir=(PROJECT_ROOT / output) if output else PROJECT_ROOT / "output",
            timeout=float(_get("VIDGEN_TIMEOUT") or 3600),
        )
