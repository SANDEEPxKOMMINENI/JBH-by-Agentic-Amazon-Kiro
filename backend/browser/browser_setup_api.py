"""
Browser setup API endpoints for chromium installation
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from browser.browser_executable_manager import (  # noqa: E402
    EXPECTED_CHROMIUM_VERSION,
    browser_manager,
)
from browser.profile_utils import (  # noqa: E402
    get_jobhuntr_profile_name,
    get_jobhuntr_profile_path,
)
from constants import BASE_DIR  # noqa: E402

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/browser", tags=["browser"])


@router.get("/health")
async def browser_api_health():
    """Health check for browser API"""
    return {
        "status": "healthy",
        "message": "Browser API is running",
        "endpoints": [
            "GET /api/browser/health - This health check",
            "GET /api/browser/check - Check if browser is available",
            "POST /api/browser/setup - Start browser setup process",
            "GET /api/browser/setup-status - Get setup progress",
            "GET /api/browser/setup-stream - Stream setup progress (SSE)",
            "POST /api/browser/reset-setup - Reset setup state",
        ],
    }


# Global state for tracking setup progress
setup_state = {
    "status": "idle",  # idle, checking, downloading, extracting, completed
    "progress": 0,
    "message": "",
    "error": None,
    "thread": None,
}

# Global list to track streaming clients
streaming_clients = []

PROFILE_CREATION_LOCK = threading.Lock()


class BrowserCheckResponse(BaseModel):
    browser_available: bool
    browser_type: str | None = None
    executable_path: str | None = None
    browser_version: str | None = None


class SetupStatusResponse(BaseModel):
    status: str
    progress: int
    message: str
    error: str | None = None


class JobhuntrProfileStatusResponse(BaseModel):
    profile_path: str
    profile_name: str
    profile_exists: bool
    chrome_available: bool
    needs_creation: bool
    created: bool = False
    last_modified: float | None = None


class ProfileEnsureRequest(BaseModel):
    user_email: str | None = None


class ManualLaunchRequest(BaseModel):
    url: str | None = None


# ---------------------------------------
# JobHuntr-specific Chrome profile status
# ---------------------------------------


def _jobhuntr_profile_dir(user_email: str | None = None) -> str:
    return get_jobhuntr_profile_path(user_email=user_email)


def _jobhuntr_profile_exists(path: str) -> bool:
    return os.path.exists(path) and _dir_has_profiles(path)


def _ensure_jobhuntr_profile_files(profile_dir: str):
    """Create the minimum structure needed for a dedicated JobHuntr Chrome profile."""
    os.makedirs(profile_dir, exist_ok=True)
    default_profile_dir = os.path.join(profile_dir, "Default")
    os.makedirs(default_profile_dir, exist_ok=True)

    local_state_path = os.path.join(profile_dir, "Local State")
    if not os.path.exists(local_state_path):
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
        with open(local_state_path, "w", encoding="utf-8") as file:
            json.dump(local_state, file, indent=2)

    preferences_path = os.path.join(default_profile_dir, "Preferences")
    if not os.path.exists(preferences_path):
        preferences = {
            "profile": {
                "name": "JobHuntr Profile",
                "avatar_index": 0,
                "exit_type": "Crashed",
            },
            "browser": {
                "check_default_browser": False,
                "show_home_button": True,
            },
            "session": {
                "restore_on_startup": 1,
                "startup_urls": [],
            },
            "download": {
                "directory_upgrade": True,
            },
            "extensions": {
                "settings": {},
            },
        }
        with open(preferences_path, "w", encoding="utf-8") as file:
            json.dump(preferences, file, indent=2)

    first_run_path = os.path.join(profile_dir, "First Run")
    if not os.path.exists(first_run_path):
        with open(first_run_path, "w", encoding="utf-8"):
            pass

    for relative in ["Extensions", "Storage", "Session Storage"]:
        os.makedirs(os.path.join(default_profile_dir, relative), exist_ok=True)


def _dir_has_profiles(path: str) -> bool:
    try:
        return any(
            os.path.isdir(os.path.join(path, entry))
            for entry in os.listdir(path)
            if entry == "Default" or entry.startswith("Profile ")
        )
    except Exception:
        return False


def _build_jobhuntr_profile_status(
    *, created: bool = False, user_email: str | None = None
) -> JobhuntrProfileStatusResponse:
    profile_path = _jobhuntr_profile_dir(user_email=user_email)
    profile_name = get_jobhuntr_profile_name(user_email=user_email)
    exists = _jobhuntr_profile_exists(profile_path)
    chrome_available = browser_manager.check_chrome_exist()
    last_modified = None
    if exists:
        try:
            last_modified = os.path.getmtime(profile_path)
        except OSError:
            last_modified = None

    return JobhuntrProfileStatusResponse(
        profile_path=profile_path,
        profile_name=profile_name,
        profile_exists=exists,
        chrome_available=chrome_available,
        needs_creation=not exists,
        created=created,
        last_modified=last_modified,
    )


@router.get("/profile/status", response_model=JobhuntrProfileStatusResponse)
async def get_jobhuntr_profile_status(user_email: str | None = None):
    """Return JobHuntr Chrome profile status (Chrome availability + dedicated profile)."""
    return _build_jobhuntr_profile_status(user_email=user_email)


@router.post("/profile/ensure", response_model=JobhuntrProfileStatusResponse)
async def ensure_jobhuntr_profile(payload: ProfileEnsureRequest | None = None):
    """
    Ensure the JobHuntr Chrome profile exists inside BASE_DIR.

    Returns the updated profile status. If the profile already exists,
    the response will indicate no creation was needed.
    """
    payload = payload or ProfileEnsureRequest()
    user_email = payload.user_email
    with PROFILE_CREATION_LOCK:
        profile_path = _jobhuntr_profile_dir(user_email=user_email)
        exists = _jobhuntr_profile_exists(profile_path)
        if not exists:
            _ensure_jobhuntr_profile_files(profile_path)
            # Touch the directory to update modified time
            try:
                os.utime(profile_path, times=(time.time(), time.time()))
            except OSError:
                pass
            return _build_jobhuntr_profile_status(created=True, user_email=user_email)

    return _build_jobhuntr_profile_status(created=False, user_email=user_email)


@router.post("/manual-launch")
async def manual_launch_browser(request: ManualLaunchRequest | None = None):
    """Launch Chrome using the JobHuntr profile from the backend side."""
    chrome_path = browser_manager.get_chrome_executable_path()
    if not chrome_path or not os.path.exists(chrome_path):
        raise HTTPException(
            status_code=400, detail="Google Chrome not found on this system."
        )

    profile_path = _jobhuntr_profile_dir()
    try:
        os.makedirs(profile_path, exist_ok=True)
    except OSError as exc:
        logger.error(f"Failed to prepare JobHuntr profile directory: {exc}")
        raise HTTPException(
            status_code=500, detail="Unable to prepare JobHuntr profile directory."
        )

    chrome_args = [
        f"--user-data-dir={profile_path}",
        "--profile-directory=Default",
        "--no-default-browser-check",
        "--no-first-run",
    ]

    if request and request.url:
        chrome_args.append(request.url)

    try:
        logger.info(
            "Launching manual Chrome session with profile %s (url=%s)",
            profile_path,
            request.url if request else None,
        )
        if sys.platform == "darwin":
            app_path = os.path.abspath(os.path.join(chrome_path, "../../.."))
            subprocess.Popen(
                ["open", "-na", app_path, "--args", *chrome_args],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        else:
            subprocess.Popen(
                [chrome_path, *chrome_args],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        return {"success": True}
    except Exception as exc:
        logger.error(f"Failed to launch Chrome with JobHuntr profile: {exc}")
        raise HTTPException(
            status_code=500, detail="Failed to launch Chrome with JobHuntr profile."
        )


@router.post("/close-all")
async def close_all_chrome():
    """Force close all Chrome processes across platforms."""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/IM", "chrome.exe", "/F", "/T"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        elif sys.platform == "darwin":
            subprocess.run(
                ["pkill", "-f", "Google Chrome"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            subprocess.run(
                ["pkill", "-f", "chrome"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        return {"success": True}
    except Exception as exc:
        logger.error(f"Failed to close Chrome processes: {exc}")
        raise HTTPException(status_code=500, detail="Failed to close Chrome processes.")


# -----------------------------
# Chrome profile copy (Windows)
# -----------------------------
class ProfileCopyStatusResponse(BaseModel):
    is_windows: bool
    is_mac: bool | None = None
    platform: str | None = None
    source_dir: str | None = None
    dest_dir: str | None = None
    exists: bool = False
    locked: bool = False
    needs_copy: bool = False
    status: str | None = None
    progress: int | None = None
    message: str | None = None
    error: str | None = None


def update_setup_progress(status: str, progress: int, message: str, error: str = None):
    """Update the global setup state and notify streaming clients"""
    setup_state.update(
        {"status": status, "progress": progress, "message": message, "error": error}
    )
    logger.info(f"Setup progress: {status} - {progress}% - {message}")

    # Notify all streaming clients
    progress_data = {
        "status": status,
        "progress": progress,
        "message": message,
        "error": error,
    }

    # Send to all connected streaming clients
    # Create a copy to avoid modification during iteration
    for client_queue in streaming_clients[:]:
        try:
            client_queue.put_nowait(progress_data)
        except Exception:
            # Remove disconnected clients
            streaming_clients.remove(client_queue)


def setup_browser_thread():
    """Run browser setup in a separate thread"""
    try:
        update_setup_progress("checking", 10, "Checking browser installation")

        # Check if Chromium already exists
        status = browser_manager.get_chromium_status(log_details=True)
        if status["is_ready"]:
            update_setup_progress("completed", 100, "Chromium already available")
            return

        update_setup_progress("downloading", 20, "Starting browser download")

        # Create a progress callback
        def progress_callback(progress_percent: int):
            msg = f"Downloading browser... {progress_percent}%"
            update_setup_progress("downloading", min(progress_percent, 80), msg)

        # Download chromium
        browser_manager.download_chromium(progress_callback)

        update_setup_progress("extracting", 90, "Extracting browser files")

        # Verify installation
        status = browser_manager.get_chromium_status(log_details=True)
        if status["is_ready"]:
            msg = "Chromium setup completed successfully"
            update_setup_progress("completed", 100, msg)
        else:
            error_msg = "Chromium installation verification failed"
            update_setup_progress("error", 0, "Chromium setup failed", error_msg)

    except Exception as e:
        logger.error(f"Browser setup failed: {e}")
        update_setup_progress("error", 0, "Browser setup failed", str(e))


@router.get("/check", response_model=BrowserCheckResponse)
async def check_browser():
    """Check if Chromium is actually installed in the target location"""
    try:
        # Use browser_manager to check if Chromium exists in target location
        chrome_available = browser_manager.check_chrome_exist()
        executable_path = (
            browser_manager.get_chrome_executable_path() if chrome_available else None
        )
        browser_version = "Chrome ready" if chrome_available else "Chrome missing"
        browser_type = "chrome" if chrome_available else None
        browser_available = chrome_available

        return BrowserCheckResponse(
            browser_available=browser_available,
            browser_type=browser_type,
            executable_path=executable_path,
            browser_version=browser_version,
        )
    except Exception as e:
        logger.error(f"Browser check failed: {e}")
        detail = f"Browser check failed: {str(e)}"
        raise HTTPException(status_code=500, detail=detail)


@router.post("/setup")
async def start_browser_setup():
    """Start browser setup process"""
    try:
        # Check if setup is already running
        running_states = ["checking", "downloading", "extracting"]
        if setup_state["status"] in running_states:
            return {
                "message": "Setup already in progress",
                "status": setup_state["status"],
            }

        # Reset state
        setup_state.update(
            {
                "status": "checking",
                "progress": 0,
                "message": "Starting browser setup...",
                "error": None,
            }
        )

        # Start setup in background thread
        setup_thread = threading.Thread(target=setup_browser_thread, daemon=True)
        setup_thread.start()
        setup_state["thread"] = setup_thread

        return {"message": "Browser setup started", "status": "checking"}

    except Exception as e:
        logger.error(f"Failed to start browser setup: {e}")
        detail = f"Failed to start browser setup: {str(e)}"
        raise HTTPException(status_code=500, detail=detail)


@router.get("/setup-status", response_model=SetupStatusResponse)
async def get_setup_status():
    """Get current setup status"""
    return SetupStatusResponse(
        status=setup_state["status"],
        progress=setup_state["progress"],
        message=setup_state["message"],
        error=setup_state["error"],
    )


@router.post("/reset-setup")
async def reset_setup():
    """Reset setup state (for debugging)"""
    setup_state.update(
        {"status": "idle", "progress": 0, "message": "", "error": None, "thread": None}
    )
    return {"message": "Setup state reset"}


@router.get("/setup-stream")
async def stream_setup_progress():
    """Stream setup progress using Server-Sent Events (SSE)"""
    import queue  # noqa: E402

    # Create a queue for this client
    client_queue = queue.Queue()
    streaming_clients.append(client_queue)

    async def event_stream():
        try:
            # Send current state immediately
            current_state = {
                "status": setup_state["status"],
                "progress": setup_state["progress"],
                "message": setup_state["message"],
                "error": setup_state["error"],
            }
            yield f"data: {json.dumps(current_state)}\n\n"

            # Stream updates
            while True:
                try:
                    # Wait for new progress updates
                    # (with timeout to keep connection alive)
                    try:
                        # 30 second timeout
                        progress_data = client_queue.get(timeout=30)
                        yield f"data: {json.dumps(progress_data)}\n\n"

                        # If setup is completed or errored, close the stream
                        if progress_data["status"] in ["completed", "error"]:
                            break

                    except queue.Empty:
                        # Send keepalive ping
                        keepalive_data = {"keepalive": True}
                        yield f"data: {json.dumps(keepalive_data)}\n\n"

                except Exception as e:
                    logger.error(f"Error in event stream: {e}")
                    break

        except Exception as e:
            logger.error(f"Error in stream setup: {e}")
        finally:
            # Clean up - remove client from list
            if client_queue in streaming_clients:
                streaming_clients.remove(client_queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
        },
    )
