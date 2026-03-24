#!/usr/bin/env python3
"""
Deploy lords-ai via Portainer API.

Reads credentials from .env.deploy (or environment variables).

Usage:
  python scripts/deploy.py
  python scripts/deploy.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path


def load_env_file(path: str) -> None:
    """Load key=value pairs from a file into os.environ."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())


def api(base_url: str, path: str, method: str = "GET",
        data: dict | None = None, token: str | None = None) -> dict:
    """Make an API request to Portainer."""
    url = f"{base_url}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        print(f"  [ERROR] {method} {path} → {e.code}: {body[:500]}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Deploy lords-ai via Portainer API")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without deploying")
    args = parser.parse_args()

    # Load config
    load_env_file(".env.deploy")

    base_url = os.environ.get("PORTAINER_URL", "").rstrip("/")
    username = os.environ.get("PORTAINER_USER", "")
    password = os.environ.get("PORTAINER_PASS", "")
    service_name = os.environ.get("SERVICE_NAME", "lords-ai_lords-ai")
    image = os.environ.get("IMAGE", "ghcr.io/hugodower/lords-ai:latest")

    if not base_url or not username or not password:
        print("[ERROR] Missing PORTAINER_URL, PORTAINER_USER, or PORTAINER_PASS")
        print("        Create .env.deploy from .env.deploy.example")
        sys.exit(1)

    print(f"[DEPLOY] Portainer: {base_url}")
    print(f"[DEPLOY] Service:   {service_name}")
    print(f"[DEPLOY] Image:     {image}")

    if args.dry_run:
        print("[DRY-RUN] Would authenticate, find service, and force update.")
        return

    # 1. Authenticate
    print("\n[1/4] Authenticating...")
    auth = api(base_url, "/api/auth", "POST", {"username": username, "password": password})
    token = auth.get("jwt")
    if not token:
        print("[ERROR] Auth failed — no JWT returned")
        sys.exit(1)
    print(f"  OK — JWT obtained")

    # 2. Get endpoints
    print("[2/4] Finding Docker endpoint...")
    endpoints = api(base_url, "/api/endpoints", token=token)
    if not endpoints:
        print("[ERROR] No endpoints found")
        sys.exit(1)
    endpoint_id = endpoints[0]["Id"]
    print(f"  OK — endpoint ID: {endpoint_id} ({endpoints[0].get('Name', '?')})")

    # 3. Find the service
    print(f"[3/4] Finding service '{service_name}'...")
    services = api(base_url, f"/api/endpoints/{endpoint_id}/docker/services", token=token)
    target = None
    for svc in services:
        name = svc.get("Spec", {}).get("Name", "")
        if name == service_name:
            target = svc
            break

    if not target:
        available = [s.get("Spec", {}).get("Name", "?") for s in services]
        print(f"[ERROR] Service '{service_name}' not found. Available: {available}")
        sys.exit(1)

    svc_id = target["ID"]
    version = target["Version"]["Index"]
    current_image = target["Spec"]["TaskTemplate"]["ContainerSpec"]["Image"]
    print(f"  OK — ID: {svc_id[:12]}, version: {version}")
    print(f"  Current image: {current_image}")

    # 4. Force update (pull new image + redeploy)
    print(f"[4/4] Updating service to '{image}' with force pull...")
    spec = target["Spec"]
    spec["TaskTemplate"]["ContainerSpec"]["Image"] = image
    # ForceUpdate triggers a rolling restart even if the spec hasn't changed
    spec["TaskTemplate"]["ForceUpdate"] = spec["TaskTemplate"].get("ForceUpdate", 0) + 1

    api(
        base_url,
        f"/api/endpoints/{endpoint_id}/docker/services/{svc_id}/update?version={version}",
        "POST",
        spec,
        token=token,
    )
    print(f"  OK — Service updated! Rolling restart in progress.")
    print(f"\n[DEPLOY] Done! Check status at {base_url}")


if __name__ == "__main__":
    main()
