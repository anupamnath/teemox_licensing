#!/usr/bin/env python3
"""
delete_license.py — Called by the GitHub Actions delete_license workflow.

Permanently removes a license:
  - Deletes licenses/{id}.json
  - Removes all entries from public/valid_licenses.json

Use this for GDPR/cleanup purposes. The client will get "license not recognised"
at next sync if they still have the key.
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
    parser = argparse.ArgumentParser(description="Permanently delete a license")
    parser.add_argument("--id", required=True, help="License ID (UUID hex)")
    args = parser.parse_args()

    license_id = args.id.strip().lower().replace("-", "")

    # ── Delete license record ──────────────────────────────────────────────
    record_path = LICENSES_DIR / f"{license_id}.json"
    app = ""
    if record_path.exists():
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
            app = record.get("app", "")
        except Exception:
            pass
        record_path.unlink()
        print(f"  Deleted: {record_path.name}")
    else:
        print(f"  WARN: License file not found: {record_path.name} — continuing cleanup")

    # ── Remove from valid_licenses.json ───────────────────────────────────
    vl_path = PUBLIC_DIR / "valid_licenses.json"
    if not vl_path.exists():
        print("ERROR: valid_licenses.json not found.", file=sys.stderr)
        sys.exit(1)

    data = json.loads(vl_path.read_text(encoding="utf-8"))
    changed = False

    # Search all apps in case we don't know which one
    for app_key, app_data in data.items():
        if not isinstance(app_data, dict):
            continue
        for lst in ("valid", "revoked"):
            if license_id in app_data.get(lst, []):
                app_data[lst].remove(license_id)
                changed = True
        if license_id in app_data.get("revoked_at", {}):
            del app_data["revoked_at"][license_id]
            changed = True

    if changed:
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        vl_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Removed {license_id[:12]}... from valid_licenses.json")
    else:
        print(f"  WARN: {license_id[:12]}... not found in valid_licenses.json")

    print(f"\n  ✅  License {license_id[:12]}... permanently deleted.")
    print(f"  Clients with this key will get 'license not recognised' at next sync.")
    print(f"DELETED_ID={license_id}")


if __name__ == "__main__":
    main()
