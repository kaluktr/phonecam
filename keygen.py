"""
keygen.py
=========

Herramienta de administración para generar licencias PRO de PhoneCam.

Uso:
    python keygen.py                # genera el par de claves y una licencia de ejemplo
    python keygen.py email@x.com    # genera una licencia para un email concreto

Salida:
    PUBLIC_KEY_HEX  -> cópiala en licensing.py
    LICENSE_KEY     -> envíala al cliente que haya pagado 1 USD

Requiere: pip install cryptography
"""

import base64
import json
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def main():
    email = sys.argv[1] if len(sys.argv) > 1 else "cliente@example.com"

    # Generar el par de claves (en producción guarda la privada en un lugar seguro).
    private = Ed25519PrivateKey.generate()
    public = private.public_key()

    public_raw = public.public_bytes(
        encoding=__import__("cryptography").hazmat.primitives.serialization.Encoding.Raw,
        format=__import__("cryptography").hazmat.primitives.serialization.PublicFormat.Raw,
    )
    print("=" * 60)
    print("Pega este valor en licensing.py (variable PUBLIC_KEY_HEX):")
    print("=" * 60)
    print(public_raw.hex())
    print()

    # Crear el payload y firmarlo.
    payload = json.dumps({"email": email, "plan": "pro"}, separators=(",", ":"))
    payload_b64 = _b64encode(payload.encode("utf-8"))
    signature = private.sign(payload_b64.encode("utf-8"))
    key = f"{payload_b64}.{_b64encode(signature)}"

    print("=" * 60)
    print(f"Licencia PRO para {email}:")
    print("=" * 60)
    print(key)
    print()


if __name__ == "__main__":
    main()
