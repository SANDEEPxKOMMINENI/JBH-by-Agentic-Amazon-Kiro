#!/usr/bin/env python3
"""
Enable session restore for the JobHuntr Chrome profile
This ensures cookies and login state persist across Chrome restarts
"""

import json
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from browser.profile_utils import get_jobhuntr_profile_path  # noqa: E402


def enable_session_restore():
    """Enable session restore in Chrome profile"""
    profile_path = get_jobhuntr_profile_path()
    preferences_path = os.path.join(profile_path, "Default", "Preferences")

    if not os.path.exists(preferences_path):
        print(f"Error: Preferences file not found at {preferences_path}")
        return False

    # Read existing preferences
    with open(preferences_path, "r", encoding="utf-8") as f:
        prefs = json.load(f)

    # Update session restore settings
    if "session" not in prefs:
        prefs["session"] = {}

    # Set to restore previous session
    # restore_on_startup: 1 = Continue where you left off
    prefs["session"]["restore_on_startup"] = 1
    if "startup_urls" not in prefs["session"]:
        prefs["session"]["startup_urls"] = []

    # Ensure exit_type is Normal (clean shutdown)
    if "profile" not in prefs:
        prefs["profile"] = {}
    prefs["profile"]["exit_type"] = "Normal"

    # Write updated preferences
    with open(preferences_path, "w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2)

    print("Session restore enabled!")
    print(f"Profile: {profile_path}")
    print("Settings:")
    print(f"  - restore_on_startup: {prefs['session']['restore_on_startup']}")
    print(f"  - exit_type: {prefs['profile']['exit_type']}")
    print("\nChrome will now restore your previous session on startup.")
    print("This means your Indeed login should persist!")

    return True


if __name__ == "__main__":
    success = enable_session_restore()
    sys.exit(0 if success else 1)
