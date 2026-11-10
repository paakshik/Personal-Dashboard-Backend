import base64
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import SECRET_KEY, TODOIST_TOKEN_ENCRYPTION_KEY


def derive_key(secret_key: str) -> bytes:
    """Derive a 32-byte encryption key from the given secret using HKDF-SHA256."""
    kdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"todoist-credential-encryption",
    )
    return kdf.derive(secret_key.encode("utf-8"))


# Resolve the encryption key: prefer TODOIST_TOKEN_ENCRYPTION_KEY when configured,
# otherwise fall back to SECRET_KEY (preserves existing encrypted tokens). The key
# is derived once at import time and never regenerated at startup.
_ENCRYPTION_SOURCE = TODOIST_TOKEN_ENCRYPTION_KEY or SECRET_KEY
_KEY = derive_key(_ENCRYPTION_SOURCE)


def encrypt(plaintext: str) -> dict:
    """Encrypt a plaintext string using AES-256-GCM.

    Returns a dict with base64-encoded nonce, ciphertext, and tag.
    """
    aesgcm = AESGCM(_KEY)
    nonce = os.urandom(12)  # 96-bit nonce, recommended for GCM
    ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    # AESGCM appends the 16-byte tag to the ciphertext; split them out.
    ciphertext = ciphertext_with_tag[:-16]
    tag = ciphertext_with_tag[-16:]
    return {
        "nonce": base64.b64encode(nonce).decode("utf-8"),
        "ciphertext": base64.b64encode(ciphertext).decode("utf-8"),
        "tag": base64.b64encode(tag).decode("utf-8"),
    }


def decrypt(encrypted_dict: dict) -> str:
    """Decrypt a dict produced by :func:`encrypt` back to the plaintext string."""
    aesgcm = AESGCM(_KEY)
    nonce = base64.b64decode(encrypted_dict["nonce"])
    ciphertext = base64.b64decode(encrypted_dict["ciphertext"])
    tag = base64.b64decode(encrypted_dict["tag"])
    # AESGCM expects ciphertext || tag concatenated.
    combined = ciphertext + tag
    plaintext = aesgcm.decrypt(nonce, combined, None)
    return plaintext.decode("utf-8")
