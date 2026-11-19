import hashlib
import hmac
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from app.core.config import settings

# OWASP-aligned Argon2id parameters for password hashing
_password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=2,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


def keyed_digest(value: str, purpose: str = 'credential', salt: str = '') -> str:
    """Compute a keyed HMAC-SHA256 digest bound to a domain purpose and server secret."""
    secret = settings.effective_hmac_secret.encode('utf-8')
    message = f'{purpose}:{salt}:{value}'.encode('utf-8')
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def digest(value: str, purpose: str = 'credential') -> str:
    """Backward-compatible alias for keyed HMAC-SHA256 digest."""
    return keyed_digest(value, purpose=purpose)


def matches(value: str, stored: str, purpose: str = 'credential', salt: str = '') -> bool:
    return hmac.compare_digest(keyed_digest(value, purpose=purpose, salt=salt), stored)


def hash_password(password: str) -> str:
    if not password or len(password) < 12:
        raise ValueError('Password must be at least 12 characters')
    return _password_hasher.hash(password)


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not password or not stored_hash:
        return False
    try:
        return _password_hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(stored_hash: str) -> bool:
    return _password_hasher.check_needs_rehash(stored_hash)
