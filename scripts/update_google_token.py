#!/usr/bin/env python3
"""
Update Google OAuth token for an organization in Supabase.

Solves the current limitation where lords-ai has no reauthorization flow.
When Google Calendar tokens expire, this script allows manual token update
after obtaining fresh tokens from OAuth Playground.

USAGE:
    # Dry run (shows what would be updated)
    python scripts/update_google_token.py \\
        --org-id "cc000000-0000-0000-0000-000000000001" \\
        --token-json "/tmp/google_token.json" \\
        --dry-run

    # Actual update
    python scripts/update_google_token.py \\
        --org-id "cc000000-0000-0000-0000-000000000001" \\
        --token-json "/tmp/google_token.json"

WORKFLOW:
    1. Go to https://developers.google.com/oauthplayground
    2. Authorize scope: https://www.googleapis.com/auth/calendar
    3. Exchange auth code for tokens
    4. Save response JSON to file
    5. Run this script to update Supabase

TOKEN JSON FORMAT (from Playground):
    {
      "access_token": "ya29.a0Ae4lvC...",
      "expires_in": 3599,
      "refresh_token": "1//04rz...",
      "scope": "https://www.googleapis.com/auth/calendar",
      "token_type": "Bearer"
    }

REQUIREMENTS:
    - SUPABASE_URL and SUPABASE_SERVICE_KEY in .env
    - Organization must exist in scheduling_config table
    - Token JSON must have access_token and refresh_token
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Env loading (same pattern as provision_org.py)
# ---------------------------------------------------------------------------

def _load_env(path: str) -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


# Load from project root
_project_root = Path(__file__).parent.parent
_load_env(str(_project_root / ".env"))
_load_env(str(_project_root / ".env.deploy"))
_load_env(str(_project_root / ".env.local"))

# Import after env loading
from supabase import create_client


class TokenUpdater:
    """Handles Google OAuth token update operations."""

    def __init__(self):
        self.supabase_url = os.environ.get("SUPABASE_URL", "")
        self.supabase_key = os.environ.get("SUPABASE_SERVICE_KEY", "") or os.environ.get("SUPABASE_KEY", "")

        if not self.supabase_url or not self.supabase_key:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set. "
                "Checked: .env, .env.deploy, .env.local, and environment variables."
            )

        self.sb = create_client(self.supabase_url, self.supabase_key)
        print(f"[INFO] Connected to Supabase: {self.supabase_url}")

    def load_token_file(self, file_path: str) -> dict:
        """Load and validate token JSON from OAuth Playground.

        Args:
            file_path: Path to JSON file from OAuth Playground

        Returns:
            Validated token data

        Raises:
            ValueError: If file invalid or missing required fields
        """
        token_path = Path(file_path)
        if not token_path.exists():
            raise ValueError(f"Token file not found: {file_path}")

        try:
            with open(token_path) as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in token file: {e}")

        # Validar campos obrigatórios
        required_fields = ["access_token", "refresh_token", "expires_in"]
        missing = [f for f in required_fields if not data.get(f)]
        if missing:
            raise ValueError(f"Missing required fields in token: {missing}")

        print(f"[INFO] Loaded token file: {file_path}")
        print(f"[INFO] Token fields: {list(data.keys())}")

        return data

    def validate_org_exists(self, org_id: str) -> dict:
        """Verify organization exists in scheduling_config.

        Args:
            org_id: Organization UUID

        Returns:
            Current scheduling_config row

        Raises:
            ValueError: If org not found or no scheduling_config
        """
        try:
            resp = (
                self.sb.table("scheduling_config")
                .select("*")
                .eq("organization_id", org_id)
                .maybe_single()
                .execute()
            )
        except Exception as e:
            raise ValueError(f"Failed to query Supabase: {e}")

        if not resp or not resp.data:
            raise ValueError(f"Organization {org_id} not found in scheduling_config table")

        config = resp.data
        print(f"[INFO] Found scheduling_config for org {org_id}")
        print(f"[INFO] Current config - type={config.get('scheduling_type')}, "
              f"calendar_id={config.get('google_calendar_id')}")

        return config

    def build_lords_token(self, playground_token: dict) -> dict:
        """Convert OAuth Playground token to lords-ai format.

        Args:
            playground_token: Token from OAuth Playground

        Returns:
            Token in lords-ai format with calculated expiry_date
        """
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        expires_in_sec = int(playground_token["expires_in"])
        expiry_date = now_ms + (expires_in_sec * 1000)

        lords_token = {
            "access_token": playground_token["access_token"],
            "refresh_token": playground_token["refresh_token"],
            "expiry_date": expiry_date,
            "token_type": playground_token.get("token_type", "Bearer"),
            "scope": playground_token.get("scope", "https://www.googleapis.com/auth/calendar")
        }

        print(f"[INFO] Token converted - expires_in={expires_in_sec}s, expiry_date={expiry_date}")

        return lords_token

    def backup_current_token(self, org_id: str, current_config: dict) -> Optional[Path]:
        """Backup current token to file before update.

        Args:
            org_id: Organization ID
            current_config: Current scheduling config

        Returns:
            Path to backup file, or None if no token to backup
        """
        current_token = current_config.get("google_oauth_token")
        if not current_token:
            print("[INFO] No current token to backup")
            return None

        backup_dir = Path("tmp/google_token_backups")
        backup_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"token_{org_id}_{timestamp}.json"

        with open(backup_path, "w") as f:
            json.dump(current_token, f, indent=2)

        print(f"[INFO] Current token backed up to: {backup_path}")
        return backup_path

    def confirm_update(self, org_id: str, current_config: dict, new_token: dict, auto_yes: bool = False) -> bool:
        """Show diff and ask user confirmation.

        Args:
            org_id: Organization ID
            current_config: Current scheduling config
            new_token: New token to be saved

        Returns:
            True if user confirms, False otherwise
        """
        current_token = current_config.get("google_oauth_token", {})

        print(f"\nUPDATING GOOGLE TOKEN FOR ORG: {org_id}")

        if current_token:
            current_expiry = current_token.get('expiry_date', 'Unknown')
            current_access = current_token.get('access_token', 'None')
            print(f"Current token expiry: {current_expiry}")
            if current_access and len(current_access) > 30:
                print(f"Current access_token: {current_access[:20]}...{current_access[-10:]}")
        else:
            print("Current token: None")

        print(f"New token expiry:     {new_token['expiry_date']}")
        print(f"New access_token:     {new_token['access_token'][:20]}...{new_token['access_token'][-10:]}")
        print(f"New refresh_token:    {new_token['refresh_token'][:15]}...{new_token['refresh_token'][-5:]}")

        if auto_yes:
            print("\nProceed with UPDATE? (yes/no): yes [AUTO-CONFIRMED]")
            return True

        while True:
            response = input("\nProceed with UPDATE? (yes/no): ").strip().lower()
            if response in ("yes", "y"):
                return True
            elif response in ("no", "n"):
                return False
            else:
                print("Please answer 'yes' or 'no'")

    def update_token(self, org_id: str, token_data: dict, dry_run: bool = False) -> bool:
        """Update google_oauth_token in Supabase.

        Args:
            org_id: Organization UUID
            token_data: Token in lords-ai format
            dry_run: If True, show what would be updated without saving

        Returns:
            True if successful, False otherwise
        """
        if dry_run:
            print(f"[DRY-RUN] Would update org {org_id} with token keys: {list(token_data.keys())}")
            print(f"[DRY-RUN] New expiry_date: {token_data['expiry_date']}")
            return True

        try:
            result = self.sb.table("scheduling_config").update(
                {"google_oauth_token": token_data}
            ).eq("organization_id", org_id).execute()

            rows_affected = len(result.data) if result and result.data else 0

            if rows_affected == 0:
                print(f"[ERROR] UPDATE failed - no rows affected for org {org_id}")
                return False

            print(f"[SUCCESS] Token updated successfully for org {org_id}")

            # Verify update by reading back
            verify_resp = (
                self.sb.table("scheduling_config")
                .select("google_oauth_token")
                .eq("organization_id", org_id)
                .maybe_single()
                .execute()
            )

            if verify_resp and verify_resp.data:
                saved_token = verify_resp.data.get("google_oauth_token", {})
                saved_expiry = saved_token.get("expiry_date")
                if saved_expiry == token_data["expiry_date"]:
                    print(f"[SUCCESS] Verification passed - token saved correctly")
                else:
                    print(f"[WARNING] Verification mismatch - expected {token_data['expiry_date']}, got {saved_expiry}")

            return True

        except Exception as e:
            print(f"[ERROR] Failed to update token: {e}")
            return False


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Update Google OAuth token for a lords-ai organization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run
  python scripts/update_google_token.py --org-id "cc000000-0000-0000-0000-000000000001" --token-json "/tmp/token.json" --dry-run

  # Actual update
  python scripts/update_google_token.py --org-id "cc000000-0000-0000-0000-000000000001" --token-json "/tmp/token.json"
        """
    )

    parser.add_argument(
        "--org-id",
        required=True,
        help="Organization UUID from Supabase"
    )
    parser.add_argument(
        "--token-json",
        required=True,
        help="Path to JSON file with OAuth token from Google Playground"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes"
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt (auto-confirm update)"
    )

    args = parser.parse_args()

    # Validate UUID format
    try:
        uuid.UUID(args.org_id)
    except ValueError:
        print(f"[ERROR] Invalid UUID format: {args.org_id}")
        sys.exit(1)

    try:
        # Initialize updater
        print("[INFO] Initializing token updater...")
        updater = TokenUpdater()

        # Load and validate token file
        print(f"[INFO] Loading token file: {args.token_json}")
        playground_token = updater.load_token_file(args.token_json)

        # Validate organization exists
        print(f"[INFO] Validating organization: {args.org_id}")
        current_config = updater.validate_org_exists(args.org_id)

        # Convert token format
        print("[INFO] Converting token to lords-ai format...")
        lords_token = updater.build_lords_token(playground_token)

        # Backup current token
        if not args.dry_run:
            print("[INFO] Creating backup of current token...")
            backup_path = updater.backup_current_token(args.org_id, current_config)

        # Confirm update (unless dry run)
        if not args.dry_run:
            if not updater.confirm_update(args.org_id, current_config, lords_token, auto_yes=args.yes):
                print("[INFO] Update cancelled by user")
                sys.exit(0)

        # Perform update
        print(f"[INFO] {'[DRY-RUN] ' if args.dry_run else ''}Updating token...")
        success = updater.update_token(args.org_id, lords_token, dry_run=args.dry_run)

        if success:
            if args.dry_run:
                print("\n[SUCCESS]DRY-RUN completed successfully")
                print("   Run without --dry-run to perform actual update")
            else:
                print(f"\n[SUCCESS]Token update completed successfully!")
                print(f"   Organization: {args.org_id}")
                print(f"   New expiry: {lords_token['expiry_date']}")
                if 'backup_path' in locals() and backup_path:
                    print(f"   Backup saved: {backup_path}")
        else:
            print("\n[ERROR]Token update failed")
            sys.exit(1)

    except ValueError as e:
        print(f"[ERROR] Validation error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()