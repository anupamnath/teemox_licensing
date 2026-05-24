#!/usr/bin/env python3
"""
setup_keypair.py — Run this ONCE locally to generate the Ed25519 keypair.

Steps:
  1.  python scripts/setup_keypair.py
  2.  Add the contents of private_key.pem as a GitHub Secret named
      LICENSE_PRIVATE_KEY_PEM  (never commit this file!)
  3.  The public key is automatically patched into:
        - client_sdk/license_core.py
        - All per-app copies of license_core.py in your app repos
  4.  Commit the updated client_sdk/license_core.py to the repo.
  5.  Delete private_key.pem from your local machine after copying to
      GitHub Secrets.  The server script only needs the env var.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Allow running from repo root or from scripts/
HERE = Path(__file__).parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))

from crypto_utils import generate_keypair

PRIV_FILE = REPO / "private_key.pem"
PUB_FILE  = REPO / "public_key.pem"
SDK_FILE  = REPO / "client_sdk" / "license_core.py"

PLACEHOLDER = "REPLACE_WITH_PUBLIC_KEY_AFTER_RUNNING_setup_keypair.py"

GITIGNORE   = REPO / ".gitignore"


def patch_public_key(pub_pem: str) -> None:
    """Replace the PUBLIC_KEY_PEM placeholder in client_sdk/license_core.py."""
    if not SDK_FILE.exists():
        print(f"  ⚠  {SDK_FILE} not found — skipping patch.")
        return

    content = SDK_FILE.read_text(encoding="utf-8")

    # Remove surrounding -----BEGIN/END----- lines and whitespace for embedding
    # We embed the full PEM including headers
    if PLACEHOLDER in content:
        content = content.replace(PLACEHOLDER, pub_pem.strip())
        SDK_FILE.write_text(content, encoding="utf-8")
        print(f"  ✅  Patched public key into {SDK_FILE}")
    else:
        # Already patched — replace the existing key
        pattern = r'(PUBLIC_KEY_PEM\s*=\s*""")(.*?)(""")'
        replacement = rf'\g<1>\n{pub_pem.strip()}\n\g<3>'
        new_content  = re.sub(pattern, replacement, content, flags=re.DOTALL)
        if new_content != content:
            SDK_FILE.write_text(new_content, encoding="utf-8")
            print(f"  ✅  Re-patched public key into {SDK_FILE}")
        else:
            print(f"  ⚠  Could not patch {SDK_FILE} — update PUBLIC_KEY_PEM manually.")


def update_gitignore() -> None:
    """Ensure private_key.pem is in .gitignore."""
    lines = GITIGNORE.read_text(encoding="utf-8").splitlines() if GITIGNORE.exists() else []
    if "private_key.pem" not in lines:
        with open(GITIGNORE, "a", encoding="utf-8") as f:
            f.write("\n# Ed25519 private key — NEVER COMMIT\nprivate_key.pem\n")
        print(f"  ✅  Added private_key.pem to {GITIGNORE}")


def main() -> None:
    print("\n" + "═" * 60)
    print("  Teemox License Server — Keypair Setup")
    print("═" * 60)

    if PRIV_FILE.exists():
        ans = input("\n  private_key.pem already exists. Regenerate? [y/N] ").strip().lower()
        if ans != "y":
            # Re-patch public key from existing private key
            from cryptography.hazmat.primitives.serialization import (
                Encoding, PublicFormat, load_pem_private_key,
            )
            priv_pem = PRIV_FILE.read_text(encoding="utf-8")
            priv     = load_pem_private_key(priv_pem.encode(), password=None)
            pub_pem  = priv.public_key().public_bytes(
                Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
            ).decode()
            PUB_FILE.write_text(pub_pem, encoding="utf-8")
            patch_public_key(pub_pem)
            print("\n  ✅  Keypair re-used. public_key.pem and SDK patched.\n")
            return

    priv_pem, pub_pem = generate_keypair()
    PRIV_FILE.write_text(priv_pem, encoding="utf-8")
    PUB_FILE.write_text(pub_pem,  encoding="utf-8")
    print(f"\n  ✅  Generated new keypair:")
    print(f"       Private: {PRIV_FILE}")
    print(f"       Public : {PUB_FILE}")

    update_gitignore()
    patch_public_key(pub_pem)

    print("\n  ─────────────────────────────────────────────────────")
    print("  NEXT STEPS:")
    print("  1.  Copy the contents of private_key.pem into GitHub Secret:")
    print("        Settings → Secrets → Actions → New secret")
    print("        Name:  LICENSE_PRIVATE_KEY_PEM")
    print("        Value: (paste entire contents of private_key.pem)")
    print("  2.  Commit and push client_sdk/license_core.py (public key patched).")
    print("  3.  Delete private_key.pem from this machine after step 1.")
    print("  ─────────────────────────────────────────────────────\n")


if __name__ == "__main__":
    main()
