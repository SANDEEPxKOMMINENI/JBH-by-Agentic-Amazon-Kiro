"""
Centralized automation library resolver for Playwright.

Usage:
  from browser.automation import Browser, BrowserContext, Page, sync_playwright

This module uses playwright for browser automation.
"""

from __future__ import annotations

import importlib

# Always use playwright (patchright is no longer supported)
_LIB_NAME = "playwright"

# Import playwright modules
_sync_api = importlib.import_module("playwright.sync_api")
transport = importlib.import_module("playwright._impl._transport")

# Re-export common types/APIs
Browser = getattr(_sync_api, "Browser")
BrowserContext = getattr(_sync_api, "BrowserContext")
Page = getattr(_sync_api, "Page")
sync_playwright = getattr(_sync_api, "sync_playwright")
Locator = getattr(_sync_api, "Locator", None)
