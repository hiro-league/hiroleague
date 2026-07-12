"""Standard filenames and directory names shared across all Hiro packages."""

from __future__ import annotations

REGISTRY_FILENAME: str = "registry.json"
CONFIG_FILENAME: str = "config.json"
LOGS_DIR: str = "logs"
# Ephemeral runtime/process state (pids, session, connection state) lives together
# under <workspace>/run/ rather than scattered across the workspace root.
RUN_DIR: str = "run"
PAIRING_SESSION_FILENAME: str = "pairing_session.json"
MASTER_KEY_FILENAME: str = "master_key.pem"
WORKSPACE_DB_FILENAME: str = "workspace.db"
PREFERENCES_FILENAME: str = "preferences.json"
PROVIDERS_FILENAME: str = "providers.json"

# All databases live together under <workspace>/db/ to keep the workspace root clean:
# workspace.db, data.db, knowledge.db, eval_results.db, the Kuzu graph (graphiti_kuzu.db)
# and the Qdrant vector store. Content blobs (data/media, data/channel_photos) and
# regenerable caches (knowledge/fastembed_cache) deliberately stay outside this folder.
DB_DIR: str = "db"

DATA_DIR: str = "data"
DATA_DB_FILENAME: str = "data.db"
MEDIA_DIR: str = "media"
# Conversation channel thumbnails (workspace `data/channel_photos/<id>/photo_512.webp`)
CHANNEL_PHOTOS_DIR: str = "channel_photos"

# Character entities (workspace-relative `characters/<id>/`; see Hiro domain/character.py)
CHARACTERS_DIR: str = "characters"
DEFAULT_CHARACTER_ID: str = "hiro"
