"""Settings loaded from environment variables, optionally from a .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .client import DEFAULT_API_VERSION, DEFAULT_HOST

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


def update_env_value(key: str, value: str, path: Path = DEFAULT_ENV_FILE) -> None:
    """Replace (or add) KEY=value in the .env file, keeping every other line."""
    lines = path.read_text().splitlines() if path.exists() else []
    for i, raw in enumerate(lines):
        if raw.split("=", 1)[0].strip() == key:
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n")


def _get(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


@dataclass
class Settings:
    access_token: str | None
    ig_user_id: str | None
    api_version: str = DEFAULT_API_VERSION
    host: str = DEFAULT_HOST
    # S3-compatible hosting (Cloudflare R2, AWS S3, Backblaze B2, ...)
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_region: str | None = None
    s3_prefix: str = "instagram/"
    public_base_url: str | None = None

    @classmethod
    def from_env(cls, env_file: Path | None = DEFAULT_ENV_FILE) -> "Settings":
        if env_file is not None:
            load_env_file(env_file)
        return cls(
            access_token=_get("IG_ACCESS_TOKEN"),
            ig_user_id=_get("IG_USER_ID"),
            api_version=_get("IG_API_VERSION") or DEFAULT_API_VERSION,
            host=_get("IG_API_HOST") or DEFAULT_HOST,
            s3_bucket=_get("S3_BUCKET"),
            s3_endpoint_url=_get("S3_ENDPOINT_URL"),
            s3_access_key_id=_get("S3_ACCESS_KEY_ID"),
            s3_secret_access_key=_get("S3_SECRET_ACCESS_KEY"),
            s3_region=_get("S3_REGION"),
            s3_prefix=_get("S3_PREFIX") or "instagram/",
            public_base_url=_get("PUBLIC_BASE_URL"),
        )

    @property
    def hosting_configured(self) -> bool:
        return bool(self.s3_bucket and self.public_base_url)

    def require_api(self) -> None:
        missing = [n for n, v in (("IG_ACCESS_TOKEN", self.access_token),
                                  ("IG_USER_ID", self.ig_user_id)) if not v]
        if missing:
            raise SystemExit(f"Missing {', '.join(missing)} — copy .env.example to .env and fill it in.")
