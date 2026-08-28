import secrets, hmac, hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.exceptions import InvalidTag

from config import SALT_BYTES, NONCE_BYTES, KEY_BYTES, PBKDF2_ITERS

def derive_key(passphrase, salt):
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=KEY_BYTES,
                     salt=salt, iterations=PBKDF2_ITERS)
    return kdf.derive(passphrase.encode())

def encrypt_bytes(data, passphrase):
    salt = secrets.token_bytes(SALT_BYTES)
    nonce = secrets.token_bytes(NONCE_BYTES)
    ct = AESGCM(derive_key(passphrase, salt)).encrypt(nonce, data, None)
    return salt + nonce + ct

def decrypt_bytes(data, passphrase):
    if len(data) < SALT_BYTES + NONCE_BYTES + 16:
        return None
    salt, nonce, ct = data[:SALT_BYTES], data[SALT_BYTES:SALT_BYTES+NONCE_BYTES], data[SALT_BYTES+NONCE_BYTES:]
    try:
        return AESGCM(derive_key(passphrase, salt)).decrypt(nonce, ct, None)
    except InvalidTag:
        return None

def pseudonymise(pid, secret):
    return "ANON-" + hmac.new(secret, pid.encode(), hashlib.sha256).hexdigest()[:10].upper()

