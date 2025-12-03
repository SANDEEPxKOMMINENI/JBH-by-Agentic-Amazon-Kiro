"""
Browser Operator - Modern sync browser automation
Complete replacement for BrowserSession with sync Playwright's bundled Chromium
"""

import json
import logging
import os
import random
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from browser.automation import Browser, BrowserContext, Page, sync_playwright
from browser.automation import transport as _playwright_transport  # noqa: E402
from browser.browser_executable_manager import BrowserManager  # noqa: E402
from browser.browser_operator.playwright_wrapper import PlaywrightWrapper  # noqa: E402
from browser.profile_utils import (  # noqa: E402
    LEGACY_PROFILE_NAME,
    PROFILE_NAME_PREFIX,
    get_jobhuntr_profile_name,
    get_jobhuntr_profile_path,
)
from constants import BASE_DIR, IS_MAC, IS_WINDOWS, LOG_DIR  # noqa: E402

logger = logging.getLogger(__name__)

_ORIG_COMPUTE_DRIVER_EXECUTABLE = _playwright_transport.compute_driver_executable


def _resolve_bundle_driver_paths() -> list[Path]:
    """Return possible driver directories when running from a frozen bundle.

    Support Playwright driver layout to ensure the overridden
    compute_driver_executable can locate the embedded driver.
    """
    candidates: list[Path] = []

    # Always use playwright (patchright is no longer supported)
    lib_name = "playwright"

    def add_paths(root: Path):
        candidates.append(root / lib_name / "driver")

    # PyInstaller exposes the extracted bundle root via sys._MEIPASS
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        add_paths(Path(bundle_root))

    # Fallback to paths relative to the executable location
    executable_dir = Path(getattr(sys, "executable", "")).resolve().parent
    if executable_dir:
        add_paths(executable_dir / "_internal")
        add_paths(executable_dir)
        # PyInstaller colocation with resources folder (macOS app bundle)
        resources_root = (
            executable_dir
            / ".."
            / "Resources"
            / "backend"
            / "dist"
            / "fastapi_server"
            / "_internal"
        )
        add_paths(resources_root)

    # Finally, try resolving relative to this file (useful for dev/debug runs)
    module_root = Path(__file__).resolve().parent.parent  # backend/
    add_paths(module_root / "dist" / "fastapi_server" / "_internal")
    add_paths((module_root / "..").resolve() / "dist" / "fastapi_server" / "_internal")

    return candidates


def _compute_driver_executable_with_bundle_support():
    node_name = "node.exe" if sys.platform == "win32" else "node"
    debug_messages: list[str] = []
    for driver_dir in _resolve_bundle_driver_paths():
        node_path = driver_dir / node_name
        cli_path = driver_dir / "package" / "cli.js"
        node_exists = node_path.exists()
        cli_exists = cli_path.exists()
        debug_messages.append(
            f"Checked driver_dir={driver_dir} "
            f"(node_exists={node_exists}, cli_exists={cli_exists})"
        )
        if node_exists and cli_exists:
            message = (
                f"Using bundled Playwright driver from {driver_dir} "
                f"(node={node_path}, cli={cli_path})"
            )
            # Print as a fallback in case logging is not yet configured
            print(f"[BrowserOperator] {message}", file=sys.stderr, flush=True)
            logger.info(message)
            return str(node_path), str(cli_path)

    warning_message = (
        "Bundled Playwright driver not found in expected locations; "
        "falling back to default resolution. "
        "This may fail inside the packaged app."
    )
    if debug_messages:
        for msg in debug_messages:
            print(f"[BrowserOperator] {msg}", file=sys.stderr, flush=True)
            logger.debug(msg)
    print(f"[BrowserOperator] {warning_message}", file=sys.stderr, flush=True)
    logger.warning(warning_message)
    return _ORIG_COMPUTE_DRIVER_EXECUTABLE()


_playwright_transport.compute_driver_executable = (
    _compute_driver_executable_with_bundle_support
)


class BrowserOperator(PlaywrightWrapper):
    """
    Modern sync browser operator using Playwright's bundled Chromium
    Complete replacement for BrowserSession with enhanced functionality
    """

    def __init__(self, headless: bool = True, **wrapper_kwargs):
        # Initialize parent PlaywrightWrapper
        super().__init__(**wrapper_kwargs)

        self.headless = headless
        self.playwright = None
        self.browser: Browser = None
        self.context: BrowserContext = None
        self.is_persistent = False
        self.browser_manager = BrowserManager()
        self.browser_mode = os.environ.get("JOBHUNTR_BROWSER_MODE", "cdp").lower()

        # Check Chrome availability first
        chrome_path = self.browser_manager.get_chrome_executable_path()
        chrome_exists = chrome_path is not None and os.path.exists(chrome_path)

        # Auto-detect: if mode is "auto" or "cdp", try CDP first if Chrome is available
        if self.browser_mode == "auto":
            # Check if Chrome is available - if yes, prefer CDP mode
            self.use_cdp = chrome_exists
            if self.use_cdp:
                logger.info(
                    f"Chrome detected at {chrome_path} - will use CDP mode (auto-detected)"
                )
            else:
                logger.info(
                    f"Chrome not found at {chrome_path} - will use bundled Chromium"
                )
        elif self.browser_mode == "cdp":
            if chrome_exists:
                self.use_cdp = True
                logger.info(
                    f"CDP mode explicitly requested - Chrome found at {chrome_path}"
                )
            else:
                logger.warning(
                    f"CDP mode requested but Chrome not found at {chrome_path}. Will attempt CDP anyway and fail if Chrome unavailable."
                )
                self.use_cdp = (
                    True  # Still try CDP, will fail in start() if Chrome unavailable
                )
        elif self.browser_mode == "bundled":
            self.use_cdp = False
            logger.info(
                "Bundled Chromium mode explicitly requested via JOBHUNTR_BROWSER_MODE=bundled"
            )
        else:
            logger.warning(
                f"Unknown browser mode '{self.browser_mode}', defaulting to bundled Chromium"
            )
            self.use_cdp = False

        logger.info(
            f"BrowserOperator initialized: use_cdp={self.use_cdp}, browser_mode={self.browser_mode}, chrome_path={chrome_path}, chrome_exists={chrome_exists}"
        )

        self.cdp_port = int(os.environ.get("JOBHUNTR_CDP_PORT", "9222"))
        self.chrome_process: subprocess.Popen | None = None
        self.chrome_started_by_us = False

        # Setup screenshot directory
        self.screenshot_folder_path = os.path.join(LOG_DIR, "screenshots")
        if not os.path.exists(self.screenshot_folder_path):
            os.makedirs(self.screenshot_folder_path)

    # Removed DNS flag injection; keep CDP launch minimal and match CDP test

    def start(self):
        """Start the browser operator"""
        self.playwright = sync_playwright().start()

        if self.use_cdp:
            logger.info("Starting Browser Operator via CDP (Google Chrome)")
            try:
                ws_endpoint = self._ensure_cdp_browser()
                # Ensure playwright object is fully initialized before connecting
                # Access chromium property to ensure it's initialized
                _ = self.playwright.chromium
                self.browser = self.playwright.chromium.connect_over_cdp(ws_endpoint)
                if not self.browser.contexts:
                    raise RuntimeError(
                        "Chrome launched but no Playwright contexts are available."
                    )
                self.context = self.browser.contexts[0]
                # For CDP mode, use existing page from context (don't create new one)
                # This matches the working approach - using existing page avoids bot detection
                if self.context.pages:
                    self.page = self.context.pages[0]
                    logger.info(
                        "Using existing page from CDP context (no stealth scripts needed - profile is enough)"
                    )
                else:
                    self.page = self.context.new_page()
                    logger.info("Creating new page in CDP context")
            except KeyError as e:
                logger.error(f"Failed to initialize Playwright object: {e}")
                logger.error(
                    "This may be a compatibility issue with playwright 1.52.0 and CDP connections."
                )
                # Clean up any partially started Chrome process
                if self.chrome_started_by_us and self.chrome_process:
                    try:
                        self._terminate_chrome_process()
                    except Exception:
                        pass
                raise RuntimeError(
                    f"Failed to start browser in CDP mode: {e}. "
                    "CDP mode was enabled but Playwright initialization failed. "
                    "Set JOBHUNTR_BROWSER_MODE=bundled to use bundled Chromium instead."
                ) from e
            except Exception as e:
                logger.error(f"Failed to start browser via CDP: {e}")
                logger.error(
                    "CDP mode was requested but failed. This should not fall back to bundled Chromium."
                )
                # Clean up any partially started Chrome process
                if self.chrome_started_by_us and self.chrome_process:
                    try:
                        self._terminate_chrome_process()
                    except Exception:
                        pass
                raise RuntimeError(
                    f"Failed to start browser in CDP mode: {e}. "
                    "CDP mode was enabled but Chrome CDP connection failed. "
                    "Set JOBHUNTR_BROWSER_MODE=bundled to use bundled Chromium instead."
                ) from e
        else:
            logger.info("Starting Browser Operator with bundled Chromium")
            self.browser = self.playwright.chromium.launch(
                headless=self.headless, args=self._get_optimized_browser_args()
            )

            context_options = self._get_context_options()
            logger.info("Creating fresh browser context")
            self.context = self.browser.new_context(**context_options)
            self.page = self.context.new_page()

        # Add stealth scripts to mask automation (only for bundled Chromium, not CDP)
        # CDP mode with copied profile doesn't need stealth scripts - profile is enough
        # Testing showed that simple Playwright connection without stealth scripts works
        if not self.use_cdp:
            self._apply_stealth_scripts(self.page)
        # For CDP mode, don't apply stealth scripts - the copied profile is sufficient

        # Add route handler to bypass COEP and security policies
        self._setup_route_interception(self.page)

        # Set page reference in parent wrapper
        self.set_page(self.page)

        logger.info("Browser Operator ready")
        return self.page

    def navigate_to(
        self, url: str, timeout: int = 60000, retry_on_cloudflare: bool = True
    ):
        """Navigate to a URL with Cloudflare challenge handling and retry logic"""
        if not self.page:
            raise Exception("Browser not started. Call start() first.")

        max_retries = 2 if retry_on_cloudflare else 0
        retry_count = 0

        while retry_count <= max_retries:
            try:
                logger.info(
                    f"Navigating to {url} (attempt {retry_count + 1}/{max_retries + 1})"
                )

                # Use op wrapper for navigation to respect pause/resume
                def goto_fn():
                    return self.page.goto(
                        url, timeout=timeout, wait_until="domcontentloaded"
                    )

                self.op(goto_fn)

                logger.info(f"Navigation complete: {self.page.url}")
                return self.page.url

            except Exception as e:
                # Check if browser was closed (e.g., due to Cloudflare detection)
                if not self.page or self.is_operations_paused():
                    logger.info(
                        "Browser closed or operations paused, stopping navigation retries"
                    )
                    raise

                # Only retry if we haven't exceeded max retries
                if retry_count < max_retries:
                    logger.warning(f"Navigation failed, retrying... ({str(e)})")
                    retry_count += 1
                    time.sleep(3)
                else:
                    raise

        return self.page.url

    def close(self):
        """Close the browser operator gracefully"""
        logger.info("Closing Browser Operator gracefully")

        try:
            # Try graceful shutdown first
            if self.page:
                try:
                    self.page.close()
                    logger.debug("Page closed gracefully")
                except Exception as e:
                    logger.debug(f"Could not close page gracefully: {e}")

            if self.context:
                try:
                    self.context.close()
                    logger.debug("Context closed gracefully")
                except Exception as e:
                    logger.debug(f"Could not close context gracefully: {e}")

            if self.browser:
                try:
                    self.browser.close()
                    logger.debug("Browser closed gracefully")
                except Exception as e:
                    logger.debug(f"Could not close browser gracefully: {e}")

            if self.playwright:
                try:
                    self.playwright.stop()
                    logger.debug("Playwright stopped gracefully")
                except Exception as e:
                    logger.debug(f"Could not stop playwright gracefully: {e}")

        except Exception as e:
            logger.debug(f"Error during graceful shutdown: {e}")

        finally:
            # Reset references regardless of errors
            self.page = None
            self.context = None
            self.browser = None
            self.playwright = None

        logger.info("Browser Operator closed gracefully")
        if self.use_cdp and self.chrome_started_by_us:
            self._terminate_chrome_process()

    def _get_optimized_browser_args(self):
        """Return no extra args for simplicity and reliability"""
        return []

    def _get_context_options(self):
        return {}

    def _ensure_cdp_browser(self) -> str:
        """
        Ensure Chrome is running with CDP enabled.

        On Windows, Chrome does NOT allow remote debugging when using the default
        User Data directory path, regardless of which profile you use. This is a
        security restriction that cannot be bypassed.

        Options:
        1. Connect to existing Chrome instance with remote debugging (if available)
        2. Copy profile to custom location and launch Chrome there (current approach)
        3. Use empty profile (fallback)

        Note: Symlinks/junctions don't work - Chrome detects and rejects them.
        """
        # First, try to connect to an existing Chrome instance with remote debugging
        ws_endpoint = self._get_existing_cdp_endpoint()
        if ws_endpoint:
            logger.info("Connected to existing Chrome CDP session")
            self.chrome_started_by_us = False
            return ws_endpoint

        chrome_path = self.browser_manager.get_chrome_executable_path()
        if not chrome_path:
            raise RuntimeError(
                "Google Chrome not found. Please install Chrome to use CDP mode."
            )

        # Try to use the user's Chrome profile
        # Strategy: First try using non-default profile directly (may fail due to Chrome restriction),
        # then fall back to copying profile to custom location
        # Chrome doesn't allow remote debugging on the default User Data directory,
        # but we can try using a non-default profile first to see if it works

        # Get user's Chrome profile
        (
            user_data_dir,
            profile_name,
        ) = self.browser_manager.get_most_recent_chrome_profile()

        # Define JobHuntr User Data copy location (copy ENTIRE User Data directory, not just one profile)
        # Priority: user-specific jobhuntr_chrome_profile directories, then chrome-user-data-copy, then legacy paths
        desired_profile_name = get_jobhuntr_profile_name()
        legacy_profile_name = LEGACY_PROFILE_NAME
        preferred = get_jobhuntr_profile_path()

        if IS_WINDOWS:
            # Prefer JobHuntr\AppData path, then lowercase jobhuntr (BASE_DIR), then legacy directories
            base_candidates = [
                os.path.join(
                    os.path.expanduser("~"),
                    "AppData",
                    "Local",
                    "JobHuntr",
                    desired_profile_name,
                ),
                os.path.join(
                    os.path.expanduser("~"),
                    "AppData",
                    "Local",
                    "jobhuntr",
                    desired_profile_name,
                ),
                preferred,
            ]
            legacy_profile_candidates = [
                os.path.join(
                    os.path.expanduser("~"),
                    "AppData",
                    "Local",
                    "JobHuntr",
                    legacy_profile_name,
                ),
                os.path.join(
                    os.path.expanduser("~"),
                    "AppData",
                    "Local",
                    "jobhuntr",
                    legacy_profile_name,
                ),
                os.path.join(BASE_DIR, legacy_profile_name),
            ]

            candidates = [
                *base_candidates,
                *legacy_profile_candidates,
                os.path.join(
                    os.path.expanduser("~"),
                    "AppData",
                    "Local",
                    "JobHuntr",
                    "chrome-user-data-copy",
                ),
                os.path.join(
                    os.path.expanduser("~"),
                    "AppData",
                    "Local",
                    "jobhuntr",
                    "chrome-user-data-copy",
                ),
                os.path.join(
                    os.path.expanduser("~"),
                    "AppData",
                    "Local",
                    "JobHuntr",
                    "chrome-profile-copy",
                ),
                os.path.join(
                    os.path.expanduser("~"),
                    "AppData",
                    "Local",
                    "jobhuntr",
                    "chrome-profile-copy",
                ),
            ]
            existing = next((p for p in candidates if os.path.exists(p)), None)
            custom_user_data = existing or base_candidates[0]
        else:
            # Mac: Prefer per-user jobhuntr profile inside Application Support
            base_candidates = [
                os.path.join(
                    os.path.expanduser("~"),
                    "Library",
                    "Application Support",
                    "JobHuntr",
                    desired_profile_name,
                ),
                preferred,
            ]
            legacy = os.path.join(
                os.path.expanduser("~"),
                "Library",
                "Application Support",
                "JobHuntr",
                "chrome-user-data-copy",
            )
            legacy_named = os.path.join(
                os.path.expanduser("~"),
                "Library",
                "Application Support",
                "JobHuntr",
                legacy_profile_name,
            )

            # Use existing profile if available, otherwise prefer new naming
            existing = next((p for p in base_candidates if os.path.exists(p)), None)
            if existing:
                custom_user_data = existing
            elif os.path.exists(legacy):
                custom_user_data = legacy
            elif os.path.exists(legacy_named):
                custom_user_data = legacy_named
            else:
                custom_user_data = base_candidates[0]

        os.makedirs(custom_user_data, exist_ok=True)
        copy_marker_path = os.path.join(custom_user_data, ".jobhuntr_profile_copy")

        def _copy_user_data_directory(
            source_dir: str, destination_dir: str, retry=False
        ):
            """Copy Chrome's user data directory to a JobHuntr-specific location."""
            copy_label = " (retry)" if retry else ""
            if os.path.exists(destination_dir):
                shutil.rmtree(destination_dir)

            if IS_WINDOWS:
                os.makedirs(destination_dir, exist_ok=True)
                robocopy_cmd = [
                    "robocopy",
                    source_dir,
                    destination_dir,
                    "/E",  # Copy subdirectories including empty ones
                    "/XD",
                    "Cache",
                    "Code Cache",
                    "GPUCache",
                    "ShaderCache",
                    "DawnGraphiteCache",
                    "DawnWebGPUCache",  # Exclude cache directories
                    "Default\\Cache",
                    "Default\\Code Cache",  # Exclude Default profile caches
                    "Profile 1\\Cache",
                    "Profile 2\\Cache",
                    "Profile 3\\Cache",
                    "Profile 4\\Cache",
                    "Profile 5\\Cache",  # Exclude other profile caches
                    "/XF",
                    "*.lock",
                    "*.tmp",
                    "*.log",
                    "LOCK",
                    "SingletonLock",
                    "SingletonSocket",  # Exclude lock/temp files
                    "/NFL",
                    "/NDL",
                    "/NJH",
                    "/NJS",  # Suppress output
                ]
                result = subprocess.run(robocopy_cmd, capture_output=True, text=True)
                if result.returncode > 9:
                    raise RuntimeError(
                        f"robocopy failed with return code {result.returncode}: {result.stderr}"
                    )
                logger.info(
                    f"User Data directory copied using robocopy{copy_label}".rstrip()
                )
            else:

                def ignore_patterns(src, names):
                    ignored = set()
                    for name in names:
                        if name in [
                            "Cache",
                            "Code Cache",
                            "GPUCache",
                            "ShaderCache",
                            "DawnGraphiteCache",
                            "DawnWebGPUCache",
                        ]:
                            ignored.add(name)
                        elif name in [
                            "LOCK",
                            "SingletonLock",
                            "SingletonSocket",
                        ] or name.endswith(".lock"):
                            ignored.add(name)
                        elif name.endswith((".tmp", ".log")):
                            ignored.add(name)
                    return ignored

                try:
                    shutil.copytree(source_dir, destination_dir, ignore=ignore_patterns)
                except shutil.Error as err:
                    errors = err.args[0] if err.args else []
                    transient_missing = (
                        isinstance(errors, list)
                        and errors
                        and all(
                            isinstance(entry, tuple)
                            and len(entry) >= 3
                            and "No such file or directory" in str(entry[2])
                            for entry in errors
                        )
                    )
                    if not transient_missing:
                        raise
                    logger.warning(
                        "Some Chrome profile files disappeared while copying (likely because the browser was "
                        "still running). Continuing with the partial copy."
                    )
                logger.info(
                    f"User Data directory copied using shutil.copytree{copy_label}".rstrip()
                )
                if IS_MAC:
                    try:
                        with open(copy_marker_path, "w", encoding="utf-8") as marker:
                            marker.write("mac\n")
                    except Exception as marker_exc:
                        logger.debug(f"Failed to mark macOS profile copy: {marker_exc}")

        # Check if JobHuntr User Data copy exists and is not locked
        jobhuntr_user_data_exists = os.path.exists(custom_user_data) and any(
            os.path.isdir(os.path.join(custom_user_data, d))
            for d in os.listdir(custom_user_data)
            if d in ["Default"] or d.startswith("Profile ")
        )
        jobhuntr_user_data_locked = False

        if jobhuntr_user_data_exists:
            # Check if User Data is locked (in use)
            lock_file = os.path.join(custom_user_data, "SingletonLock")
            lock_socket = os.path.join(custom_user_data, "SingletonSocket")
            if os.path.exists(lock_file) or (
                IS_WINDOWS and os.path.exists(lock_socket)
            ):
                logger.warning(
                    "JobHuntr User Data copy is locked (in use). Will try to copy again."
                )
                jobhuntr_user_data_locked = True

        copy_marker_exists = os.path.exists(copy_marker_path)
        # Check if this is the intentional JobHuntr profile (not a copy)
        custom_basename = os.path.basename(custom_user_data)
        is_jobhuntr_profile = (
            PROFILE_NAME_PREFIX in custom_basename
            or LEGACY_PROFILE_NAME in custom_user_data
        )

        if (
            jobhuntr_user_data_exists
            and IS_MAC
            and not copy_marker_exists
            and not is_jobhuntr_profile
        ):
            # Legacy macOS copy without marker – remove so we can use the real profile
            # But keep JobHuntr's dedicated profile even without marker (it's intentionally empty)
            try:
                logger.info(
                    "Removing legacy macOS Chrome profile copy to use the real profile instead"
                )
                shutil.rmtree(custom_user_data)
            except Exception as exc:
                logger.warning(
                    f"Failed to remove legacy macOS profile copy: {exc}. Continuing with real profile."
                )
            jobhuntr_user_data_exists = False
            jobhuntr_user_data_locked = False
            copy_marker_exists = False

        use_real_profile = False

        can_use_copy = (
            jobhuntr_user_data_exists
            and not jobhuntr_user_data_locked
            and (IS_WINDOWS or copy_marker_exists or is_jobhuntr_profile)
        )

        # First priority: Use existing JobHuntr User Data copy if available and not locked
        if can_use_copy:
            if is_jobhuntr_profile:
                logger.info(f"Using JobHuntr Chrome profile: {custom_user_data}")
            else:
                logger.info("Using existing JobHuntr User Data copy")
            profile_dir = custom_user_data
            profile_dir_arg = None  # Don't specify profile, let Chrome use default
            use_real_profile = True
        elif user_data_dir:
            if IS_MAC:
                source_lock_file = os.path.join(user_data_dir, "SingletonLock")
                source_lock_socket = os.path.join(user_data_dir, "SingletonSocket")
                source_locked = os.path.exists(source_lock_file) or os.path.exists(
                    source_lock_socket
                )

                if not source_locked:
                    logger.info(
                        "Using macOS Chrome User Data directory directly (no copy needed)"
                    )
                    profile_dir = user_data_dir
                    profile_dir_arg = (
                        f"--profile-directory={profile_name}" if profile_name else None
                    )
                    use_real_profile = True
                else:
                    logger.warning(
                        "macOS Chrome profile appears locked (Chrome already running). "
                        "Creating temporary JobHuntr copy."
                    )
                    try:
                        _copy_user_data_directory(user_data_dir, custom_user_data)
                    except Exception as e:
                        logger.warning(
                            f"Failed to copy User Data directory: {e}. Using empty profile instead."
                        )
                        use_real_profile = False
                    else:
                        logger.info("Using Chrome User Data directory copy")
                        profile_dir = custom_user_data
                        profile_dir_arg = (
                            None  # Don't specify profile, let Chrome use default
                        )
                        use_real_profile = True
            elif IS_WINDOWS:
                # Copy ENTIRE User Data directory (Chrome on Windows rejects the default User Data directory)
                # Check if source User Data is locked
                source_lock_file = os.path.join(user_data_dir, "SingletonLock")
                source_lock_socket = os.path.join(user_data_dir, "SingletonSocket")
                source_locked = os.path.exists(source_lock_file) or (
                    IS_WINDOWS and os.path.exists(source_lock_socket)
                )

                if not source_locked:
                    # Copy entire User Data directory
                    should_copy = True
                    if jobhuntr_user_data_exists and not jobhuntr_user_data_locked:
                        # Check if source is newer than copy
                        try:
                            source_mtime = os.path.getmtime(user_data_dir)
                            dest_mtime = os.path.getmtime(custom_user_data)
                            if dest_mtime >= source_mtime:
                                should_copy = False
                                logger.info("JobHuntr User Data copy is up to date")
                        except Exception:
                            pass

                    if should_copy:
                        logger.info(
                            "Copying ENTIRE Chrome User Data directory to JobHuntr location..."
                        )
                        try:
                            _copy_user_data_directory(user_data_dir, custom_user_data)
                        except Exception as e:
                            logger.warning(
                                f"Failed to copy User Data directory: {e}. Using empty profile instead."
                            )
                            use_real_profile = False
                        else:
                            logger.info("Using Chrome User Data directory copy")
                            profile_dir = custom_user_data
                            profile_dir_arg = (
                                None  # Don't specify profile, let Chrome use default
                            )
                            use_real_profile = True
                    else:
                        logger.info("Using existing JobHuntr User Data copy")
                        profile_dir = custom_user_data
                        profile_dir_arg = (
                            None  # Don't specify profile, let Chrome use default
                        )
                        use_real_profile = True

        if not use_real_profile:
            # Fallback to empty custom profile directory
            logger.info("Using empty custom profile directory")
            if IS_WINDOWS:
                profile_dir = os.path.join(
                    os.path.expanduser("~"),
                    "AppData",
                    "Local",
                    "JobHuntr",
                    "cdp-profile",
                )
            else:
                profile_dir = os.path.join(
                    os.path.expanduser("~"),
                    "Library",
                    "Application Support",
                    "JobHuntr",
                    "cdp-profile",
                )
            os.makedirs(profile_dir, exist_ok=True)
            profile_dir_arg = None

        logger.info(
            "BrowserOperator will launch Chrome with user-data-dir=%s %s",
            profile_dir,
            f"(profile arg {profile_dir_arg})"
            if profile_dir_arg
            else "(default profile)",
        )

        cmd = [
            chrome_path,
            f"--remote-debugging-port={self.cdp_port}",
            f"--user-data-dir={profile_dir}",
        ]
        # Add headless flag if enabled (new headless mode for better bot detection avoidance)
        if self.headless:
            cmd.append("--headless=new")
        # Keep CDP launch minimal; no DNS flags

        # Add profile directory flag if using actual Chrome profile
        if profile_dir_arg:
            cmd.append(profile_dir_arg)
            # keep simple: no extra flags, just profile directory if provided

        env = os.environ.copy()
        logger.info(f"Launching Chrome with command: {' '.join(cmd)}")

        # Capture stderr to see Chrome's error messages
        import tempfile

        stderr_file = tempfile.NamedTemporaryFile(
            mode="w+", delete=False, suffix=".log"
        )
        stderr_file.close()

        try:
            self.chrome_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=open(stderr_file.name, "w"),
                env=env,
            )
            self.chrome_started_by_us = True

            # Give Chrome a moment to start
            time.sleep(2)

            # Check if process is still running
            if self.chrome_process.poll() is not None:
                exit_code = self.chrome_process.returncode

                # Read Chrome's error output
                error_output = ""
                try:
                    with open(stderr_file.name, "r") as f:
                        error_output = f.read()
                except Exception:
                    pass

                # Check if Chrome rejected due to using default User Data directory
                if (
                    error_output
                    and "requires a non-default data directory" in error_output
                ):
                    logger.warning(
                        f"Chrome rejected using profile directly: {error_output[:200]}. "
                        "Falling back to copying profile to custom location."
                    )

                    # Clean up temp file and process
                    try:
                        os.unlink(stderr_file.name)
                    except Exception:
                        pass
                    if self.chrome_started_by_us and self.chrome_process:
                        try:
                            self._terminate_chrome_process()
                        except Exception:
                            pass

                    # Fall back to copying entire User Data directory
                    if user_data_dir:
                        logger.info(
                            "Copying ENTIRE Chrome User Data directory to JobHuntr location (retry)..."
                        )
                        try:
                            _copy_user_data_directory(
                                user_data_dir, custom_user_data, retry=True
                            )
                            logger.info(
                                "User Data directory copied successfully, retrying Chrome launch..."
                            )

                            # Retry with copied User Data directory
                            profile_dir = custom_user_data
                            profile_dir_arg = (
                                None  # Don't specify profile, let Chrome use default
                            )

                            # Rebuild command with copied User Data directory (simple, no extra flags)
                            cmd = [
                                chrome_path,
                                f"--remote-debugging-port={self.cdp_port}",
                                f"--user-data-dir={profile_dir}",
                            ]
                            # Add headless flag if enabled
                            if self.headless:
                                cmd.append("--headless=new")

                            # Add profile directory flag if specified
                            if profile_dir_arg:
                                cmd.append(profile_dir_arg)

                            logger.info(
                                f"Retrying Chrome launch with copied User Data: {' '.join(cmd)}"
                            )

                            # Create new stderr file for retry
                            stderr_file = tempfile.NamedTemporaryFile(
                                mode="w+", delete=False, suffix=".log"
                            )
                            stderr_file.close()

                            self.chrome_process = subprocess.Popen(
                                cmd,
                                stdout=subprocess.DEVNULL,
                                stderr=open(stderr_file.name, "w"),
                                env=env,
                            )

                            time.sleep(2)

                            # Check again
                            if self.chrome_process.poll() is not None:
                                exit_code = self.chrome_process.returncode
                                try:
                                    with open(stderr_file.name, "r") as f:
                                        error_output = f.read()
                                except Exception:
                                    pass
                                raise RuntimeError(
                                    f"Chrome process exited with code {exit_code} even after copying User Data. "
                                    f"Error: {error_output[:200] if error_output else 'Unknown error'}"
                                )

                            # Success - continue to wait for CDP endpoint
                            try:
                                os.unlink(stderr_file.name)
                            except Exception:
                                pass

                            return self._wait_for_cdp_endpoint()
                        except Exception as e:
                            logger.error(
                                f"Failed to copy User Data directory and retry: {e}"
                            )
                            raise RuntimeError(
                                f"Failed to use profile directly and failed to copy: {e}"
                            )
                    elif user_data_dir:
                        raise RuntimeError(
                            "Chrome rejected using the default profile and copying the profile failed. "
                            "Close any running Chrome instances or launch JobHuntr with an empty profile."
                        )

                error_msg = (
                    f"Chrome process exited immediately with code {exit_code}. "
                    "This may indicate the profile is locked or Chrome failed to start. "
                    "Try closing any running Chrome instances or use a different profile."
                )

                if error_output:
                    logger.error(f"Chrome stderr output: {error_output[:500]}")
                    error_msg += f"\nChrome error: {error_output[:200]}"

                # Clean up temp file
                try:
                    os.unlink(stderr_file.name)
                except Exception:
                    pass

                raise RuntimeError(error_msg)

            # Clean up temp file if Chrome is running
            try:
                os.unlink(stderr_file.name)
            except Exception:
                pass

            return self._wait_for_cdp_endpoint()
        except Exception as e:
            # Clean up temp file on error
            try:
                if os.path.exists(stderr_file.name):
                    with open(stderr_file.name, "r") as f:
                        error_output = f.read()
                        if error_output:
                            logger.error(f"Chrome stderr output: {error_output[:500]}")
                    os.unlink(stderr_file.name)
            except Exception:
                pass

            if self.chrome_started_by_us and self.chrome_process:
                try:
                    self._terminate_chrome_process()
                except Exception:
                    pass
            raise

    def _get_existing_cdp_endpoint(self) -> str | None:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.cdp_port}/json/version", timeout=1
            ) as response:
                payload = json.loads(response.read().decode())
                return payload.get("webSocketDebuggerUrl")
        except Exception:
            return None

    def _wait_for_cdp_endpoint(self, timeout: int = 20) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            # Check if Chrome process is still running
            if self.chrome_started_by_us and self.chrome_process:
                if self.chrome_process.poll() is not None:
                    exit_code = self.chrome_process.returncode
                    raise RuntimeError(
                        f"Chrome process exited with code {exit_code} before CDP endpoint became available. "
                        "This may indicate the profile is locked, Chrome crashed, or there's a configuration issue."
                    )

            endpoint = self._get_existing_cdp_endpoint()
            if endpoint:
                logger.info(f"CDP endpoint available: {endpoint}")
                return endpoint
            time.sleep(0.5)

        # Final check if process is still running
        if self.chrome_started_by_us and self.chrome_process:
            if self.chrome_process.poll() is not None:
                exit_code = self.chrome_process.returncode
                raise RuntimeError(
                    f"Chrome process exited with code {exit_code}. "
                    "CDP endpoint never became available."
                )

        raise RuntimeError(
            "Chrome remote debugging endpoint not available after timeout. "
            "Verify Chrome launched successfully. "
            "If using your Chrome profile, ensure no other Chrome instances are using it."
        )

    def _terminate_chrome_process(self):
        if not self.chrome_process:
            return
        try:
            self.chrome_process.terminate()
            self.chrome_process.wait(timeout=5)
        except Exception as exc:
            logger.debug(f"Failed to terminate Chrome process: {exc}")
        finally:
            self.chrome_process = None
            self.chrome_started_by_us = False

    def _setup_route_interception(self, page: Page):
        """
        Setup route interception to bypass COEP and security policies
        This intercepts RESPONSES (not just requests) to strip restrictive headers
        """
        try:
            # Use CDP to modify response headers (Playwright doesn't support this natively)
            # We need to use add_init_script to inject code that overrides the headers

            # JavaScript to override COEP and COOP via service worker
            coep_bypass_script = """
            // Override document.domain to help with COEP
            try {
                document.domain = document.domain;
            } catch(e) {}

            // Intercept fetch requests to strip COEP headers
            const originalFetch = window.fetch;
            window.fetch = function(...args) {
                return originalFetch.apply(this, args).then(response => {
                    // Can't modify headers of actual response, but we can at least log
                    return response;
                });
            };

            // Override XMLHttpRequest to bypass COEP for Cloudflare signals
            const originalOpen = XMLHttpRequest.prototype.open;
            const originalSend = XMLHttpRequest.prototype.send;

            XMLHttpRequest.prototype.open = function(method, url, ...rest) {
                this._url = url;
                return originalOpen.apply(this, [method, url, ...rest]);
            };

            XMLHttpRequest.prototype.send = function(...args) {
                // For Cloudflare signals, ensure proper headers
                if (this._url && (this._url.includes('cloudflare') || this._url.includes('indeed.com'))) {
                    try {
                        this.setRequestHeader('Origin', 'https://www.indeed.com');
                    } catch(e) {}
                }
                return originalSend.apply(this, args);
            };

            console.log('棣冩晛 COEP bypass scripts injected');
            """

            page.add_init_script(coep_bypass_script)
            logger.info("COEP bypass scripts injected")

        except Exception as e:
            logger.warning(f"Failed to setup COEP bypass: {e}")

    def _apply_stealth_scripts(self, page: Page):
        """Apply comprehensive stealth scripts to avoid bot detection"""
        stealth_js = """
        // Override navigator.webdriver
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });

        // Override chrome property
        window.chrome = {
            runtime: {},
            loadTimes: function() {},
            csi: function() {},
            app: {}
        };

        // Override permissions
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );

        // Override plugins to avoid headless detection
        Object.defineProperty(navigator, 'plugins', {
            get: () => [
                {
                    0: {type: "application/x-google-chrome-pdf", suffixes: "pdf", description: "Portable Document Format"},
                    description: "Portable Document Format",
                    filename: "internal-pdf-viewer",
                    length: 1,
                    name: "Chrome PDF Plugin"
                },
                {
                    0: {type: "application/pdf", suffixes: "pdf", description: "Portable Document Format"},
                    description: "Portable Document Format",
                    filename: "mhjfbmdgcfjbbpaeojofohoefgiehjai",
                    length: 1,
                    name: "Chrome PDF Viewer"
                },
                {
                    0: {type: "application/x-nacl", suffixes: "", description: "Native Client Executable"},
                    1: {type: "application/x-pnacl", suffixes: "", description: "Portable Native Client Executable"},
                    description: "",
                    filename: "internal-nacl-plugin",
                    length: 2,
                    name: "Native Client"
                }
            ],
        });

        // Override languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en']
        });

        // Override platform
        Object.defineProperty(navigator, 'platform', {
            get: () => 'MacIntel'
        });

        // Override vendor
        Object.defineProperty(navigator, 'vendor', {
            get: () => 'Google Inc.'
        });

        // Mock battery API
        if (!navigator.getBattery) {
            navigator.getBattery = () => Promise.resolve({
                charging: true,
                chargingTime: 0,
                dischargingTime: Infinity,
                level: 1,
                addEventListener: () => {},
                removeEventListener: () => {},
                dispatchEvent: () => true
            });
        }

        // Override connection
        Object.defineProperty(navigator, 'connection', {
            get: () => ({
                effectiveType: '4g',
                rtt: 50,
                downlink: 10,
                saveData: false
            })
        });

        // Override hardwareConcurrency
        Object.defineProperty(navigator, 'hardwareConcurrency', {
            get: () => 8
        });

        // Override deviceMemory
        Object.defineProperty(navigator, 'deviceMemory', {
            get: () => 8
        });

        // Override screen properties
        Object.defineProperty(screen, 'availWidth', { get: () => 1920 });
        Object.defineProperty(screen, 'availHeight', { get: () => 1080 });
        Object.defineProperty(screen, 'width', { get: () => 1920 });
        Object.defineProperty(screen, 'height', { get: () => 1080 });
        Object.defineProperty(screen, 'colorDepth', { get: () => 24 });
        Object.defineProperty(screen, 'pixelDepth', { get: () => 24 });

        // Add realistic mouse movement tracking
        let mouseX = 0, mouseY = 0;
        document.addEventListener('mousemove', (e) => {
            mouseX = e.clientX;
            mouseY = e.clientY;
        }, true);

        // Override Date to use consistent timezone
        const originalDate = Date;
        const timezoneOffset = -300; // EST offset in minutes
        Date = new Proxy(originalDate, {
            construct(target, args) {
                if (args.length === 0) {
                    return new target();
                }
                return new target(...args);
            },
            apply(target, thisArg, args) {
                if (args.length === 0) {
                    return target();
                }
                return target(...args);
            }
        });
        Date.prototype = originalDate.prototype;
        Date.prototype.getTimezoneOffset = function() { return timezoneOffset; };

        // Remove automation traces
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;

        console.log('Stealth mode activated');
        """

        try:
            page.add_init_script(stealth_js)
            logger.info("Stealth scripts applied successfully")
        except Exception as e:
            logger.warning(f"Failed to apply stealth scripts: {e}")

    # Convenience methods
    def get_current_url(self):
        """Get current page URL"""
        return self.page.url if self.page else None

    def get_page_title(self):
        """Get current page title"""
        return self.page.title() if self.page else None

    def evaluate_js(self, script: str):
        """Evaluate JavaScript on the page"""
        if not self.page:
            return None
        return self.page.evaluate(script)

    def is_ready(self):
        """Check if browser operator is ready"""
        return self.page is not None

    def is_connected(self) -> bool:
        """Check if browser is connected"""
        if self.context:
            pages = self.context.pages
            return pages and not pages[0].is_closed()
        if self.browser:
            return self.browser.is_connected()
        return False

    def pause_operations(self):
        """Pause all browser operations"""
        logger.info("Pausing browser operations")
        self.pause()  # Call parent PlaywrightWrapper pause method

    def resume_operations(self):
        """Resume all browser operations"""
        logger.info("Resuming browser operations")
        self.resume()  # Call parent PlaywrightWrapper resume method

    def is_operations_paused(self) -> bool:
        """Check if browser operations are currently paused"""
        return self.is_paused()  # Call parent PlaywrightWrapper method

    def get_main_page(self, add_human_interaction_overlay: bool = True) -> Page:
        """Get the main page, ensuring only one page is open"""
        if not self.context:
            self.start()

        # Check if more than one page is open
        if len(self.context.pages) >= 1:
            # Close other pages
            for page in self.context.pages[1:]:
                page.close()
            self.page = self.context.pages[0]
            # Don't apply stealth scripts for CDP mode - profile is enough
            # Only apply route interception for CDP
            if not self.use_cdp:
                self._apply_stealth_scripts(self.page)
            self._setup_route_interception(self.page)
        else:
            self.page = self.context.new_page()
            # Apply stealth scripts and route interception to newly created pages
            if not self.use_cdp:
                self._apply_stealth_scripts(self.page)
            self._setup_route_interception(self.page)

        if add_human_interaction_overlay:
            self.add_human_interaction_overlay(self.page)

        # Update page reference in parent wrapper
        self.set_page(self.page)

        return self.page

    def add_human_interaction_overlay(self, page: Page):
        """Add the human interaction detection overlay"""
        overlay_path = os.path.join(os.path.dirname(__file__), "overlay.js")

        with open(overlay_path, "r", encoding="utf-8") as f:
            overlay_script = f.read()

        page.evaluate(overlay_script)
        logger.info("Human interaction overlay added")

    def add_overlay(
        self,
        page: Page,
        title: str = "",
        subtitle: str = "",
        messages: list[str] = [],
        timeout=8000,
    ):
        """
        Add a semi-transparent overlay with custom title, subtitle, message,
        and timer to the page.
        """

        overlay_script = """
            // Create the overlay container
            const overlay = document.createElement('div');
            overlay.style.position = 'fixed';
            overlay.style.top = '0';
            overlay.style.left = '0';
            overlay.style.width = '100vw';
            overlay.style.height = '100vh';
            overlay.style.backgroundColor = 'rgba(0, 0, 0, 0.8)';
            overlay.style.color = 'white';
            overlay.style.display = 'flex';
            overlay.style.flexDirection = 'column';
            overlay.style.justifyContent = 'center';
            overlay.style.alignItems = 'center';
            overlay.style.fontSize = '24px';
            overlay.style.zIndex = '9999';
            overlay.style.opacity = '1';
            overlay.style.transition = 'opacity 0.3s ease';
            overlay.style.pointerEvents = 'auto';
            overlay.id = 'custom-overlay';
        """

        if title:
            overlay_script += f"""
                const titleElement = document.createElement('div');
                titleElement.style.fontSize = '32px';
                titleElement.style.fontWeight = 'bold';
                titleElement.style.marginBottom = '10px';
                titleElement.innerText = `{title}`;
                overlay.appendChild(titleElement);
            """
        if subtitle:
            overlay_script += f"""
                const subtitleElement = document.createElement('div');
                subtitleElement.style.fontSize = '24px';
                subtitleElement.style.marginBottom = '10px';
                subtitleElement.innerText = `{subtitle}`;
                overlay.appendChild(subtitleElement);
            """
        if messages:
            for i, message in enumerate(messages):
                overlay_script += f"""
                    const messageElement{i} = document.createElement('div');
                    messageElement{i}.style.fontSize = '20px';
                    messageElement{i}.innerText = `{message}`;
                    overlay.appendChild(messageElement{i});
            """

        overlay_script += """
            // Create hover detection zone
            document.body.appendChild(overlay);
        """

        # Add timer to display remaining time and remove overlay
        overlay_script += f"""
            const timeout = {timeout};
            let remainingSeconds = Math.floor(timeout / 1000);

            // Create timer caption
            const timerCaption = document.createElement('div');
            timerCaption.style.fontSize = '14px';
            timerCaption.style.marginTop = '20px';
            timerCaption.style.opacity = '0.7';
            timerCaption.innerText = `Close in ${{remainingSeconds}} seconds...`;
            overlay.appendChild(timerCaption);

            // Update timer every second
            const countdownInterval = setInterval(() => {{
                remainingSeconds -= 1;
                if (remainingSeconds > 0) {{
                    timerCaption.innerText = `Close in ` +
                        `${{remainingSeconds}} seconds...`;
                }} else {{
                    clearInterval(countdownInterval);
                }}
            }}, 1000);

            // Remove overlay after timeout
            setTimeout(() => {{
                overlay.remove();
            }}, {timeout});
        """

        page.evaluate(overlay_script)
        time.sleep(timeout / 1000)
        return page

    def add_closing_overlay(self, page: Page):
        """Add overlay for human interaction detection"""
        self.add_overlay(page, "Detected Human Interaction", timeout=3000)

    def add_no_interaction_overlay(self, page: Page):
        """Add overlay indicating bot is working"""
        return self.add_overlay(
            page,
            "JobHuntr Bot is Working Its Magic!",
            "Sit back and relax, interviews are on the way.",
            [
                "Please avoid interacting with the browser window.",
                ("You can pause or stop the bot anytime " "from your control panel."),
            ],
        )

    def human_delay(self, min_seconds: float = 0.5, max_seconds: float = 2.0):
        """Add a random human-like delay"""
        delay = random.uniform(min_seconds, max_seconds)
        time.sleep(delay)

    def move_mouse_randomly(self, page: Page):
        """Move mouse to random position on page"""
        try:
            x = random.randint(200, 1700)
            y = random.randint(200, 900)
            page.mouse.move(x, y, steps=random.randint(5, 15))
            time.sleep(random.uniform(0.1, 0.3))
        except Exception as e:
            logger.debug(f"Failed to move mouse: {e}")

    def scroll_around(self, page: Page):
        """Scroll around the page randomly with human-like behavior"""
        logger.info("Scrolling around")
        start_time = time.time()

        try:
            # Get page dimensions
            body_box = page.locator("body").bounding_box()
            height = body_box.get("height", 1000) if body_box else 1000

            # Random number of scrolls
            num_scrolls = random.randint(3, 6)

            # Scroll down with varied speeds
            for i in range(num_scrolls):
                scroll_amount = random.randint(200, 500)
                page.mouse.wheel(delta_x=0, delta_y=scroll_amount)

                # Random delay between scrolls
                time.sleep(random.uniform(0.3, 0.8))

                # Occasionally move mouse
                if random.random() > 0.6:
                    self.move_mouse_randomly(page)

            # Pause at bottom
            time.sleep(random.uniform(1, 2))

            # Scroll back up (not always to top)
            scroll_back = random.randint(2, num_scrolls)
            for i in range(scroll_back):
                scroll_amount = random.randint(-500, -200)
                page.mouse.wheel(delta_x=0, delta_y=scroll_amount)
                time.sleep(random.uniform(0.3, 0.8))

        except Exception as e:
            logger.debug(f"Error during scroll: {e}")

        # Ensure we spend at least 3 seconds
        elapsed = time.time() - start_time
        if elapsed < 3:
            time.sleep(3 - elapsed)

    def take_screenshot(self, page: Page = None, path: str = None):
        """Take a screenshot of the current page"""
        if not page:
            page = self.page

        if not page:
            logger.error("No page available for screenshot")
            return None

        if not path:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            screenshot_name = f"screenshot_{timestamp}.png"
            path = os.path.join(self.screenshot_folder_path, screenshot_name)

        page.screenshot(path=path)
        logger.info(f"Screenshot saved: {path}")
        return path
