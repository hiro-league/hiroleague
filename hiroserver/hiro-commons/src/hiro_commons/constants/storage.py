"""Standard filenames and directory names shared across all Hiro packages."""

from __future__ import annotations

REGISTRY_FILENAME: str = "registry.json"
CONFIG_FILENAME: str = "config.json"
LOGS_DIR: str = "logs"
PAIRING_SESSION_FILENAME: str = "pairing_session.json"
MASTER_KEY_FILENAME: str = "master_key.pem"
WORKSPACE_DB_FILENAME: str = "workspace.db"
PREFERENCES_FILENAME: str = "preferences.json"
PROVIDERS_FILENAME: str = "providers.json"

DATA_DIR: str = "data"
DATA_DB_FILENAME: str = "data.db"
MEDIA_DIR: str = "media"

# Character entities (workspace-relative `characters/<id>/`; see Hiro domain/character.py)
CHARACTERS_DIR: str = "characters"
DEFAULT_CHARACTER_ID: str = "hiro"
