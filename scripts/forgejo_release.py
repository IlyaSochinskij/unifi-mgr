#!/usr/bin/env python3
"""Создаёт Forgejo release v0.1.7 + загружает deployment-архивы как assets.

Использует requests (зависимость пакета). jq/curl не нужны.

Usage:
    FORGEJO_TOKEN=<token> .venv/Scripts/python scripts/forgejo_release.py

Токен: Forgejo -> Settings -> Applications -> Generate Token, scope write:repository.

Env overrides: FORGEJO_BASE, FORGEJO_OWNER, FORGEJO_REPO, FORGEJO_TAG, FORGEJO_TARGET,
FORGEJO_NOTES, FORGEJO_VERIFY_SSL (set to 0 для self-signed cert).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

token = os.environ.get("FORGEJO_TOKEN")
if not token:
    sys.exit(
        "ERROR: set FORGEJO_TOKEN env var "
        "(Forgejo -> Settings -> Applications -> Generate Token, scope write:repository)"
    )

BASE = os.environ.get("FORGEJO_BASE", "https://milandir.duckdns.org").rstrip("/")
OWNER = os.environ.get("FORGEJO_OWNER", "Milandir")
REPO = os.environ.get("FORGEJO_REPO", "unifi_manager")
TAG = os.environ.get("FORGEJO_TAG", "v0.1.7")
TARGET = os.environ.get("FORGEJO_TARGET", "main")
NOTES_FILE = Path(os.environ.get("FORGEJO_NOTES", "RELEASE-NOTES-v0.1.7.md"))
VERIFY_SSL = os.environ.get("FORGEJO_VERIFY_SSL", "1") != "0"

ASSETS = [
    Path("dist/unifi-mgr-0.1.7-deploy.tar.gz"),
    Path("dist/unifi-mgr-0.1.7-deploy.zip"),
]

# --- Pre-flight ---
if not NOTES_FILE.is_file():
    sys.exit(f"ERROR: notes file not found: {NOTES_FILE}")
for a in ASSETS:
    if not a.is_file():
        sys.exit(f"ERROR: asset not found: {a}")

api = f"{BASE}/api/v1/repos/{OWNER}/{REPO}"
headers = {"Authorization": f"token {token}"}
notes = NOTES_FILE.read_text(encoding="utf-8")

# --- Create release (Forgejo создаёт тег из target_commitish если не существует) ---
print(f"==> Creating release {TAG} on {OWNER}/{REPO} (target: {TARGET})")
resp = requests.post(
    f"{api}/releases",
    headers=headers,
    json={
        "tag_name": TAG,
        "target_commitish": TARGET,
        "name": "v0.1.7 - pre-cron safety release (secret-leak, crash, restart-race, retry, dep-cap fixes)",
        "body": notes,
        "draft": False,
        "prerelease": False,
    },
    timeout=30,
    verify=VERIFY_SSL,
)
if resp.status_code == 409:
    sys.exit(f"ERROR: release {TAG} already exists. Delete it first или смени FORGEJO_TAG.")
resp.raise_for_status()
rel = resp.json()
rel_id = rel["id"]
print(f"==> Release created: id={rel_id}, tag={TAG}")

# --- Upload assets ---
for a in ASSETS:
    name = a.name
    print(f"==> Uploading {name} ...")
    with a.open("rb") as fh:
        up = requests.post(
            f"{api}/releases/{rel_id}/assets",
            headers=headers,
            params={"name": name},
            files={"attachment": (name, fh)},
            timeout=180,
            verify=VERIFY_SSL,
        )
    up.raise_for_status()
    print(f"    -> {up.json().get('browser_download_url')}")

print(f"==> Done. Release: {BASE}/{OWNER}/{REPO}/releases/tag/{TAG}")
