import base64
import binascii
import hashlib
import json
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from adam.mesh.contracts import MeshError


def decode(value: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise MeshError("MESH.INVALID_PACKET") from None


def encode(value: bytes) -> str:
    return base64.b64encode(value).decode()


def public(value: str) -> ec.EllipticCurvePublicKey:
    try:
        key = serialization.load_der_public_key(decode(value))
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
            key.curve, ec.SECP256R1
        ):
            raise ValueError
        return key
    except (ValueError, TypeError):
        raise MeshError("MESH.INVALID_KEY") from None


def export(key: ec.EllipticCurvePrivateKey) -> str:
    return encode(
        key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )


def fingerprint(value: str) -> str:
    key = public(value)
    canonical = key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return hashlib.sha256(canonical).hexdigest()


def verify(key: str, message: bytes, signature: str) -> None:
    raw = decode(signature)
    if len(raw) != 64:
        raise MeshError("MESH.BAD_SIGNATURE")
    der = utils.encode_dss_signature(
        int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")
    )
    try:
        public(key).verify(der, message, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        raise MeshError("MESH.BAD_SIGNATURE") from None


def packet(key: ec.EllipticCurvePrivateKey, body: dict[str, Any]) -> dict[str, str]:
    message = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    r, s = utils.decode_dss_signature(key.sign(message, ec.ECDSA(hashes.SHA256())))
    return {
        "message": encode(message),
        "signature": encode(r.to_bytes(32, "big") + s.to_bytes(32, "big")),
    }
