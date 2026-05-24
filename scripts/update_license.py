#!/usr/bin/env python3
"""
update_license.py — Called by the GitHub Actions update_license workflow.

Re-signs the license with new parameters (adding/removing machines, changing
expiry, etc.).  The license_id is preserved; the old key becomes invalid because
the canonical payload changes and the old signature no longer matches.

The workflow should also optionally add the old license to a 'superseded' list
so apps re-validate correctly.
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

from crypto_utils import update_license as _update_license

LICENSES_DIR = REPO / "licenses"
PUBLIC_DIR   = REPO / "public"


def load_valid(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_valid(data: dict, path: Path) -> None:
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def parse_machines(s: str) -> list[str] | None:
    if not s or s.strip() == "":
        return None
    return [m.strip() for m in s.split(",") if m.strip()] or None


def main() -> None:
    parser = argparse.ArgumentParser(description="Update a Teemox license")
    parser.add_argument("--id",            required=True, help="License ID to update")
    parser.add_argument("--add-machines",  default="",    help="Comma-separated machine IDs to add")
    parser.add_argument("--remove-machines", default="",  help="Comma-separated machine IDs to remove")
    parser.add_argument("--set-machines",  default="",    help="Replace entire machine list (comma-separated)")
    parser.add_argument("--expiry",        default="",    help="New expiry date (YYYY-MM-DD or 'never')")
    parser.add_argument("--max-machines",  type=int, default=0, help="New max machines (0 = unchanged)")
    parser.add_argument("--sync-interval", type=int, default=0, help="New sync interval in minutes (0 = unchanged)")
    parser.add_argument("--grace-hours",   type=int, default=0, help="New grace hours (0 = unchanged)")
    parser.add_argument("--notes",         default="",    help="Update notes (empty = unchanged)")
    args = parser.parse_args()

    private_pem = os.environ.get("LICENSE_PRIVATE_KEY_PEM", "").strip()
    if not private_pem:
        print("ERROR: LICENSE_PRIVATE_KEY_PEM not set.", file=sys.stderr)
        sys.exit(1)

    license_id  = args.id.strip().lower().replace("-", "")
    record_path = LICENSES_DIR / f"{license_id}.json"
    if not record_path.exists():
        print(f"ERROR: License record not found: {record_path}", file=sys.stderr)
        sys.exit(1)

    record = json.loads(record_path.read_text(encoding="utf-8"))
    if record.get("status") == "revoked":
        print(f"ERROR: Cannot update a revoked license.", file=sys.stderr)
        sys.exit(1)

    # ── Resolve machines ───────────────────────────────────────────────────
    new_machines: list[str] | None = None
    current_machines = list(record.get("m", ["*"]))

    if args.set_machines:
        new_machines = parse_machines(args.set_machines)
    else:
        if args.add_machines:
            add = parse_machines(args.add_machines) or []
            new_machines = list(dict.fromkeys(current_machines + add))  # deduplicate, preserve order
        if args.remove_machines:
            remove = set(parse_machines(args.remove_machines) or [])
            base   = new_machines if new_machines is not None else current_machines
            new_machines = [m for m in base if m not in remove] or ["*"]

    # ── Apply updates ──────────────────────────────────────────────────────
    new_key, new_meta = _update_license(
        private_pem   = private_pem,
        existing_meta = record,
        machines      = new_machines,
        expiry        = args.expiry        if args.expiry         else None,
        max_machines  = args.max_machines  if args.max_machines   else None,
        sync_interval = args.sync_interval if args.sync_interval  else None,
        grace_hours   = args.grace_hours   if args.grace_hours    else None,
        notes         = args.notes         if args.notes          else None,
    )

    # ── Save updated record ────────────────────────────────────────────────
    record_path.write_text(
        json.dumps(new_meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ── valid_licenses.json stays the same (same ID, still valid) ─────────
    # The old key's signature no longer matches the new canonical, so the
    # old key will fail local signature verification automatically.

    print(f"LICENSE_KEY={new_key}")
    print(f"\n  ✅  License {license_id[:12]}... UPDATED.", file=sys.stderr)
    print(f"  App      : {new_meta['app']}", file=sys.stderr)
    print(f"  Machines : {', '.join(new_meta['m'])}", file=sys.stderr)
    print(f"  Expires  : {new_meta['e']}", file=sys.stderr)
    print(f"\n  NEW KEY: {new_key}\n", file=sys.stderr)


if __name__ == "__main__":
    main()
