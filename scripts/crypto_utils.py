"""
Shared cryptographic utilities for the Teemox License Server.

Ed25519 signing/verification, base64url helpers, canonical payload construction,
and full license creation/parsing logic used by all server-side scripts.
"""
from __future__ import annotations

import base64
import json
import os
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
    load_pem_public_key,
    load_der_private_key,
)
from cryptography.exceptions import InvalidSignature

# ── Constants ─────────────────────────────────────────────────────────────────
LICENSE_VERSION   = 4
MAX_MACHINES      = 10        # raised from 6 to 10
MIN_SYNC_MINUTES  = 30
MAX_GRACE_HOURS   = 720   # 30 days

APP_NAMES = frozenset({
    "TEEMOX_MAILER", "INFOMANIAK_API", "SHOPIFY_API",
    "ZOHO_CALENDAR", "ZOHO_INVOICE", "HIGHTAIL_MAILER"
})

# Each app has its own private key secret in GitHub Actions
APP_SECRET_NAME = {
    "TEEMOX_MAILER":    "TEEMOX_MAILER_PRIVATE_KEY",
    "INFOMANIAK_API":   "INFOMANIAK_API_PRIVATE_KEY",
    "SHOPIFY_API":      "SHOPIFY_API_PRIVATE_KEY",
    "ZOHO_CALENDAR":    "ZOHO_CALENDAR_PRIVATE_KEY",
    "ZOHO_INVOICE":     "ZOHO_INVOICE_PRIVATE_KEY",
    "HIGHTAIL_MAILER":  "HIGHTAIL_MAILER_PRIVATE_KEY",
}

APP_PREFIX = {
    "TEEMOX_MAILER":    "TMX",
    "INFOMANIAK_API":   "INF",
    "SHOPIFY_API":      "SHO",
    "ZOHO_CALENDAR":    "ZOH",
    "ZOHO_INVOICE":     "ZOH",
    "HIGHTAIL_MAILER":  "HIG",
}


# ── Base64url helpers ─────────────────────────────────────────────────────────

def b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64u_decode(s: str) -> bytes:
    pad = 4 - len(s) % 4
    if pad != 4:
        s += "=" * pad
    return base64.urlsafe_b64decode(s)


# ── Keypair management ────────────────────────────────────────────────────────

def generate_keypair() -> tuple[str, str]:
    """Generate an Ed25519 keypair.  Returns (private_pem, public_pem)."""
    private_key = Ed25519PrivateKey.generate()
    priv_pem = private_key.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    ).decode()
    pub_pem = private_key.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return priv_pem, pub_pem


def load_private_key(pem: str) -> Ed25519PrivateKey:
    """Load an Ed25519 private key from a PEM string.

    Tolerates all common GitHub Actions secret storage formats:
    - Proper multi-line PEM
    - Literal \\n escape sequences
    - No newlines at all (single-line concatenation)
    """
    import re
    # Normalise literal \n escape sequences
    pem = pem.replace("\\n", "\n").strip()
    # Extract the raw base64 payload between any PEM headers and decode to DER.
    # This bypasses all PEM framing issues entirely.
    b64 = re.sub(r"-----[^-]+-----", "", pem).replace("\n", "").replace("\r", "").strip()
    if b64:
        import base64 as _b64
        try:
            der = _b64.b64decode(b64)
            return load_der_private_key(der, password=None)
        except Exception:
            pass  # fall through to PEM load as last resort
    return load_pem_private_key(pem.encode(), password=None)


# ── Canonical signing payload ─────────────────────────────────────────────────

def canonical_v4(
    license_id: str,
    app: str,
    display: str,
    expiry: str,
    created: str,
    sync_interval: int,
    machines: list[str],
    max_machines: int,
    grace_hours: int,
) -> bytes:
    """Deterministic bytes that are signed/verified.  Any change breaks the sig."""
    machines_str = ",".join(sorted(machines))
    return (
        f"{license_id}|{app}|{display}|{expiry}|{created}"
        f"|{sync_interval}|{machines_str}|{max_machines}|{grace_hours}"
    ).encode("utf-8")


# ── License creation ──────────────────────────────────────────────────────────

def create_license(
    private_pem: str,
    app: str,
    display: str,
    expiry: str                   = "never",
    machines: Optional[list[str]] = None,
    max_machines: int             = 1,
    sync_interval: int            = 90,
    grace_hours: int              = 24,
    notes: str                    = "",
    created: Optional[str]        = None,
    license_id: Optional[str]     = None,
) -> tuple[str, dict]:
    """
    Create a signed v4 license key.

    Returns (key_string, metadata_dict).
    The key has format:  TMXLIC.{base64url_payload}.{base64url_signature}
    """
    if app not in APP_NAMES:
        raise ValueError(f"Unknown app '{app}'. Valid: {sorted(APP_NAMES)}")

    license_id    = license_id or uuid.uuid4().hex
    created       = created or date.today().isoformat()
    sync_interval = max(MIN_SYNC_MINUTES, int(sync_interval))
    grace_hours   = max(1, min(MAX_GRACE_HOURS, int(grace_hours)))
    max_machines  = max(1, min(MAX_MACHINES, int(max_machines)))
    machines      = list(machines) if machines else ["*"]

    payload = {
        "v":   LICENSE_VERSION,
        "id":  license_id,
        "app": app,
        "d":   display,
        "e":   expiry,
        "c":   created,
        "si":  sync_interval,
        "m":   sorted(machines),
        "n":   max_machines,
        "g":   grace_hours,
    }
    if notes:
        payload["notes"] = notes

    canonical = canonical_v4(
        license_id, app, display, expiry, created,
        sync_interval, machines, max_machines, grace_hours,
    )

    priv = load_private_key(private_pem)
    sig  = priv.sign(canonical)

    payload_b64 = b64u_encode(json.dumps(payload, separators=(",", ":")).encode())
    sig_b64     = b64u_encode(sig)
    key         = f"TMXLIC.{payload_b64}.{sig_b64}"

    metadata = {
        **payload,
        "key":        key,
        "notes":      notes,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "history":    [],
        "status":     "active",
    }
    return key, metadata


def update_license(
    private_pem: str,
    existing_meta: dict,
    *,
    machines: Optional[list[str]] = None,
    expiry: Optional[str]         = None,
    max_machines: Optional[int]   = None,
    sync_interval: Optional[int]  = None,
    grace_hours: Optional[int]    = None,
    notes: Optional[str]          = None,
) -> tuple[str, dict]:
    """
    Re-issue a license with updated parameters.
    Preserves the license_id; returns a new key (old key becomes invalid).
    """
    old_key = existing_meta.get("key", "")

    new_key, new_meta = create_license(
        private_pem   = private_pem,
        app           = existing_meta["app"],
        display       = existing_meta["d"],
        expiry        = expiry        if expiry        is not None else existing_meta["e"],
        machines      = machines      if machines      is not None else existing_meta["m"],
        max_machines  = max_machines  if max_machines  is not None else existing_meta["n"],
        sync_interval = sync_interval if sync_interval is not None else existing_meta["si"],
        grace_hours   = grace_hours   if grace_hours   is not None else existing_meta["g"],
        notes         = notes         if notes         is not None else existing_meta.get("notes", ""),
        created       = existing_meta["c"],
        license_id    = existing_meta["id"],   # keep same ID
    )

    # Carry over history
    history = list(existing_meta.get("history", []))
    history.append({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "old_key_prefix": old_key[:24] if old_key else "",
        "reason": "license_updated",
    })
    new_meta["history"] = history
    return new_key, new_meta


def verify_license(public_pem: str, key_str: str) -> dict:
    """
    Verify a license key offline (signature + structure only, no revocation check).
    Returns the parsed payload dict on success, raises ValueError on failure.
    """
    key_str = key_str.strip()
    if not key_str.startswith("TMXLIC."):
        raise ValueError("Not a v4 license key (expected 'TMXLIC.' prefix).")

    parts = key_str.split(".")
    if len(parts) != 3:
        raise ValueError("Malformed license key (expected TMXLIC.payload.sig).")

    try:
        payload_bytes = b64u_decode(parts[1])
        sig_bytes     = b64u_decode(parts[2])
        p = json.loads(payload_bytes)
    except Exception as exc:
        raise ValueError(f"Cannot decode license key: {exc}") from exc

    if p.get("v") != LICENSE_VERSION:
        raise ValueError(f"Unsupported license version {p.get('v')} (expected {LICENSE_VERSION}).")

    canonical = canonical_v4(
        p["id"], p["app"], p["d"], p["e"], p["c"],
        p["si"], p["m"], p["n"], p["g"],
    )
    try:
        pub = load_pem_public_key(public_pem.encode())
        pub.verify(sig_bytes, canonical)
    except InvalidSignature:
        raise ValueError("License signature invalid — key has been tampered with.")
    except Exception as exc:
        raise ValueError(f"Signature verification failed: {exc}") from exc

    return p