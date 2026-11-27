"""Desktop master-key persistence helpers."""

from __future__ import annotations

from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from hiro_commons.keys import (
    generate_private_key,
    load_private_key_pem,
    private_key_to_pem,
)

from .workspace_layout import master_key_path, move_credentials

__all__ = [
    "load_or_create_master_key",
]

def load_or_create_master_key(workspace_path: Path) -> Ed25519PrivateKey:
    """Load the workspace's master key (``credentials/master_key.pem``) or create one if absent. An older workspace's
    key on the root is moved there first: a new key would mean pairing every device again."""
    move_credentials(workspace_path)
    key_path = master_key_path(workspace_path)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if key_path.exists():
        return load_private_key_pem(key_path.read_bytes())

    private_key = generate_private_key()
    key_path.write_bytes(private_key_to_pem(private_key))
    try:
        key_path.chmod(0o600)
    except OSError:
        # Windows doesn't fully support POSIX perms via chmod.
        pass
    return private_key
