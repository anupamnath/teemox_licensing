#!C:\Users\anupa\AppData\Local\Programs\Python\Python310\python.exe
"""Set GitHub Actions Secrets from local PEM files."""
import base64, json, os, sys, requests
from pathlib import Path

HERE = Path(__file__).parent
PAT = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GH_PAT", "")
OWNER, REPO_NAME = "anupamnath", "teemox_licensing"
API = f"https://api.github.com/repos/{OWNER}/{REPO_NAME}/actions/secrets"

# Map secret name -> PEM file path
# App-specific secret names and their PEM file paths
SECRET_FILES = {
    "LICENSE_PRIVATE_KEY_PEM":       HERE / "private_key.pem",
    "ZOHO_CALENDAR_PRIVATE_KEY":     HERE / "zoho_calendar_private_key.pem",
    "TEEMOX_MAILER_PRIVATE_KEY":     HERE / "private_key.pem",
    "INFOMANIAK_API_PRIVATE_KEY":    HERE / "private_key.pem",
    "SHOPIFY_API_PRIVATE_KEY":       HERE / "private_key.pem",
}

# Note: TEEMOX_MAILER, INFOMANIAK_API, SHOPIFY_API use the generic
# private_key.pem (matching public_key.pem) for now. Their per-app
# private keys were not preserved locally.

headers = {
    "Authorization": f"Bearer {PAT}",
    "Accept": "application/vnd.github.v3+json",
}

from nacl.bindings import crypto_box_seal

def get_public_key():
    r = requests.get(f"{API}/public-key", headers=headers)
    r.raise_for_status()
    pk_data = r.json()
    return pk_data["key_id"], base64.b64decode(pk_data["key"])

for secret_name, pem_path in SECRET_FILES.items():
    if not pem_path.exists():
        print(f"  ⚠  {pem_path} not found — skipping {secret_name}")
        continue
    value = pem_path.read_text(encoding="utf-8").strip()
    if not value:
        print(f"  ⚠  {pem_path} is empty — skipping {secret_name}")
        continue
    # Fetch fresh public key before each encryption
    key_id, pk_bytes = get_public_key()
    # Encrypt using libsodium sealed box
    encrypted = crypto_box_seal(value.encode("utf-8"), pk_bytes)
    encrypted_b64 = base64.b64encode(encrypted).decode()
    payload = {"encrypted_value": encrypted_b64, "key_id": key_id}
    r = requests.put(f"{API}/{secret_name}", headers=headers, json=payload)
    if r.status_code in (201, 204):
        print(f"  ✅  Set {secret_name}")
    else:
        print(f"  ❌  Failed to set {secret_name}: {r.status_code} {r.text}")

print("\nDone! Secrets should now be available in GitHub Actions.")
