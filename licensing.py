"""
licensing.py
============

Sistema de licencias PRO de PhoneCam (pago único de 1 USD).

La licencia es una clave firmada con Ed25519:
    clave = base64url(payload) + "." + base64url(firma)

Solo la CLAVE PÚBLICA se incluye en la aplicación; la clave privada queda en el
equipo del desarrollador (ver keygen.py). Así, solo tú puedes emitir licencias
válidas. La verificación es 100 % offline (no necesita servidor).

Para activar el modo PRO:
    1. Ejecuta `python keygen.py` para generar el par de claves.
    2. Copia el valor de PUBLIC_KEY_HEX en este archivo.
    3. Genera licencias con `python keygen.py <email>`.

Requisito extra: `pip install cryptography`.
"""

import base64
import json
from pathlib import Path

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    _HAS_CRYPTO = True
except Exception:  # pragma: no cover
    _HAS_CRYPTO = False

# Pegar aquí la clave pública generada con keygen.py (en hexadecimal).
# Mientras esté vacía, el programa funciona en modo TRIAL.
PUBLIC_KEY_HEX = ""

# Archivo donde se guarda la licencia activada.
_LICENSE_FILE = Path(__file__).with_name("license.json")


def _b64decode(data):
    """Decodifica base64url tolerando la falta de padding."""
    data += "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data)


def _public_key():
    if not _HAS_CRYPTO or not PUBLIC_KEY_HEX:
        return None
    try:
        return Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY_HEX))
    except Exception:
        return None


def validate_key(key):
    """
    Verifica una clave de licencia.

    Devuelve el payload (dict con 'email', 'plan', etc.) si es válida,
    o None si es inválida / malformada.
    """
    pub = _public_key()
    if pub is None:
        return None
    try:
        payload_b64, sig_b64 = key.strip().split(".")
        payload = json.loads(_b64decode(payload_b64).decode("utf-8"))
        signature = _b64decode(sig_b64)
        # La firma se calcula sobre la representación base64url del payload.
        pub.verify(signature, payload_b64.encode("utf-8"))
        return payload
    except Exception:
        return None


def activate(key):
    """
    Activa una clave si es válida y corresponde al plan PRO.

    Devuelve True si se activó correctamente, False en caso contrario.
    """
    payload = validate_key(key)
    if not payload or payload.get("plan") != "pro":
        return False
    _LICENSE_FILE.write_text(json.dumps({"key": key, "payload": payload}),
                             encoding="utf-8")
    return True


def is_pro():
    """Devuelve True si hay una licencia PRO válida activada."""
    try:
        data = json.loads(_LICENSE_FILE.read_text(encoding="utf-8"))
        payload = validate_key(data.get("key", ""))
        return bool(payload and payload.get("plan") == "pro")
    except Exception:
        return False


def licensed_email():
    """Email asociado a la licencia activada (o None)."""
    try:
        data = json.loads(_LICENSE_FILE.read_text(encoding="utf-8"))
        payload = validate_key(data.get("key", ""))
        return payload.get("email") if payload else None
    except Exception:
        return None
