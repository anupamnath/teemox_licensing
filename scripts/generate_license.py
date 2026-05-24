#!/usr/bin/env python3
"""
generate_license.py — Called by the GitHub Actions generate_license workflow.

Reads LICENSE_PRIVATE_KEY_PEM from environment, generates a signed v4 license,
saves the license record to licenses/{id}.json, and updates
public/valid_licenses.json so apps can validate online.

Outputs the key as:  LICENSE_KEY=TMXLIC.xxxxx
(captured by the workflow and shown in the run summary)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))

from crypto_utils import create_license

LICENSES_DIR = REPO / "licenses"
PUBLIC_DIR   = REPO / "public"


# ── Valid-licenses index helpers ──────────────────────────────────────────────

def load_valid(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "updated_at":     datetime.now(timezone.utc).isoformat(),
        "schema_version": 1,
        "TEEMOX_MAILER":  {"valid": [], "revoked": []},
        "INFOMANIAK_API": {"valid": [], "revoked": []},
        "SHOPIFY_API":    {"valid": [], "revoked": []},
    }


def save_valid(data: dict, path: Path) -> None:
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a Teemox license key")
    parser.add_argument("--app",           required=True,  help="TEEMOX_MAILER | INFOMANIAK_API | SHOPIFY_API")
    parser.add_argument("--display",       required=True,  help="Customer / company name")
    parser.add_argument("--expiry",        default="never",help="YYYY-MM-DD or 'never'")
    parser.add_argument("--machines",      default="*",    help="Comma-separated machine IDs (or * for any)")
    parser.add_argument("--max-machines",  type=int, default=1,  help="1–6")
    parser.add_argument("--sync-interval", type=int, default=90, help="Sync interval in minutes (min 30)")
    parser.add_argument("--grace-hours",   type=int, default=24, help="Offline grace period in hours")
    parser.add_argument("--notes",         default="",     help="Internal notes (not embedded in key)")
    args = parser.parse_args()

    private_pem = os.environ.get("LICENSE_PRIVATE_KEY_PEM", "").strip()
    if not private_pem:
        print("ERROR: LICENSE_PRIVATE_KEY_PEM environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    machines = [m.strip() for m in args.machines.split(",") if m.strip()] or ["*"]

    key, meta = create_license(
        private_pem   = private_pem,
        app           = args.app,
        display       = args.display,
        expiry        = args.expiry,
        machines      = machines,
        max_machines  = args.max_machines,
        sync_interval = args.sync_interval,
        grace_hours   = args.grace_hours,
        notes         = args.notes,
    )

    # ── Persist license record ─────────────────────────────────────────────
    LICENSES_DIR.mkdir(exist_ok=True)
    record_path = LICENSES_DIR / f"{meta['id']}.json"
    record_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── Update valid_licenses.json ─────────────────────────────────────────
    PUBLIC_DIR.mkdir(exist_ok=True)
    vl_path = PUBLIC_DIR / "valid_licenses.json"
    valid   = load_valid(vl_path)

    if args.app not in valid:
        valid[args.app] = {"valid": [], "revoked": []}

    if meta["id"] not in valid[args.app]["valid"]:
        valid[args.app]["valid"].append(meta["id"])

    save_valid(valid, vl_path)

    # ── Outputs (captured by GitHub Actions) ──────────────────────────────
    print(f"LICENSE_KEY={key}")

    # Summary info to stderr (visible in Actions logs)
    print(f"\n{'─'*60}", file=sys.stderr)
    print(f"  LICENSE GENERATED SUCCESSFULLY", file=sys.stderr)
    print(f"{'─'*60}", file=sys.stderr)
    print(f"  App       : {args.app}", file=sys.stderr)
    print(f"  Customer  : {args.display}", file=sys.stderr)
    print(f"  Expires   : {args.expiry}", file=sys.stderr)
    print(f"  Machines  : {', '.join(machines)}", file=sys.stderr)
    print(f"  Max mach  : {args.max_machines}", file=sys.stderr)
    print(f"  Sync      : every {args.sync_interval} min", file=sys.stderr)
    print(f"  Grace     : {args.grace_hours} h", file=sys.stderr)
    print(f"  License ID: {meta['id']}", file=sys.stderr)
    print(f"\n  KEY: {key}\n", file=sys.stderr)


if __name__ == "__main__":
    main()
