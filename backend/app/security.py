"""Security primitives: password hashing and opaque token handling.

Uses only the Python standard library so there is no native build dependency:
- Passwords are hashed with PBKDF2-HMAC-SHA256 and a per-password random salt.
- Session tokens are random, URL-safe, and stored only as SHA-256 hashes in the
  database (so a DB leak does not expose usable session tokens).

Comparisons use constant-time helpers to avoid timing side channels.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_PBKDF2_ROUNDS = 240_000
_SALT_BYTES = 16
_HASH_NAME = "sha256"
_PREFIX = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    """Return an encoded PBKDF2 hash: ``pbkdf2_sha256$rounds$salt_hex$hash_hex``."""
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(_HASH_NAME, password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return f"{_PREFIX}${_PBKDF2_ROUNDS}${salt.hex()}${derived.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """Verify ``password`` against a previously encoded hash (constant-time)."""
    try:
        prefix, rounds_s, salt_hex, hash_hex = encoded.split("$")
        if prefix != _PREFIX:
            return False
        rounds = int(rounds_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    derived = hashlib.pbkdf2_hmac(_HASH_NAME, password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(derived, expected)


def generate_token() -> str:
    """Return a new high-entropy, URL-safe opaque token (the raw session id)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest used to store/look up a token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    """Constant-time string comparison (e.g. for CSRF tokens)."""
    return hmac.compare_digest(a, b)
