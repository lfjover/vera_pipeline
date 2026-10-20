"""Settings from environment variables, optionally loaded from vera_synth_photo/.env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_RUNS_DIR = PROJECT_ROOT / "runs"
DEFAULT_DIRECTION_FILE = PROJECT_ROOT / "direction.txt"


def load_env_file(path: Path | None) -> None:
    """KEY=value lines; variables already set in the shell win."""
    if not path or not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _get(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or default


@dataclass
class Settings:
    fal_key: str | None
    fal_model: str
    kling_api_key: str | None
    kling_access_key: str | None
    kling_secret_key: str | None
    kling_base_url: str
    kling_model: str
    anthropic_api_key: str | None
    anthropic_model: str
    runs_dir: Path

    @classmethod
    def from_env(cls, env_file: Path | None = DEFAULT_ENV_FILE) -> "Settings":
        load_env_file(env_file)
        return cls(
            fal_key=_get("FAL_KEY"),
            fal_model=_get("FAL_MODEL", "fal-ai/kling-image/o3/text-to-image"),
            kling_api_key=_get("KLING_API_KEY"),
            kling_access_key=_get("KLING_ACCESS_KEY"),
            kling_secret_key=_get("KLING_SECRET_KEY"),
            kling_base_url=_get("KLING_API_BASE", "https://api-singapore.klingai.com"),
            kling_model=_get("KLING_IMAGE_MODEL", "kling-v2-1"),
            anthropic_api_key=_get("ANTHROPIC_API_KEY"),
            anthropic_model=_get("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
            runs_dir=Path(_get("VERA_RUNS_DIR", str(DEFAULT_RUNS_DIR))).expanduser(),
        )

    def missing(self) -> list[str]:
        missing = []
        if not (self.fal_key or self.kling_api_key or (self.kling_access_key and self.kling_secret_key)):
            missing.append("FAL_KEY (or KLING_API_KEY)")
        if not self.anthropic_api_key:
            missing.append("ANTHROPIC_API_KEY")
        return missing

    @property
    def image_provider(self) -> str:
        return "fal" if self.fal_key else "kling"

    def image_client(self):
        """fal.ai when FAL_KEY is set (pay as you go), otherwise Kling's own API."""
        if self.fal_key:
            from .fal import FalClient
            return FalClient(self.fal_key, self.fal_model)
        return self.kling_client()

    def kling_client(self):
        from .kling import KlingClient
        return KlingClient(self.kling_access_key, self.kling_secret_key, self.kling_base_url,
                           self.kling_model, api_key=self.kling_api_key)

    def require_keys(self) -> None:
        missing = self.missing()
        if missing:
            raise SystemExit(
                f"Missing {', '.join(missing)} in vera_synth_photo/.env. Paste "
                "your keys there (or add --dry-run to try the pipeline without keys).")
