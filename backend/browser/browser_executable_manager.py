"""
This module is used to manage the browser.
- check if chrome is installed
- download and install playwright chromium browser
- return current executable path of the browser

"""

import logging
import os
import shutil
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import zipfile  # noqa: E402
from enum import Enum  # noqa: E402

import requests  # noqa: E402  # pylint: disable=import-error

from constants import IS_MAC, IS_WINDOWS, PLAYWRIGHT_DOWNLOAD_URL  # noqa: E402

logger = logging.getLogger(__name__)

EXPECTED_CHROMIUM_VERSION = "chromium-1169"


class BrowserName(Enum):
    CHROME = "chrome"
    CHROMIUM = "chromium"


class BrowserManager:
    def __init__(self):
        self.chrome_path = self.get_chrome_path()
        self.chromium_path = self.get_playwright_path()
        self.executable_path = None
        self.user_data_path = None
        self.browser_name: BrowserName = None
        self.browser_exist = False
        self.browser_executable_path = None
        self.last_detected_chromium_version: str | None = None

    def prepare_browser_executable_path(self, update_status_signal=None) -> str | None:
        logger.info("Preparing bundled Chromium executable...")

        _, executable_path, is_ready = self._detect_chromium_install(log_details=True)

        if not is_ready:
            logger.info(
                "Chromium missing or mismatched version, downloading bundled browser..."
            )
            self.download_chromium(update_status_signal)
            _, executable_path, is_ready = self._detect_chromium_install(
                log_details=True
            )

        self.executable_path = executable_path
        self.browser_name = BrowserName.CHROMIUM
        self.browser_exist = bool(self.executable_path and is_ready)

        if not self.executable_path:
            logger.error("Chromium executable not found after preparation")
            return None

        # Set PLAYWRIGHT_BROWSERS_PATH to the playwright browsers directory, not executable
        playwright_browsers_path = self.get_playwright_path()
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = playwright_browsers_path
        logger.info(f"Set PLAYWRIGHT_BROWSERS_PATH to: {playwright_browsers_path}")

        self.user_data_path = self.get_user_data_path()

        return self.executable_path

    def prepare_user_persistent_data_path(self):
        # if is windows, don't need to do anything, because windows
        # requires user to quick chrome to create the user data path
        if not self.browser_name == BrowserName.CHROME:
            logger.warning("Only chrome is supported for user persistent data path")
            return
        if IS_WINDOWS:
            return
        # if is mac, copy the user data from Program Files to Local App Data
        return self.user_data_path

    def check_browser_exist(self) -> bool:
        chromium_status = self.get_chromium_status()
        return self.check_chrome_exist() or chromium_status["is_ready"]

    def check_chrome_exist(self):
        """
        Get the path to Chrome based on the platform.

        Returns:
            str: The path to Chrome executable
        """
        result = False
        if IS_WINDOWS:
            # Use standard Windows Program Files path
            program_files = "C:\\Program Files"
            chrome_path = os.path.join(
                program_files,
                "Google",
                "Chrome",
                "Application",
                "chrome.exe",
            )
        elif IS_MAC:
            chrome_path = os.path.expanduser(
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            )

        if os.path.exists(chrome_path):
            result = True

        return result

    def _detect_chromium_install(self, *, log_details: bool = False):
        """
        Locate the locally cached Chromium build and return its version and executable path.
        """
        playwright_path = self.get_playwright_path()
        self.last_detected_chromium_version = None

        if not os.path.exists(playwright_path):
            return None, None, False

        preferred_version = EXPECTED_CHROMIUM_VERSION
        chromium_folder = None

        expected_path = os.path.join(playwright_path, preferred_version)
        if os.path.isdir(expected_path):
            chromium_folder = preferred_version
        else:
            try:
                for item in os.listdir(playwright_path):
                    if item.startswith("chromium-") and os.path.isdir(
                        os.path.join(playwright_path, item)
                    ):
                        chromium_folder = item
                        break
            except OSError:
                pass

        if not chromium_folder:
            return None, None, False

        self.last_detected_chromium_version = chromium_folder
        is_expected_build = chromium_folder == preferred_version

        executable_path = None
        try:
            if IS_WINDOWS:
                executable_path = os.path.join(
                    playwright_path, chromium_folder, "chrome-win", "chrome.exe"
                )
            elif IS_MAC:
                executable_path = os.path.join(
                    playwright_path,
                    chromium_folder,
                    "chrome-mac",
                    "Chromium.app",
                    "Contents",
                    "MacOS",
                    "Chromium",
                )
            else:  # Linux
                executable_path = os.path.join(
                    playwright_path, chromium_folder, "chrome-linux", "chrome"
                )

            if executable_path and not os.path.exists(executable_path):
                executable_path = None
        except OSError:
            executable_path = None

        if log_details and chromium_folder:
            if executable_path:
                logger.info(
                    "Detected Chromium build %s at %s",
                    chromium_folder,
                    executable_path,
                )
            else:
                logger.warning(
                    "Detected Chromium build %s but executable path is missing",
                    chromium_folder,
                )

            if not is_expected_build:
                logger.warning(
                    "Chromium version mismatch detected: %s (expected %s)",
                    chromium_folder,
                    EXPECTED_CHROMIUM_VERSION,
                )

        return (
            chromium_folder,
            executable_path,
            bool(executable_path and is_expected_build),
        )

    def get_chromium_status(self, *, log_details: bool = False):
        version, executable_path, is_ready = self._detect_chromium_install(
            log_details=log_details
        )
        return {
            "is_ready": is_ready,
            "version": version,
            "executable_path": executable_path,
        }

    def download_chromium(self, update_status_callback=None):
        try:
            # Ensure the playwright browser directory exists before download
            status = self.get_chromium_status()
            if not status["is_ready"]:
                os.makedirs(self.chromium_path, exist_ok=True)

            # Download the playwright browser
            response = requests.get(PLAYWRIGHT_DOWNLOAD_URL, stream=True)
            response.raise_for_status()  # Raise an exception for HTTP errors

            # Get total size for progress tracking
            total_size = int(response.headers.get("content-length", 0))
            total_size_mb = total_size / 1024 / 1024
            downloaded_size = 0
            last_progress_time = time.time()

            # Download to a temporary file first
            temp_zip_path = os.path.join(self.chromium_path, "chromium.zip")
            with open(temp_zip_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)

                        # Update progress every 0.5 seconds or at significant milestones
                        current_time = time.time()
                        if (
                            current_time - last_progress_time > 0.5
                            or downloaded_size == total_size
                        ):
                            progress_percent = (
                                int((downloaded_size / total_size) * 80)
                                if total_size > 0
                                else 20
                            )  # Cap at 80% for download
                            downloaded_mb = downloaded_size / 1024 / 1024

                            if update_status_callback:
                                update_status_callback(progress_percent)

                            logger.info(
                                "Downloading Playwright browser... "
                                f"{round(downloaded_mb, 2)}/"
                                f"{round(total_size_mb, 2)}MB "
                                f"({progress_percent}%)"
                            )
                            last_progress_time = current_time

            # Extract the zip file
            if update_status_callback:
                update_status_callback(85)
            logger.info("Extracting Playwright browser...")

            # Use the built-in zipfile module which works on all platforms
            with zipfile.ZipFile(temp_zip_path, "r") as zip_ref:
                zip_ref.extractall(self.chromium_path)

            # Clean up the zip file
            os.remove(temp_zip_path)

            if update_status_callback:
                update_status_callback(95)

            # Set permissions on Windows
            if IS_WINDOWS:
                # On Windows, we need to ensure the executable has proper permissions
                chromium_exe_path = os.path.join(
                    self.chromium_path, "chromium", "chrome-win", "chrome.exe"
                )
                if os.path.exists(chromium_exe_path):
                    # Make sure the file is executable
                    import stat  # noqa: E402

                    os.chmod(
                        chromium_exe_path,
                        os.stat(chromium_exe_path).st_mode | stat.S_IEXEC,
                    )
                    logger.info("Permissions updated successfully.")
            elif IS_MAC:
                # On macOS/Linux, use chmod
                chromium_path = os.path.join(
                    self.chromium_path,
                    EXPECTED_CHROMIUM_VERSION,
                    "chrome-mac",
                    "Chromium.app",
                )
                try:
                    try:
                        subprocess.run(
                            ["chmod", "-R", "+x", chromium_path],
                            check=True,
                            encoding="utf-8",
                            errors="replace",
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to run with UTF-8 encoding: {e}, "
                            "falling back to system default encoding"
                        )
                        subprocess.run(["chmod", "-R", "+x", chromium_path], check=True)
                    logger.info("Permissions updated successfully.")
                except subprocess.CalledProcessError as e:
                    logger.error(f"Failed to update permissions: {e}")
            else:
                logger.warning(
                    "Unsupported platform for Playwright browser installation."
                )
                return 1
            return 0
        except Exception as e:
            logger.error(f"Failed to download Playwright browser: {e}")
            # Clean up on failure
            if os.path.exists(self.chromium_path):
                shutil.rmtree(self.chromium_path)
            return 1

    def get_chrome_path(self) -> str:
        """
        Get the path to Chrome based on the platform.

        Returns:
            str: The path to Chrome executable
        """
        if IS_WINDOWS:
            # Use standard Windows Program Files path
            program_files = "C:\\Program Files"
            return os.path.join(
                program_files,
                "Google",
                "Chrome",
                "Application",
                "chrome.exe",
            )
        elif IS_MAC:
            return os.path.expanduser(
                "~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            )
        else:
            return None

    def get_playwright_path(self) -> str:
        """
        Get the correct Playwright browser path based on the platform.

        Returns:
            str: The path where Playwright browsers should be installed
        """
        if IS_WINDOWS:
            # Use standard Windows AppData Local path
            return os.path.join(
                os.path.expanduser("~"), "AppData", "Local", "ms-playwright"
            )
        elif IS_MAC:
            # On macOS/Linux, use ~/Library/Caches/ms-playwright
            return os.path.expanduser("~/Library/Caches/ms-playwright")
        else:
            raise ValueError(f"Unsupported platform: {sys.platform}")

    def get_chrome_user_data_dir(self) -> str | None:
        """
        Get the default Chrome user data directory (parent folder containing profiles).
        Returns:
            str: The path to Chrome's User Data directory, or None if not found
        """
        if IS_WINDOWS:
            user_data_dir = os.path.join(
                os.path.expanduser("~"),
                "AppData",
                "Local",
                "Google",
                "Chrome",
                "User Data",
            )
        elif IS_MAC:
            user_data_dir = os.path.expanduser(
                "~/Library/Application Support/Google/Chrome"
            )
        else:
            return None

        # Check if the directory exists
        if os.path.exists(user_data_dir):
            return user_data_dir
        return None

    def get_most_recent_chrome_profile(self) -> tuple[str | None, str | None]:
        """
        Get the most recently used Chrome profile.
        Returns:
            tuple: (user_data_dir, profile_name) or (None, None) if not found
        """
        user_data_dir = self.get_chrome_user_data_dir()
        if not user_data_dir:
            return None, None

        # Try to read Local State to find the last active profile
        local_state_path = os.path.join(user_data_dir, "Local State")
        profile_name = None

        if os.path.exists(local_state_path):
            try:
                import json

                with open(local_state_path, "r", encoding="utf-8") as f:
                    local_state = json.load(f)
                    # Chrome stores profile info in different structures
                    # Try to get last_used from profile.info_cache or profile.last_used
                    profile_info = local_state.get("profile", {})
                    if isinstance(profile_info, dict):
                        last_used = profile_info.get("last_used")
                        if last_used:
                            profile_name = last_used
                        else:
                            # Check info_cache for profiles
                            info_cache = profile_info.get("info_cache", {})
                            if info_cache:
                                # Get the most recently used from info_cache
                                profiles = list(info_cache.keys())
                                if profiles:
                                    # Default is usually the first/main profile
                                    profile_name = (
                                        "Default"
                                        if "Default" in profiles
                                        else profiles[0]
                                    )
            except Exception as e:
                logger.warning(f"Could not read Chrome Local State: {e}")

        # If we found a profile name, verify it exists
        if profile_name:
            profile_dir = os.path.join(user_data_dir, profile_name)
            if os.path.exists(profile_dir):
                return user_data_dir, profile_name

        # Fallback: find most recently modified profile directory
        try:
            profiles = []
            for item in os.listdir(user_data_dir):
                item_path = os.path.join(user_data_dir, item)
                if os.path.isdir(item_path) and (
                    item == "Default" or item.startswith("Profile ")
                ):
                    # Check modification time of the profile directory
                    mtime = os.path.getmtime(item_path)
                    profiles.append((mtime, item))

            if profiles:
                # Sort by modification time (most recent first)
                profiles.sort(reverse=True)
                profile_name = profiles[0][1]
                return user_data_dir, profile_name
        except Exception as e:
            logger.warning(f"Could not find Chrome profiles: {e}")

        # Final fallback to Default profile if it exists
        default_profile = os.path.join(user_data_dir, "Default")
        if os.path.exists(default_profile):
            return user_data_dir, "Default"

        return None, None

    def get_user_data_path(self) -> str:
        """
        Get the default Chrome user profile path based on the platform.
        Returns:
            str: The path to the default Chrome user profile
        """
        if IS_WINDOWS:
            # Use standard Windows AppData Local path
            new_profile_path = os.path.join(
                os.path.expanduser("~"),
                "AppData",
                "Local",
                "jobhuntr",
                "Chrome",
                "User Data",
            )
            return new_profile_path
        elif IS_MAC:
            return os.path.expanduser(
                "~/Library/Application Support/Google/Chrome/Default"
            )
        else:
            raise ValueError(f"Unsupported platform: {sys.platform}")

    def get_chrome_executable_path(self):
        """Get Chrome executable path, checking multiple common locations"""
        if IS_WINDOWS:
            # Check multiple common Windows locations
            possible_paths = [
                os.path.join(
                    "C:\\Program Files", "Google", "Chrome", "Application", "chrome.exe"
                ),
                os.path.join(
                    "C:\\Program Files (x86)",
                    "Google",
                    "Chrome",
                    "Application",
                    "chrome.exe",
                ),
                os.path.join(
                    os.path.expanduser("~"),
                    "AppData",
                    "Local",
                    "Google",
                    "Chrome",
                    "Application",
                    "chrome.exe",
                ),
            ]

            for path in possible_paths:
                if os.path.exists(path):
                    logger.info(f"Found Chrome at: {path}")
                    return path

            # Return default path even if not found (caller will check existence)
            return possible_paths[0]
        elif IS_MAC:
            return os.path.expanduser(
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            )
        else:
            return None

    def get_chromium_executable_path(self):
        """Get the Chromium executable path for Playwright"""
        _, executable_path, _ = self._detect_chromium_install()
        return executable_path


browser_manager = BrowserManager()


if __name__ == "__main__":
    browser_manager.prepare_browser_executable_path()
