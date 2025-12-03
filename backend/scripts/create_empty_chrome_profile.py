#!/usr/bin/env python3
"""
Script to create an empty Chrome profile in the JobHuntr directory.
This creates a minimal Chrome profile structure with necessary files.
"""

import json
import os
import sys

# Add parent directory to path to import constants
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants import BASE_DIR, IS_MAC, IS_WINDOWS  # noqa: E402


def create_empty_chrome_profile(profile_name="chrome-user-data-empty"):
    """
    Create an empty Chrome profile in BASE_DIR.

    Args:
        profile_name: Name of the profile directory
                      (default: chrome-user-data-empty)

    Returns:
        str: Path to the created profile directory
    """
    # Profile directory path
    profile_dir = os.path.join(BASE_DIR, profile_name)

    # Create main profile directory
    os.makedirs(profile_dir, exist_ok=True)
    print(f"Created profile directory: {profile_dir}")

    # Create Default profile subdirectory
    default_profile_dir = os.path.join(profile_dir, "Default")
    os.makedirs(default_profile_dir, exist_ok=True)
    print(f"Created Default profile: {default_profile_dir}")

    # Create minimal Local State file
    local_state = {
        "profile": {
            "info_cache": {
                "Default": {
                    "name": "JobHuntr Profile",
                    "is_using_default_name": False,
                    "is_using_default_avatar": True,
                    "gaia_id": "",
                    "user_name": "",
                    "avatar_icon": "chrome://theme/IDR_PROFILE_AVATAR_0",
                }
            },
            "last_used": "Default",
            "last_active_profiles": ["Default"],
        }
    }

    local_state_path = os.path.join(profile_dir, "Local State")
    with open(local_state_path, "w", encoding="utf-8") as f:
        json.dump(local_state, f, indent=2)
    print(f"Created Local State file: {local_state_path}")

    # Create minimal Preferences file for Default profile
    preferences = {
        "profile": {
            "name": "JobHuntr Profile",
            "avatar_index": 0,
            "exit_type": "Crashed",  # Trick Chrome into restoring session cookies
        },
        "browser": {"check_default_browser": False, "show_home_button": True},
        "session": {
            "restore_on_startup": 1,  # 1 = Continue where you left off
            "startup_urls": [],
        },
        "download": {"directory_upgrade": True},
        "extensions": {"settings": {}},
    }

    preferences_path = os.path.join(default_profile_dir, "Preferences")
    with open(preferences_path, "w", encoding="utf-8") as f:
        json.dump(preferences, f, indent=2)
    print(f"Created Preferences file: {preferences_path}")

    # Create First Run file (tells Chrome this isn't the first run)
    first_run_path = os.path.join(profile_dir, "First Run")
    with open(first_run_path, "w") as f:
        f.write("")
    print(f"Created First Run marker: {first_run_path}")

    # Create essential subdirectories
    essential_dirs = [
        os.path.join(default_profile_dir, "Extensions"),
        os.path.join(default_profile_dir, "Storage"),
        os.path.join(default_profile_dir, "Session Storage"),
    ]

    for dir_path in essential_dirs:
        os.makedirs(dir_path, exist_ok=True)
    print("Created essential subdirectories")

    print("\n" + "=" * 60)
    print("Empty Chrome profile created successfully!")
    print(f"Profile location: {profile_dir}")
    print("Profile type: Empty/Clean profile")
    platform_name = "macOS" if IS_MAC else "Windows" if IS_WINDOWS else "Other"
    print(f"Platform: {platform_name}")
    print("=" * 60)

    return profile_dir


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Create an empty Chrome profile in JobHuntr directory"
    )
    parser.add_argument(
        "--name",
        default="chrome-user-data-empty",
        help="Name of the profile directory (default: chrome-user-data-empty)",
    )

    args = parser.parse_args()

    try:
        profile_path = create_empty_chrome_profile(profile_name=args.name)
        print("\nYou can now use this profile with Chrome by passing:")
        print(f'  --user-data-dir="{profile_path}"')
        return 0
    except Exception as e:
        print(f"Error creating Chrome profile: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
