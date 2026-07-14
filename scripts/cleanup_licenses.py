#!/usr/bin/env python3
"""
cleanup_licenses.py — Called by the GitHub Actions cleanup_licenses workflow.

1. Auto-revokes any license whose expiry date has passed.
2. Permanently deletes licenses that were revoked more than 7 days ago
   (removes the licenses/{id}.json file and all index entries).

Run schedule: daily (or manually triggered).
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

REPO         = Path(__file__).parent.parent
LICENSES_DIR = REPO / "licenses"
PUBLIC_DIR   = REPO / "public"
REVOKE_GRACE_DAYS = 7   # delete records this many days after revocation

APP_NAMES = {"TEEMOX_MAILER", "INFOMANIAK_API", "SHOPIFY_API", "HIGHTAIL_MAILER"}


def load_valid(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "updated_at":     datetime.now(timezone.utc).isoformat(),
        "schema_version": 2,
        "TEEMOX_MAILER":  {"valid": [], "revoked": [], "revoked_at": {}},
        "INFOMANIAK_API": {"valid": [], "revoked": [], "revoked_at": {}},
        "SHOPIFY_API":    {"valid": [], "revoked": [], "revoked_at": {}},
        "HIGHTAIL_MAILER": {"valid": [], "revoked": [], "revoked_at": {}},
    }


def save_valid(data: dict, path: Path) -> None:
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    vl_path = PUBLIC_DIR / "valid_licenses.json"
    valid   = load_valid(vl_path)
    now     = datetime.now(timezone.utc)
    today   = date.today()

    auto_revoked = []
    auto_deleted = []

    for record_path in sorted(LICENSES_DIR.glob("*.json")):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        lid    = record.get("id", record_path.stem)
        app    = record.get("app", "")
        status = record.get("status", "active")
        expiry = record.get("e", "never")

        if app not in APP_NAMES:
            continue

        # Ensure app entry exists in valid_licenses.json
        if app not in valid:
            valid[app] = {"valid": [], "revoked": [], "revoked_at": {}}

        app_data = valid[app]
        if "revoked_at" not in app_data:
            app_data["revoked_at"] = {}

        # ── Auto-revoke expired licenses ───────────────────────────────────
        if status == "active" and str(expiry).lower() not in ("never", ""):
            try:
                exp_date = date.fromisoformat(expiry[:10])  # handle datetime too
                if exp_date < today:
                    record["status"]     = "revoked"
                    record["revoked_at"] = now.isoformat()
                    record["revoke_reason"] = f"Auto-revoked: license expired on {expiry}"
                    record_path.write_text(
                        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
                    )

                    # Update valid_licenses.json
                    if lid in app_data.get("valid", []):
                        app_data["valid"].remove(lid)
                    if lid not in app_data.get("revoked", []):
                        app_data.setdefault("revoked", []).append(lid)
                    app_data["revoked_at"][lid] = now.isoformat()

                    auto_revoked.append(lid)
                    print(f"AUTO-REVOKED: {lid[:12]}... ({app}) — expired {expiry}")
            except ValueError:
                pass  # invalid date format, skip

        # ── Auto-delete licenses revoked > 7 days ago ─────────────────────
        elif status == "revoked":
            revoked_at_str = record.get("revoked_at") or app_data.get("revoked_at", {}).get(lid)
            if revoked_at_str:
                try:
                    revoked_dt = datetime.fromisoformat(revoked_at_str.replace("Z", "+00:00"))
                    if (now - revoked_dt).days >= REVOKE_GRACE_DAYS:
                        # Remove the license file
                        record_path.unlink(missing_ok=True)

                        # Remove from valid_licenses.json entirely
                        for lst in ("valid", "revoked"):
                            if lid in app_data.get(lst, []):
                                app_data[lst].remove(lid)
                        app_data.get("revoked_at", {}).pop(lid, None)

                        auto_deleted.append(lid)
                        print(f"AUTO-DELETED: {lid[:12]}... ({app}) — revoked {revoked_at_str[:10]}")
                except Exception as e:
                    print(f"WARN: Could not parse revoked_at for {lid}: {e}")

    # ── Save updated valid_licenses.json ──────────────────────────────────
    save_valid(valid, vl_path)

    print(f"\nSummary: {len(auto_revoked)} auto-revoked, {len(auto_deleted)} auto-deleted.")

    if not auto_revoked and not auto_deleted:
        print("Nothing to clean up — all licenses are current.")


if __name__ == "__main__":
    main()
