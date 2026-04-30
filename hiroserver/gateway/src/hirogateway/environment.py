"""Runtime environment configuration for Hiro Gateway."""

from __future__ import annotations

from dataclasses import dataclass
import os

from .constants import ENV_HIRO_ENV

DEV_ENV_VALUES = {"dev", "development", "local"}
PROD_ENV_VALUES = {"prod", "production"}


@dataclass(frozen=True)
class GatewayEnvironmentConfig:
    hiro_env: str

    @property
    def is_dev(self) -> bool:
        return self.hiro_env == "dev"

    @property
    def is_prod(self) -> bool:
        return self.hiro_env == "prod"


def current_hiro_env() -> str:
    raw = os.getenv(ENV_HIRO_ENV, "prod").strip().lower()
    if raw in DEV_ENV_VALUES:
        return "dev"
    if raw in PROD_ENV_VALUES or not raw:
        return "prod"
    return raw


def get_environment_config() -> GatewayEnvironmentConfig:
    return GatewayEnvironmentConfig(hiro_env=current_hiro_env())
