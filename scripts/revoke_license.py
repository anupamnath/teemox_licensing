#!/usr/bin/env python3
"""
revoke_license.py — Called by the GitHub Actions revoke_license workflow.

Moves the given license ID from 'valid' to 'revoked' in valid_licenses.json
and marks the license record as revoked.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO         = Path(__file__).parent.parent
LICENSES_DIR = REPO / "licenses"
PUBLIC_DIR   = REPO / "public"


def main() -> None:
    parser = argparse.ArgumentParser(description="Revoke a Teemox license")
    parser.add_argument("--id",     required=True, help="License ID (UUID hex)")
    parser.add_argument("--reason", default="revoked by admin", help="Reason for revocation")
    args = parser.parse_args()

    license_id = args.id.strip().lower().replace("-", "")

    # ── Load license record ────────────────────────────────────────────────
    record_path = LICENSES_DIR / f"{license_id}.json"
    if not record_path.exists():
        print(f"ERROR: License record not found: {record_path}", file=sys.stderr)
        sys.exit(1)

    record = json.loads(record_path.read_text(encoding="utf-8"))
    app    = record.get("app", "")

    # ── Update license record ──────────────────────────────────────────────
    record["status"]      = "revoked"
    record["revoked_at"]  = datetime.now(timezone.utc).isoformat()
    record["revoke_reason"] = args.reason
    record_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── Update valid_licenses.json ─────────────────────────────────────────
    vl_path = PUBLIC_DIR / "valid_licenses.json"
    if not vl_path.exists():
        print("ERROR: valid_licenses.json not found.", file=sys.stderr)
        sys.exit(1)

    data = json.loads(vl_path.read_text(encoding="utf-8"))

    if app not in data:
        data[app] = {"valid": [], "revoked": []}

    # Remove from valid
    if license_id in data[app]["valid"]:
        data[app]["valid"].remove(license_id)

    # Add to revoked (deduplicated)
    if license_id not in data[app]["revoked"]:
        data[app]["revoked"].append(license_id)

    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    vl_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n  ✅  License {license_id[:12]}... has been REVOKED.", file=sys.stderr)
    print(f"  App    : {app}", file=sys.stderr)
    print(f"  Reason : {args.reason}", file=sys.stderr)
    print(f"  All running instances will be blocked at next sync.\n", file=sys.stderr)

    # Output for Actions summary
    print(f"REVOKED_ID={license_id}")


if __name__ == "__main__":
    main()
