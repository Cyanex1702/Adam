"""Explicit LAN TLS preparation. Never changes OS or Android certificate trust."""

import argparse
import ipaddress
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from adam.mesh.contracts import MeshError
from adam.resilience.archive import scoped
from adam.security.vault import DPAPI, Sealer


def lan_address(value: str) -> ipaddress.IPv4Address:
    address = ipaddress.IPv4Address(value)
    networks = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    if not (address.is_loopback or any(address in ipaddress.IPv4Network(n) for n in networks)):
        raise MeshError("MESH.LAN_ADDRESS_REQUIRED")
    return address


def prepare(root: Path, address: str, port: int = 9443, sealer: Sealer | None = None) -> Path:
    ip = lan_address(address)
    if not 1024 <= port <= 65535:
        raise MeshError("MESH.PORT_INVALID")
    folder = scoped(root, "mesh/tls")
    # Rotating trust requires deliberate removal while the listener is stopped.
    if folder.exists() and any(folder.iterdir()):
        raise MeshError("MESH.TLS_ALREADY_CONFIGURED")
    folder.mkdir(parents=True, exist_ok=True)
    ca_key, server_key = (ec.generate_private_key(ec.SECP256R1()) for _ in range(2))
    now = datetime.now(UTC)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ADAM personal device mesh")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    server = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ADAM LAN core")]))
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.KeyUsage(True, False, False, False, False, False, False, False, False),
            critical=True,
        )
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ip)]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    password = secrets.token_urlsafe(32).encode()
    scoped(root, "mesh/tls/ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    scoped(root, "mesh/tls/ca.crt").write_bytes(ca.public_bytes(serialization.Encoding.DER))
    scoped(root, "mesh/tls/server.pem").write_bytes(server.public_bytes(serialization.Encoding.PEM))
    scoped(root, "mesh/tls/key.pem").write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(password),
        )
    )
    scoped(root, "mesh/tls/password.dpapi").write_bytes((sealer or DPAPI()).seal(password))
    scoped(root, "mesh/network.json").write_text(json.dumps({"address": str(ip), "port": port}))
    # CA private key is never saved; only this one leaf can be issued.
    return scoped(root, "mesh/tls/ca.crt")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--address", required=True)
    parser.add_argument("--port", type=int, default=9443)
    args = parser.parse_args()
    cert = prepare(args.data_dir, args.address, args.port)
    print(f"Prepared TLS. Listener remains OFF. Android CA certificate: {cert}")


if __name__ == "__main__":
    main()
