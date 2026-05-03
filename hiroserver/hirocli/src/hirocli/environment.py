"""Runtime environment configuration for Hiro.

The package artifact stays the same across dev and prod; environment variables
select deployment-specific values at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
import os

from .constants import ENV_HIRO_ENV

DOCS_BASE_URL_ENV = "HIRO_DOCS_BASE_URL"

DEV_ENV_VALUES = {"dev", "development", "local"}
PROD_ENV_VALUES = {"prod", "production"}

DEV_DOCS_BASE_URL = "http://localhost:3000"
PROD_DOCS_BASE_URL = "https://docs.hiroleague.com"


@dataclass(frozen=True)
class HiroEnvironmentConfig:
    hiro_env: str
    docs_base_url: str


def current_hiro_env() -> str:
    raw = os.getenv(ENV_HIRO_ENV, "prod").strip().lower()
    if raw in DEV_ENV_VALUES:
        return "dev"
    if raw in PROD_ENV_VALUES or not raw:
        return "prod"
    return raw


def docs_base_url() -> str:
    override = os.getenv(DOCS_BASE_URL_ENV, "").strip()
    if override:
        return override.rstrip("/")
    return DEV_DOCS_BASE_URL if current_hiro_env() == "dev" else PROD_DOCS_BASE_URL


def get_environment_config() -> HiroEnvironmentConfig:
    return HiroEnvironmentConfig(
        hiro_env=current_hiro_env(),
        docs_base_url=docs_base_url(),
    )


def default_workspace_log_level() -> str:
    """Root ``log_level`` for a new workspace before ``config.json`` exists.

    ``HIRO_ENV`` values that normalize to production use ``INFO``; any other
    value (``dev``, ``staging``, etc.) uses ``DEBUG`` for local and non-prod
    diagnostics.
    """
    return "DEBUG" if current_hiro_env() != "prod" else "INFO"
