"""
Teemox License Client SDK — v4
═══════════════════════════════
Validates Ed25519-signed TMXLIC keys and syncs with the GitHub-hosted
revocation list.  Copy this file into each of the three apps and set the
constants below to match the app.

Per-app customisation (change these 2 lines per deployment):
    APP_NAME     = "TEEMOX_MAILER"   # "INFOMANIAK_API" | "SHOPIFY_API"
    APP_DIR_NAME = "TeemoxMailer"    # subdirectory in %APPDATA%

After running scripts/setup_keypair.py, the PUBLIC_KEY_PEM placeholder
will be replaced automatically.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import socket
import sys
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.serialization import load_pem_public_key

# ── Per-app constants (edit per deployment) ────────────────────────────────────
APP_NAME     = "TEEMOX_MAILER"   # TEEMOX_MAILER | INFOMANIAK_API | SHOPIFY_API
APP_DIR_NAME = "TeemoxMailer"    # %APPDATA% subdirectory name

GITHUB_OWNER = "anupamnath"
GITHUB_REPO  = "teemox_licensing"

# Ed25519 public key — patched in by scripts/setup_keypair.py
PUBLIC_KEY_PEM = """
-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAGIDY1XRAic/aQGxuMirvnX6M0g67xRheQG0M1R8v+rc=
-----END PUBLIC KEY-----
"""

# ── Internal constants ─────────────────────────────────────────────────────────
_REVOCATION_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}"
    "/main/public/valid_licenses.json"
)
_LICENSE_VERSION   = 4
_DEFAULT_GRACE_H   = 24
_LIC_FILENAME      = ".tmxlic"
_CACHE_FILENAME    = ".tmxlic_sync"
_CACHE_SECRET      = b"tmxlic-v4-cache-" + APP_NAME.encode()


# ── AppData directory ─────────────────────────────────────────────────────────

def _appdata_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    d = base / APP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Fernet encryption (local cache) ───────────────────────────────────────────

def _fernet_key() -> bytes:
    """Derive a stable Fernet key from cache secret + machine fingerprint."""
    raw = hashlib.sha256(_CACHE_SECRET + get_machine_id().encode("ascii")).digest()
    return base64.urlsafe_b64encode(raw)


def _fernet() -> Fernet:
    return Fernet(_fernet_key())


def _encrypt(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def _decrypt(data: bytes) -> bytes:
    return _fernet().decrypt(data)


# ── Machine fingerprint ────────────────────────────────────────────────────────

def get_machine_id() -> str:
    """
    Return a stable 16-char hex machine fingerprint.
    Combines MAC address + hostname + Windows MachineGuid (when available).
    """
    parts: list[str] = []

    try:
        import uuid as _uuid
        mac = _uuid.getnode()
        parts.append(f"{mac:012x}")
    except Exception:
        pass

    try:
        parts.append(socket.gethostname().lower())
    except Exception:
        pass

    if sys.platform == "win32":
        try:
            import winreg
            k   = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            )
            guid, _ = winreg.QueryValueEx(k, "MachineGuid")
            winreg.CloseKey(k)
            parts.append(str(guid).lower())
        except Exception:
            pass

    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ── Base64url ─────────────────────────────────────────────────────────────────

def _b64u_decode(s: str) -> bytes:
    pad = 4 - len(s) % 4
    if pad != 4:
        s += "=" * pad
    return base64.urlsafe_b64decode(s)


# ── Canonical payload (must match server-side crypto_utils.py) ────────────────

def _canonical_v4(p: dict) -> bytes:
    machines_str = ",".join(sorted(p["m"]))
    return (
        f"{p['id']}|{p['app']}|{p['d']}|{p['e']}|{p['c']}"
        f"|{p['si']}|{machines_str}|{p['n']}|{p['g']}"
    ).encode("utf-8")


# ── Sync cache (anti-rollback + offline grace) ────────────────────────────────

def _read_sync_cache() -> Optional[dict]:
    """Return {ts: float, id: str} or None if not available / tampered."""
    path = _appdata_dir() / _CACHE_FILENAME
    try:
        raw = path.read_bytes()
        return json.loads(_decrypt(raw))
    except (FileNotFoundError, InvalidToken, json.JSONDecodeError, Exception):
        return None


def _write_sync_cache(ts: float, license_id: str = "") -> None:
    path = _appdata_dir() / _CACHE_FILENAME
    data = json.dumps({"ts": ts, "id": license_id}).encode()
    path.write_bytes(_encrypt(data))


# ── License file storage ──────────────────────────────────────────────────────

def save_license(key_str: str) -> None:
    """Encrypt and persist the license key to AppData."""
    path = _appdata_dir() / _LIC_FILENAME
    path.write_bytes(_encrypt(key_str.encode("utf-8")))


def load_license() -> Optional[str]:
    """Load and decrypt the saved license key. Returns None if not found."""
    path = _appdata_dir() / _LIC_FILENAME
    try:
        return _decrypt(path.read_bytes()).decode("utf-8")
    except Exception:
        return None


def delete_license() -> None:
    """Remove the saved license key and sync cache."""
    for fname in (_LIC_FILENAME, _CACHE_FILENAME):
        p = _appdata_dir() / fname
        try:
            p.unlink()
        except FileNotFoundError:
            pass


# ── GitHub revocation check ───────────────────────────────────────────────────

def _check_github_revocation(license_id: str, app: str, grace_hours: int) -> None:
    """
    Fetch valid_licenses.json from GitHub and verify the license is active.

    Network failure behaviour:
    - First activation (no cache): raises immediately — internet required.
    - Subsequent runs: uses grace period from last successful sync.
    - Clock rollback detected: raises immediately.

    Raises ValueError with a user-readable message on failure.
    """
    import urllib.request
    import urllib.error

    cache = _read_sync_cache()
    now   = time.time()

    # Anti-rollback: clock moved backwards by more than 5 minutes
    if cache and getattr(sys, "frozen", False):
        if now < cache["ts"] - 300:
            raise ValueError(
                "System clock anomaly detected. "
                "License validation requires an accurate clock."
            )

    try:
        import urllib.request
        req = urllib.request.Request(
            _REVOCATION_URL,
            headers={"User-Agent": f"TeemoxLicenseClient/4.0 ({APP_NAME})"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        app_data = data.get(app, {})
        revoked  = app_data.get("revoked", [])
        valid    = app_data.get("valid", [])

        if license_id in revoked:
            raise ValueError(
                "This license has been revoked. "
                "Please contact your license provider."
            )

        if valid and license_id not in valid:
            raise ValueError(
                "This license is not recognised on the server. "
                "Please contact your license provider."
            )

        # Successful sync — update cache timestamp
        _write_sync_cache(now, license_id)
        return

    except ValueError:
        raise  # propagate our own errors

    except Exception as net_err:
        # ── Offline fallback ────────────────────────────────────────────────
        if cache is None:
            raise ValueError(
                "Cannot reach the license server and no local sync record exists.\n"
                "An internet connection is required for the first activation.\n"
                f"(Error: {net_err})"
            )

        elapsed_hours = (now - cache["ts"]) / 3600.0
        if elapsed_hours > grace_hours:
            raise ValueError(
                f"License sync grace period ({grace_hours} h) has expired.\n"
                f"Last successful sync: {elapsed_hours:.1f} h ago.\n"
                "Please restore internet access to revalidate."
            )
        # Within grace period — allow the app to run
        # Caller may log:  f"Offline mode: {grace_hours - elapsed_hours:.0f} h remaining"


# ── Core license parser / verifier ───────────────────────────────────────────

def parse_and_verify(key_str: str) -> dict:
    """
    Parse, cryptographically verify, and online-validate a license key.

    Returns a dict with:
        id, app, display, expiry, created, sync_interval,
        machines, max_machines, grace_hours, notes

    Raises ValueError with a human-readable message on any failure.
    """
    key_str = key_str.strip()

    # ── v4 format ────────────────────────────────────────────────────────────
    if key_str.startswith("TMXLIC."):
        parts = key_str.split(".")
        if len(parts) != 3:
            raise ValueError(
                "Malformed license key. "
                "Expected format:  TMXLIC.<payload>.<signature>"
            )

        try:
            payload_bytes = _b64u_decode(parts[1])
            sig_bytes     = _b64u_decode(parts[2])
            p = json.loads(payload_bytes)
        except Exception as e:
            raise ValueError(f"Cannot decode license key: {e}") from e

        if p.get("v") != _LICENSE_VERSION:
            raise ValueError(
                f"Unsupported license version {p.get('v')}. "
                f"This app requires v{_LICENSE_VERSION} keys."
            )

        # ── Signature verification ────────────────────────────────────────
        try:
            pub       = load_pem_public_key(PUBLIC_KEY_PEM.strip().encode())
            canonical = _canonical_v4(p)
            pub.verify(sig_bytes, canonical)
        except InvalidSignature:
            raise ValueError(
                "License signature is invalid. "
                "This key may have been tampered with or is not authentic."
            )
        except Exception as e:
            raise ValueError(f"Signature verification error: {e}") from e

        # ── App binding ───────────────────────────────────────────────────
        if p.get("app") != APP_NAME:
            raise ValueError(
                f"This license is issued for '{p.get('app')}', "
                f"not for '{APP_NAME}'.\n"
                "Please use the correct license for this application."
            )

        # ── Expiry check ──────────────────────────────────────────────────
        expiry = p.get("e", "never")
        if str(expiry).lower() not in ("never", ""):
            try:
                if date.fromisoformat(expiry) < date.today():
                    raise ValueError(
                        f"This license expired on {expiry}.\n"
                        "Please renew your license."
                    )
            except ValueError as ve:
                if "expired" in str(ve).lower():
                    raise
                raise ValueError(f"Invalid expiry date in license: {expiry}") from ve

        # ── Machine binding ───────────────────────────────────────────────
        machines = p.get("m", ["*"])
        if machines and machines != ["*"] and "*" not in machines:
            my_id = get_machine_id()
            if my_id not in machines:
                raise ValueError(
                    f"This machine (ID: {my_id}) is not authorised for this license.\n"
                    f"{len(machines)} machine(s) are registered.\n"
                    "Contact your license provider to add this machine."
                )

        # ── GitHub revocation check (online + grace period) ───────────────
        grace_hours = int(p.get("g", _DEFAULT_GRACE_H))
        _check_github_revocation(p["id"], p["app"], grace_hours)

        return {
            "id":            p["id"],
            "app":           p["app"],
            "display":       p.get("d", ""),
            "expiry":        expiry,
            "created":       p.get("c", ""),
            "sync_interval": int(p.get("si", 90)),
            "machines":      machines,
            "max_machines":  int(p.get("n", 1)),
            "grace_hours":   grace_hours,
            "notes":         p.get("notes", ""),
        }

    # ── Legacy format (v1/v2/v3 with TMXM- prefix) ───────────────────────────
    elif key_str.startswith("TMXM-"):
        raise ValueError(
            "This is a v3 (legacy) license key.\n"
            "Please request a new v4 license key from your license provider.\n"
            "The new key starts with 'TMXLIC.'"
        )

    else:
        raise ValueError(
            "Unrecognised license key format.\n"
            "Valid keys start with 'TMXLIC.'"
        )


# ── Background sync thread ────────────────────────────────────────────────────

def start_sync_thread(
    key: str,
    sync_interval_minutes: int,
    on_invalid: Optional[Callable[[str], None]] = None,
) -> threading.Thread:
    """
    Start a daemon thread that re-validates the license every
    sync_interval_minutes minutes.

    on_invalid(message) is called if the license becomes invalid.
    Default: print a warning to stderr.
    """
    def _sync_loop() -> None:
        interval = max(30, sync_interval_minutes) * 60  # seconds
        while True:
            time.sleep(interval)
            try:
                parse_and_verify(key)
            except ValueError as e:
                msg = str(e)
                if on_invalid:
                    on_invalid(msg)
                else:
                    print(
                        f"\n[LicenseSDK] License validation failed: {msg}",
                        file=sys.stderr,
                    )

    t = threading.Thread(target=_sync_loop, daemon=True, name="LicenseSyncThread")
    t.start()
    return t
