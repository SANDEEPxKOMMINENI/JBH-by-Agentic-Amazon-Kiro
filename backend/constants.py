#!/usr/bin/env python3
"""
Constants for JobHuntr v2 Backend
@file purpose: Define constants and paths for the backend
"""

import os
import sys

from local_config import SERVICE_GATEWAY_URL  # noqa: F401

# Platform detection
IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

# Local settings (no environment variables)
# DEBUG and ENV available if needed

# Base directory for application data
if IS_MAC:
    BASE_DIR = os.path.expanduser("~/Library/Application Support/JobHuntr")
else:
    # Use standard Windows AppData location
    BASE_DIR = os.path.join(os.path.expanduser("~"), "AppData", "Local", "jobhuntr")

# Create base directory if it doesn't exist
os.makedirs(BASE_DIR, exist_ok=True)

# Application directories
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
RESUME_DIR = os.path.join(OUTPUT_DIR, "resume")
COVER_LETTER_DIR = os.path.join(OUTPUT_DIR, "cover_letter")
LOG_DIR = os.path.join(BASE_DIR, "logs")
OBJECTS_DIR = os.path.join(os.path.dirname(__file__), "browser")

# Create necessary directories
for directory in [OUTPUT_DIR, RESUME_DIR, COVER_LETTER_DIR, LOG_DIR]:
    os.makedirs(directory, exist_ok=True)

# File paths - Shared state file for all bots (LinkedIn, Indeed, etc.)
BOT_STATE_FILE = os.path.join(BASE_DIR, "bot_state.json")

# Service URLs (imported at top)

# Playwright browser download URLs
if IS_WINDOWS:
    PLAYWRIGHT_DOWNLOAD_URL = (
        "https://github.com/lookr-fyi/playwright_browser/releases/"
        "download/playwright-new/chromium-win.zip"
    )
else:
    PLAYWRIGHT_DOWNLOAD_URL = (
        "https://github.com/lookr-fyi/playwright_browser/releases/"
        "download/playwright-new/chromium.zip"
    )

# Automation library selection
# - Always 'playwright' on all platforms
# - Can be overridden via env AUTOMATION_LIB if needed
if IS_MAC:
    AUTOMATION_LIB = "playwright"
elif IS_WINDOWS:
    AUTOMATION_LIB = os.getenv("AUTOMATION_LIB", "playwright").lower()
else:
    AUTOMATION_LIB = os.getenv("AUTOMATION_LIB", "playwright").lower()
