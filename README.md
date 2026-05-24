# Teemox License Server

GitHub-hosted license management for three applications:
- **Teemox Mailer** (`TEEMOX_MAILER`)
- **Infomaniak API** (`INFOMANIAK_API`)
- **Shopify API** (`SHOPIFY_API`)

**Admin portal:** https://anupamnath.github.io/teemox-licensing/

---

## Architecture

| Layer | Technology |
|---|---|
| Key signing | Ed25519 (private key in GitHub Secrets only) |
| Admin portal | GitHub Pages (`docs/`) |
| Backend | GitHub Actions `workflow_dispatch` |
| Revocation | `public/valid_licenses.json` on `raw.githubusercontent.com` |
| Client | `client_sdk/license_core.py` (embedded in each app) |

```
┌──────────────────────────────────────────────────────┐
│  Admin Browser                                        │
│  index.html (GitHub Pages) + app.js                  │
│  → calls GitHub Actions API with PAT                 │
└──────────────────────┬───────────────────────────────┘
                       │ workflow_dispatch
┌──────────────────────▼───────────────────────────────┐
│  GitHub Actions                                       │
│  generate_license.yml / revoke_license.yml /          │
│  update_license.yml                                   │
│  → runs scripts/generate_license.py (etc.)           │
│  → commits licenses/{id}.json                        │
│  → commits public/valid_licenses.json                │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│  Each App (Teemox Mailer, Infomaniak API, Shopify)    │
│  client_sdk/license_core.py                          │
│  → verify Ed25519 signature locally (offline-safe)   │
│  → fetch valid_licenses.json for revocation check    │
│  → encrypted local sync cache (.tmxlic_sync)         │
│  → background sync thread                            │
└──────────────────────────────────────────────────────┘
```

---

## One-Time Setup

### 1. Create the GitHub repository

1. Go to https://github.com/new
2. Name: **teemox-licensing**
3. Owner: **anupamnath**
4. Visibility: **Public** (required for raw.githubusercontent.com revocation URL)
5. Click **Create repository**

### 2. Push the `github-license-server/` contents

From your local machine:
```bash
cd github-license-server
git init
git remote add origin https://github.com/anupamnath/teemox-licensing.git
git add .
git commit -m "chore: initial license server setup"
git branch -M main
git push -u origin main
```

### 3. Generate the Ed25519 keypair

```bash
cd github-license-server
pip install cryptography
python scripts/setup_keypair.py
```

This will:
- Write `private_key.pem` (keep this secret — **never commit it**)
- Write `public_key.pem`
- Patch the public key into `client_sdk/license_core.py`

### 4. Add `LICENSE_PRIVATE_KEY_PEM` to GitHub Secrets

1. Open https://github.com/anupamnath/teemox-licensing/settings/secrets/actions
2. Click **New repository secret**
3. Name: `LICENSE_PRIVATE_KEY_PEM`
4. Value: paste the entire contents of `private_key.pem`

### 5. Enable GitHub Pages

1. Go to **Settings → Pages**
2. Source: **Deploy from a branch**
3. Branch: `main` / Folder: `/docs`
4. Save — portal available at https://anupamnath.github.io/teemox-licensing/

### 6. Enable GitHub Actions

Actions are enabled by default on new repos. Verify at **Actions → Settings**.

---

## Using the Admin Portal

1. Open https://anupamnath.github.io/teemox-licensing/
2. Create a PAT at https://github.com/settings/tokens/new with `repo` + `workflow` scopes
3. Paste the PAT on the login screen
4. Use **Generate** tab to create licenses
5. Use **Licenses** tab to view, revoke, or copy keys

---

## Integrating `client_sdk/license_core.py` into Each App

### 1. Copy the file
Copy `client_sdk/license_core.py` to your app directory.

### 2. Set the per-app constants at the top

| App | `APP_NAME` | `APP_DIR_NAME` |
|---|---|---|
| Teemox Mailer | `TEEMOX_MAILER` | `TeemoxMailer` |
| Infomaniak API | `INFOMANIAK_API` | `InfomaniakApi` |
| Shopify API | `SHOPIFY_API` | `ShopifyApi` |

### 3. Add the required dependency
```
cryptography>=41.0.0
```

### 4. Typical app startup flow

```python
from license_core import (
    load_license, save_license, delete_license,
    parse_and_verify, get_machine_id, start_sync_thread
)

# Show the machine ID to the user during activation
print("Your Machine ID:", get_machine_id())

# Activation
key_str = input("Enter your license key: ").strip()
try:
    info = parse_and_verify(key_str)
    save_license(key_str)
    print(f"Activated for {info['display']}")
    # Start background sync
    start_sync_thread(key_str, info['sync_interval'], on_invalid=_on_invalid)
except ValueError as e:
    print(f"Invalid license: {e}")

# On subsequent launches
key_str = load_license()
if not key_str:
    # → show activation screen
    pass
else:
    try:
        info = parse_and_verify(key_str)
        start_sync_thread(key_str, info['sync_interval'], on_invalid=_on_invalid)
    except ValueError as e:
        delete_license()
        # → show activation screen with e as error
```

---

## Security Architecture

1. **Ed25519 key pair** — The private key lives exclusively in GitHub Secrets. It is never in the repository or binary.
2. **License key format** — `TMXLIC.<base64url_json>.<base64url_signature>`. Any tampering invalidates the Ed25519 signature.
3. **Machine binding** — License contains a list of allowed 16-char hex machine IDs (SHA-256 of MAC + hostname + Windows MachineGuid). Floating licenses enforce `max_machines` server-side.
4. **Revocation** — `public/valid_licenses.json` is updated on every generate/revoke action. Each app fetches it on startup and every `sync_interval` minutes.
5. **Encrypted sync cache** — Local `.tmxlic_sync` is Fernet-encrypted. Key is derived from a secret constant + machine fingerprint. Prevents offline spoofing.
6. **Anti-rollback** — If the system clock moves backwards by >5 minutes (frozen-binary mode only), the SDK raises an error. Prevents clock manipulation to extend expired licenses.
7. **Grace period** — After the first successful online sync, the app can run offline for `grace_hours` (default 24 h). After that, internet is required.

---

## File Layout

```
github-license-server/
├── .gitignore                   # excludes private_key.pem
├── requirements.txt             # cryptography>=41
├── README.md                    # this file
├── scripts/
│   ├── crypto_utils.py          # shared signing / verification utilities
│   ├── setup_keypair.py         # one-time keypair generator
│   ├── generate_license.py      # called by GitHub Actions
│   ├── revoke_license.py        # called by GitHub Actions
│   └── update_license.py        # called by GitHub Actions
├── .github/workflows/
│   ├── generate_license.yml
│   ├── revoke_license.yml
│   └── update_license.yml
├── docs/                        # GitHub Pages — admin portal
│   ├── index.html
│   ├── style.css
│   └── app.js
├── client_sdk/                  # Copy to each app
│   ├── __init__.py
│   └── license_core.py
├── public/
│   └── valid_licenses.json      # revocation list (public)
└── licenses/                    # one JSON per license (private data)
    └── .gitkeep
```
