#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LinkedIn Bot REST API Server with Activity Polling
"""

import os

# CRITICAL: Set UTF-8 encoding for Windows console to handle emojis in logs
import sys

import requests

# Fix Windows console encoding issues with emojis
if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# Set the Playwright browsers path to the system-wide location
if sys.platform == "darwin":  # macOS
    PLAYWRIGHT_BROWSERS_PATH = os.path.expanduser("~/Library/Caches/ms-playwright")
elif sys.platform == "win32":  # Windows
    PLAYWRIGHT_BROWSERS_PATH = os.path.join(
        os.path.expanduser("~"), "AppData", "Local", "ms-playwright"
    )
else:
    PLAYWRIGHT_BROWSERS_PATH = os.path.expanduser("~/.cache/ms-playwright")

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = PLAYWRIGHT_BROWSERS_PATH

# Note: Automation library (playwright) is handled centrally in
# backend/browser/automation.py. No aliasing or early module patching is
# performed here to keep initialization simple and predictable.

import json
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel  # noqa: E402

from autonomous_search_bot.autonomous_search_controller import (  # noqa: E402
    autonomous_search_controller,
)

# Import browser setup API
from browser.browser_setup_api import router as browser_router  # noqa: E402

# Import config for BetterStack credentials
from config import BETTERSTACK_INGESTING_HOST, BETTERSTACK_SOURCE_TOKEN  # noqa: E402
from constants import SERVICE_GATEWAY_URL  # noqa: E402

# Import Dice bot controller
from dice_bot.dice_bot_controller import dice_bot_controller  # noqa: E402

# Import Glassdoor bot controller
from glassdoor_bot.glassdoor_bot_controller import (  # noqa: E402
    glassdoor_bot_controller,
)

# Import Indeed bot controller
from indeed_bot.indeed_bot_controller import indeed_bot_controller  # noqa: E402
from infinite_hunt.auto_infinite_hunt_monitor import (  # noqa: E402
    get_auto_infinite_hunt_monitor,
    initialize_auto_infinite_hunt_monitor,
)
from infinite_hunt.manager import initialize_infinite_hunt_manager  # noqa: E402

# Import LinkedIn bot controller (we'll modify this)
from linkedin_bot.linkedin_bot_controller import linkedin_bot_controller  # noqa: E402

# Import logger initialization
from logger import initialize_logging  # noqa: E402

# Import auth helper for JWT token management
from services.auth_helper import auth_helper  # noqa: E402
from services.supabase_client import supabase_client  # noqa: E402
from shared.infinite_hunt_metadata import get_metadata_service  # noqa: E402
from ziprecruiter_bot.ziprecruiter_bot_controller import (  # noqa: E402
    ziprecruiter_bot_controller,
)

# Import utilities

WORKFLOW_CONTROL_ALIASES = {}

WORKFLOW_CONTROLLER_MAP = {
    "linkedin-apply": {
        "pause": linkedin_bot_controller.pause_hunting_controller,
        "resume": linkedin_bot_controller.resume_hunting_controller,
        "stop": linkedin_bot_controller.stop_hunting_controller,
    },
    "indeed-search": {
        "pause": indeed_bot_controller.pause_searching_controller,
        "resume": indeed_bot_controller.resume_searching_controller,
        "stop": indeed_bot_controller.stop_searching_controller,
    },
    "ziprecruiter-search": {
        "pause": ziprecruiter_bot_controller.pause_searching_controller,
        "resume": ziprecruiter_bot_controller.resume_searching_controller,
        "stop": ziprecruiter_bot_controller.stop_searching_controller,
    },
    "glassdoor-search": {
        "pause": glassdoor_bot_controller.pause_searching_controller,
        "resume": glassdoor_bot_controller.resume_searching_controller,
        "stop": glassdoor_bot_controller.stop_searching_controller,
    },
    "dice-search": {
        "pause": dice_bot_controller.pause_searching_controller,
        "resume": dice_bot_controller.resume_searching_controller,
        "stop": dice_bot_controller.stop_searching_controller,
    },
    "autonomous-auto-search": {
        "stop": autonomous_search_controller.stop_autonomous_search,
    },
}


# Initialize BetterStack logging (always enabled)
initialize_logging(
    betterstack_token=BETTERSTACK_SOURCE_TOKEN,
    betterstack_host=BETTERSTACK_INGESTING_HOST,
)

# Get logger instance
logger = logging.getLogger(__name__)


# Lifespan event handler
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    # Startup: Initialize background managers
    manager = initialize_infinite_hunt_manager()

    # Initialize auto infinite hunt monitor (auto-start every 30 min if enabled)
    auto_hunt_monitor = initialize_auto_infinite_hunt_monitor(supabase_client, manager)
    auto_hunt_monitor.start()
    logger.info("Auto infinite hunt monitor started")

    # Reset infinite hunt status in database to 'stopped' on backend restart
    # This prevents the frontend from showing stale 'running' status
    try:
        supabase_client.update_infinite_run_state(status="stopped")
        logger.info("Reset infinite hunt status to 'stopped' on backend startup")
    except Exception as e:
        logger.warning(f"Failed to reset infinite hunt status on startup: {e}")

    yield
    # Shutdown: Ensure background managers stop cleanly
    auto_hunt_monitor.stop()
    logger.info("Auto infinite hunt monitor stopped")
    manager.stop()


# Create FastAPI app with lifespan handler
app = FastAPI(
    title="LinkedIn Bot REST API",
    description="REST API for LinkedIn bot control with activity polling",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include browser setup router
app.include_router(browser_router)


# Pydantic models for REST API
class StartHuntingRequest(BaseModel):
    linkedin_starter_url: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class StartSearchingRequest(BaseModel):
    indeed_starter_url: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class BotStatusResponse(BaseModel):
    success: bool
    bot_id: Optional[str] = None
    is_running: bool = False
    status: str = "unknown"
    current_url: Optional[str] = None
    has_browser: bool = False
    has_page: bool = False
    message: Optional[str] = None
    error: Optional[str] = None
    timestamp: Optional[str] = None
    workflow_run_id: Optional[str] = None


@app.get("/")
def root():
    """Health check endpoint"""
    return {"message": "LinkedIn Bot REST API is running", "status": "healthy"}


@app.get("/status")
def status():
    """Server status endpoint"""
    return {"status": "healthy", "message": "Server is running"}


def _control_latest_run(action: str) -> Dict[str, Any]:
    """
    Control (pause/resume/stop) the currently active workflow run.
    Uses cached run info from the manager instead of fetching from database.
    """
    # Get the active run from the manager's cache
    manager = initialize_infinite_hunt_manager()
    active_run = manager.get_active_run()

    if not active_run:
        raise HTTPException(
            status_code=404, detail="No active workflow run found in infinite hunt"
        )

    run_id, agent_run_template_name = active_run

    # Get the controller action
    workflow_key = WORKFLOW_CONTROL_ALIASES.get(
        agent_run_template_name, agent_run_template_name
    )
    controller_actions = WORKFLOW_CONTROLLER_MAP.get(workflow_key)
    if not controller_actions or action not in controller_actions:
        raise HTTPException(
            status_code=400,
            detail=f"{action.capitalize()} is not supported for workflow {agent_run_template_name}",
        )

    # Call the controller function directly with workflow_run_id
    control_fn = controller_actions[action]
    try:
        controller_result = control_fn(run_id)
    except Exception as exc:
        logger.error(
            "Failed to %s workflow %s: %s", action, agent_run_template_name, exc
        )
        raise HTTPException(
            status_code=500, detail=f"Unable to {action} the active agent run: {exc}"
        )

    if isinstance(controller_result, dict):
        success = controller_result.get("success", False)
        message = controller_result.get("message")
    else:
        success = bool(controller_result)
        message = None

    if not success:
        raise HTTPException(
            status_code=500,
            detail=message or f"Controller failed to {action} the active agent run",
        )

    return {
        "success": True,
        "workflow_run_id": run_id,
        "agent_run_template_name": agent_run_template_name,
        "message": message,
    }


# REST API endpoints for Infinite Hunt control
def _kill_chrome_processes():
    """Kill all Chrome processes to prevent profile lock issues"""
    try:
        import platform
        import subprocess

        system = platform.system().lower()
        logger.info(f"Killing Chrome processes on {system}")

        if system == "darwin":  # macOS
            # Kill Chrome processes
            subprocess.run(
                ["pkill", "-9", "Google Chrome"], check=False, capture_output=True
            )
            subprocess.run(
                ["pkill", "-9", "Chromium"], check=False, capture_output=True
            )
            logger.info("Killed Chrome processes on macOS")
        elif system == "linux":
            subprocess.run(["pkill", "-9", "chrome"], check=False, capture_output=True)
            subprocess.run(
                ["pkill", "-9", "chromium"], check=False, capture_output=True
            )
            logger.info("Killed Chrome processes on Linux")
        elif system == "windows":
            subprocess.run(
                ["taskkill", "/F", "/IM", "chrome.exe"],
                check=False,
                capture_output=True,
            )
            subprocess.run(
                ["taskkill", "/F", "/IM", "chromium.exe"],
                check=False,
                capture_output=True,
            )
            logger.info("Killed Chrome processes on Windows")

        # Brief pause to allow processes to terminate
        import time

        time.sleep(1)

    except Exception as e:
        logger.warning(f"Failed to kill Chrome processes: {e}")
        # Don't fail the start operation if Chrome kill fails


@app.post("/api/infinite-hunt/start")
async def start_infinite_hunt():
    """Start the infinite hunt background manager"""
    try:
        logger.info("Starting infinite hunt manager")

        # Kill any existing Chrome processes to prevent profile lock
        _kill_chrome_processes()

        manager = initialize_infinite_hunt_manager()
        manager.start()

        # Update database status to running
        supabase_client.update_infinite_run_state(status="running")
        logger.info("Infinite hunt manager started and status set to running")

        return {
            "success": True,
            "message": "Infinite hunt manager started successfully",
        }
    except Exception as e:
        logger.error(f"Failed to start infinite hunt: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/infinite-hunt/pause")
async def pause_infinite_hunt():
    """Pause the latest infinite hunt agent run"""
    control_info = _control_latest_run("pause")
    supabase_client.update_infinite_run_state(status="paused")
    return {
        "success": True,
        "message": "Infinite hunt paused",
        "run_id": control_info["workflow_run_id"],
        "agent_run_template_name": control_info["agent_run_template_name"],
    }


@app.post("/api/infinite-hunt/resume")
async def resume_infinite_hunt():
    """Resume the latest infinite hunt agent run"""
    control_info = _control_latest_run("resume")
    supabase_client.update_infinite_run_state(status="running")
    return {
        "success": True,
        "message": "Infinite hunt resumed",
        "run_id": control_info["workflow_run_id"],
        "agent_run_template_name": control_info["agent_run_template_name"],
    }


@app.post("/api/infinite-hunt/stop")
async def stop_infinite_hunt():
    """Stop the infinite hunt background manager and latest agent run (master stop button)"""
    stopped_run_id = None
    stopped_agent_run_template_name = None

    # Step 1: Try to stop the active agent run if there is one
    try:
        logger.info("Attempting to stop active infinite hunt agent run")
        control_info = _control_latest_run("stop")
        stopped_run_id = control_info["workflow_run_id"]
        stopped_agent_run_template_name = control_info["agent_run_template_name"]
        logger.info(f"Stopped active agent run: {stopped_run_id}")
    except HTTPException as http_exc:
        # No active run found - this is OK, just log it
        if http_exc.status_code == 404:
            logger.info("No active agent run to stop")
        else:
            logger.warning(f"Failed to stop active agent run: {http_exc.detail}")
    except Exception as exc:
        # Non-fatal - log but continue with manager stop
        logger.warning(f"Error stopping active agent run: {exc}")

    # Step 2: Stop the infinite hunt manager (always do this)
    try:
        logger.info("Stopping infinite hunt manager")
        manager = initialize_infinite_hunt_manager()
        manager.stop()
        logger.info("Infinite hunt manager stopped successfully")
    except Exception as exc:
        logger.warning(f"Failed to stop infinite hunt manager cleanly: {exc}")

    # Step 3: Update database status to 'stopped' (always do this)
    try:
        supabase_client.update_infinite_run_state(
            status="stopped",
        )
        logger.info("Updated infinite hunt database status to 'stopped'")
    except Exception as exc:
        logger.error(f"Failed to update database status: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Stopped manager but failed to update database status: {exc}",
        )

    # Step 4: Update the workflow run status to 'stopped' if we have a run ID
    if stopped_run_id:
        try:
            headers = supabase_client._get_auth_headers()
            update_response = requests.put(
                f"{SERVICE_GATEWAY_URL}/api/workflow-runs/{stopped_run_id}",
                json={"status": "stopped"},
                headers=headers,
            )
            if update_response.status_code == 200:
                logger.info(
                    f"Updated workflow run {stopped_run_id} status to 'stopped'"
                )
            else:
                logger.warning(
                    f"Failed to update workflow run status: {update_response.text}"
                )
        except Exception as exc:
            logger.warning(f"Error updating workflow run status: {exc}")

    return {
        "success": True,
        "message": "Infinite hunt stopped successfully",
        "run_id": stopped_run_id,
        "workflow_id": stopped_agent_run_template_name,
    }


@app.get("/api/infinite-hunt/status")
async def get_infinite_hunt_status():
    """Get the status of the infinite hunt from the database"""
    try:
        # Get the infinite run record from the database
        infinite_run_obj = supabase_client.get_infinite_run()
        if not infinite_run_obj:
            return {
                "success": True,
                "status": "idle",
                "message": None,
                "active_agent_run_id": None,
                "last_run_id": None,
                "session_id": None,
            }

        # Convert InfiniteRun object to dict
        infinite_run = (
            infinite_run_obj.model_dump()
            if hasattr(infinite_run_obj, "model_dump")
            else infinite_run_obj.__dict__
        )

        # Get the session ID from the infinite run
        session_id = infinite_run.get("session_id")

        # Find the most recent workflow run for this session
        active_agent_run_id = None
        if session_id:
            # Query the service gateway for workflow runs with this session_id

            url = f"{SERVICE_GATEWAY_URL}/api/workflow-runs/"
            params = {
                "infinite_hunt_session_id": session_id,
                "page": 1,
                "page_size": 1,
            }
            headers = supabase_client._get_auth_headers()

            response = requests.get(url, params=params, headers=headers)
            if response.status_code == 200:
                data = response.json()
                runs = data.get("runs", [])
                if runs and len(runs) > 0:
                    # The most recent run is the active one
                    most_recent_run = runs[0]
                    # Only consider it active if it's running or pending
                    if most_recent_run.get("status") in ["running", "pending"]:
                        active_agent_run_id = most_recent_run.get("id")

        return {
            "success": True,
            "status": infinite_run.get("status", "idle"),
            "active_agent_run_id": active_agent_run_id,
            "last_run_id": infinite_run.get("last_run_id"),
            "session_id": session_id,
        }
    except Exception as e:
        logger.error(f"Failed to get infinite hunt status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/infinite-hunt/bot-status")
async def get_infinite_hunt_bot_status():
    """Get the status of the currently active bot in infinite hunt"""
    try:
        manager = initialize_infinite_hunt_manager()
        result = manager.get_active_controller()

        if not result:
            return {"is_running": False, "workflow_run_id": None, "workflow_id": None}

        controller, run_id, workflow_id = result
        is_running = controller.is_bot_running(run_id)

        return {
            "is_running": is_running,
            "workflow_run_id": run_id,
            "workflow_id": workflow_id,
        }
    except Exception as exc:
        logger.error(f"Failed to get bot status: {exc}")
        return {"is_running": False, "workflow_run_id": None, "workflow_id": None}


@app.get("/api/infinite-hunt/metadata")
async def get_infinite_hunt_metadata():
    """
    Get infinite hunt runtime metadata for nav bar display.

    Minimal flat structure - only fields needed for UI:
    - is_running: bool
    - started_at: str | null (for duration calc)
    - ended_at: str | null (null when active)
    - agent_runs_by_template: dict (template progress)
    - current_agent_run: dict | null (real-time stats when active)
    - cumulative_job_stats: dict (job counts)
    """
    try:
        metadata_service = get_metadata_service()
        is_running = metadata_service.is_infinite_hunt_running()

        if is_running:
            # Active: use real-time in-memory data
            status = metadata_service.get_full_status()
            return {
                "is_running": True,
                "started_at": status.get("started_at"),
                "ended_at": None,
                "agent_runs_by_template": status.get("agent_runs_by_template", {}),
                "current_agent_run": status.get("current_agent_run"),
                "cumulative_job_stats": status.get(
                    "cumulative_job_stats",
                    {
                        "queued": 0,
                        "skipped": 0,
                        "submitted": 0,
                        "failed": 0,
                    },
                ),
            }

        # Idle: get session_id from in-memory (persists after stop)
        status = metadata_service.get_full_status()
        session_id = status.get("session_id")

        # Fallback: if in-memory is empty (e.g., after restart), get from DB config
        if not session_id:
            try:
                infinite_run_obj = supabase_client.get_infinite_run()
                if infinite_run_obj and infinite_run_obj.session_id:
                    session_id = str(infinite_run_obj.session_id)
            except Exception as e:
                logger.warning(f"Failed to fetch session_id from config: {e}")

        # Get auto infinite hunt status for countdown display
        auto_hunt_status = None
        auto_hunt_monitor = get_auto_infinite_hunt_monitor()
        if auto_hunt_monitor:
            auto_hunt_status = auto_hunt_monitor.get_status()

        # Default response for idle state
        response = {
            "is_running": False,
            "started_at": None,
            "ended_at": None,
            "agent_runs_by_template": {},
            "current_agent_run": None,
            "cumulative_job_stats": {
                "queued": 0,
                "skipped": 0,
                "submitted": 0,
                "failed": 0,
            },
            "auto_hunt_status": auto_hunt_status,
        }

        # Fetch historical session stats from DB if we have a session
        if session_id:
            try:
                url = f"{SERVICE_GATEWAY_URL}/api/infinite-runs/session-metadata/{session_id}"
                headers = supabase_client._get_auth_headers()
                resp = requests.get(url, headers=headers, timeout=5)

                if resp.status_code == 200:
                    data = resp.json()
                    response["started_at"] = data.get("started_at")
                    response["ended_at"] = data.get("ended_at")
                    response["agent_runs_by_template"] = data.get(
                        "agent_runs_by_template", {}
                    )
                    response["cumulative_job_stats"] = {
                        "queued": data.get("queued", 0),
                        "skipped": data.get("skipped", 0),
                        "submitted": data.get("submitted", 0),
                        "failed": data.get("failed", 0),
                    }
            except Exception as e:
                logger.warning(f"Failed to fetch session metadata: {e}")

        return response

    except Exception as exc:
        logger.error(f"Failed to get infinite hunt metadata: {exc}")
        return {
            "is_running": False,
            "started_at": None,
            "ended_at": None,
            "agent_runs_by_template": {},
            "current_agent_run": None,
            "cumulative_job_stats": {
                "queued": 0,
                "skipped": 0,
                "submitted": 0,
                "failed": 0,
            },
        }


@app.get("/api/infinite-hunt/job-stats")
async def get_infinite_hunt_job_stats():
    """Get current and cumulative job stats for infinite hunt."""
    try:
        metadata_service = get_metadata_service()
        return {
            "success": True,
            "current": metadata_service.get_current_job_stats(),
            "cumulative": metadata_service.get_cumulative_job_stats(),
        }
    except Exception as exc:
        logger.error(f"Failed to get job stats: {exc}")
        return {
            "success": False,
            "error": str(exc),
            "current": {"queued": 0, "skipped": 0, "submitted": 0, "failed": 0},
            "cumulative": {"queued": 0, "skipped": 0, "submitted": 0, "failed": 0},
        }


@app.get("/api/infinite-hunt/auto-hunt-status")
async def get_auto_infinite_hunt_status():
    """
    Get auto infinite hunt monitor status.

    Returns:
        - enabled: Whether auto_infinite_hunt_on is enabled
        - check_interval_minutes: How often the monitor checks (30 min)
        - last_auto_start_at: Timestamp of last auto-start
    """
    try:
        monitor = get_auto_infinite_hunt_monitor()
        if monitor:
            return {
                "success": True,
                **monitor.get_status(),
            }
        return {
            "success": False,
            "error": "Auto infinite hunt monitor not initialized",
            "enabled": False,
        }
    except Exception as exc:
        logger.error(f"Failed to get auto infinite hunt status: {exc}")
        return {
            "success": False,
            "error": str(exc),
            "enabled": False,
        }


# REST API endpoints for LinkedIn bot control
@app.post("/api/linkedin-bot/{user_id}/{workflow_run_id}/start")
async def start_hunting(
    user_id: str, workflow_run_id: str, request: StartHuntingRequest
):
    """Start LinkedIn bot hunting process"""
    try:
        logger.info(
            f"Starting hunting for user {user_id}, workflow run {workflow_run_id}"
        )

        # Extract workflow_run_id from config
        bot_config = request.config or {}
        if request.linkedin_starter_url:
            bot_config["linkedinStarterUrl"] = request.linkedin_starter_url
        # workflow_run_id comes from URL path parameter
        # Register workflow run for activity polling
        linkedin_bot_controller.register_polling_session(workflow_run_id)

        # Start the bot with activity callback
        result = linkedin_bot_controller.start_hunting_controller(
            user_id, workflow_run_id, bot_config
        )

        return {
            "success": result.get("success", False),
            "bot_id": result.get("bot_id"),
            "workflow_run_id": workflow_run_id,
            "message": result.get("message", "Unknown result"),
            "polling_registered": True,
        }

    except Exception as e:
        logger.error(f"Failed to start hunting: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/linkedin-bot/{workflow_run_id}/stop")
async def stop_hunting(workflow_run_id: str):
    """Stop LinkedIn bot hunting process"""
    try:
        logger.info(f"Stopping hunting for workflow run {workflow_run_id}")
        result = linkedin_bot_controller.stop_hunting_controller(workflow_run_id)

        return {
            "success": result.get("success", False),
            "message": result.get("message", "Unknown result"),
        }

    except Exception as e:
        logger.error(f"Failed to stop hunting: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/linkedin-bot/{workflow_run_id}/pause")
async def pause_hunting(workflow_run_id: str):
    """Pause LinkedIn bot hunting process"""
    try:
        logger.info(f"Pausing hunting for workflow run {workflow_run_id}")
        result = linkedin_bot_controller.pause_hunting_controller(workflow_run_id)

        return {
            "success": result.get("success", False),
            "message": result.get("message", "Unknown result"),
        }

    except Exception as e:
        logger.error(f"Failed to pause hunting: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/linkedin-bot/{workflow_run_id}/resume")
async def resume_hunting(workflow_run_id: str):
    """Resume LinkedIn bot hunting process"""
    try:
        logger.info(f"Resuming hunting for workflow run {workflow_run_id}")
        result = linkedin_bot_controller.resume_hunting_controller(workflow_run_id)
        return {
            "success": result.get("success", False),
            "message": result.get("message", "Unknown result"),
        }

    except Exception as e:
        logger.error(f"Failed to resume hunting: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/linkedin-bot/{workflow_run_id}/status")
async def get_bot_status(workflow_run_id: str):
    """Get LinkedIn bot status"""
    try:
        result = linkedin_bot_controller.get_bot_status(workflow_run_id)

        return BotStatusResponse(
            success=result.get("success", False),
            bot_id=result.get("bot_id"),
            is_running=result.get("is_running", False),
            status=result.get("status", "unknown"),
            current_url=result.get("current_url"),
            has_browser=result.get("has_browser", False),
            has_page=result.get("has_page", False),
            message=result.get("message"),
        )

    except Exception as e:
        logger.error(f"Failed to get bot status: {e}")
        return BotStatusResponse(success=False, error=str(e))


# REST API endpoints for Indeed bot control
@app.post("/api/indeed-bot/{user_id}/{workflow_run_id}/start")
async def start_searching(
    user_id: str, workflow_run_id: str, request: StartSearchingRequest
):
    """Start Indeed bot searching process"""
    try:
        logger.info(
            f"Starting Indeed search for user {user_id}, workflow run {workflow_run_id}"
        )

        # Register workflow run for activity polling
        indeed_bot_controller.register_polling_session(workflow_run_id)

        # Start the bot with activity callback
        bot_config = request.config or {}
        if request.indeed_starter_url:
            bot_config["indeedStarterUrl"] = request.indeed_starter_url

        result = indeed_bot_controller.start_searching_controller(
            user_id, workflow_run_id, bot_config
        )

        return {
            "success": result.get("success", False),
            "bot_id": result.get("bot_id"),
            "workflow_run_id": workflow_run_id,
            "message": result.get("message", "Unknown result"),
            "polling_registered": True,
        }

    except Exception as e:
        logger.error(f"Failed to start Indeed search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/indeed-bot/{workflow_run_id}/stop")
async def stop_searching(workflow_run_id: str):
    """Stop Indeed bot searching process"""
    try:
        logger.info(f"Stopping Indeed search for workflow run {workflow_run_id}")
        result = indeed_bot_controller.stop_searching_controller(workflow_run_id)

        return {
            "success": result.get("success", False),
            "message": result.get("message", "Unknown result"),
        }

    except Exception as e:
        logger.error(f"Failed to stop Indeed search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/indeed-bot/{workflow_run_id}/pause")
async def pause_searching(workflow_run_id: str):
    """Pause Indeed bot searching process"""
    try:
        logger.info(f"Pausing Indeed search for workflow run {workflow_run_id}")
        result = indeed_bot_controller.pause_searching_controller(workflow_run_id)

        return {
            "success": result.get("success", False),
            "message": result.get("message", "Unknown result"),
        }

    except Exception as e:
        logger.error(f"Failed to pause Indeed search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/indeed-bot/{workflow_run_id}/resume")
async def resume_searching(workflow_run_id: str):
    """Resume Indeed bot searching process"""
    try:
        logger.info(f"Resuming Indeed search for workflow run {workflow_run_id}")
        result = indeed_bot_controller.resume_searching_controller(workflow_run_id)
        return {
            "success": result.get("success", False),
            "message": result.get("message", "Unknown result"),
        }

    except Exception as e:
        logger.error(f"Failed to resume Indeed search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/indeed-bot/{workflow_run_id}/status")
async def get_indeed_bot_status(workflow_run_id: str):
    """Get Indeed bot status"""
    try:
        result = indeed_bot_controller.get_bot_status(workflow_run_id)

        return BotStatusResponse(
            success=result.get("success", False),
            bot_id=result.get("bot_id"),
            is_running=result.get("is_running", False),
            status=result.get("status", "unknown"),
            current_url=result.get("current_url"),
            has_browser=result.get("has_browser", False),
            has_page=result.get("has_page", False),
            message=result.get("message"),
        )

    except Exception as e:
        logger.error(f"Failed to get Indeed bot status: {e}")
        return BotStatusResponse(success=False, error=str(e))


# REST API endpoints for Autonomous browser-use bot
@app.post("/api/autonomous-search/{user_id}/{workflow_run_id}/start")
async def start_autonomous_search(
    user_id: str, workflow_run_id: str, request: StartSearchingRequest
):
    try:
        logger.info(
            f"Starting autonomous Browser Use search for user {user_id}, workflow run {workflow_run_id}"
        )
        # workflow_run_id comes from URL path parameter
        bot_config = request.config or {}

        # Register workflow run for activity polling
        autonomous_search_controller.register_polling_session(workflow_run_id)

        result = autonomous_search_controller.start_autonomous_search(
            user_id, workflow_run_id, bot_config
        )
        return {
            "success": result.get("success", False),
            "message": result.get("message", "Unknown"),
        }
    except Exception as e:
        logger.error(f"Failed to start autonomous search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/autonomous-search/{workflow_run_id}/stop")
async def stop_autonomous_search(workflow_run_id: str):
    try:
        logger.info(f"Stopping autonomous search for workflow run {workflow_run_id}")
        result = autonomous_search_controller.stop_autonomous_search(workflow_run_id)
        return result
    except Exception as e:
        logger.error(f"Failed to stop autonomous search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/autonomous-search/{workflow_run_id}/status")
async def get_autonomous_status(workflow_run_id: str):
    try:
        return autonomous_search_controller.get_status(workflow_run_id)
    except Exception as e:
        logger.error(f"Failed to get autonomous status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# REST API endpoints for LLM credential management
@app.get("/api/llm-credentials/{workflow_run_id}/{provider}")
async def get_llm_credentials(workflow_run_id: str, provider: str):
    """Load stored LLM credentials for a workflow run and provider"""
    try:
        from services.llm_credential_manager import LLMCredentialManager

        credentials = LLMCredentialManager.load_credentials(workflow_run_id, provider)
        if credentials:
            return {"success": True, "credentials": credentials}
        return {"success": False, "message": "No credentials found"}
    except Exception as e:
        logger.error(f"Failed to load LLM credentials: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/llm-credentials/{workflow_run_id}/{provider}")
async def save_llm_credentials(workflow_run_id: str, provider: str, request: dict):
    """Save LLM credentials for a workflow run and provider"""
    try:
        from services.llm_credential_manager import LLMCredentialManager

        api_key = request.get("api_key")
        model = request.get("model")
        endpoint = request.get("endpoint")

        if not api_key:
            raise HTTPException(status_code=400, detail="API key is required")

        success = LLMCredentialManager.save_credentials(
            workflow_run_id=workflow_run_id,
            provider=provider,
            api_key=api_key,
            model=model,
            endpoint=endpoint,
        )

        if success:
            return {"success": True, "message": "Credentials saved successfully"}
        return {"success": False, "message": "Failed to save credentials"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to save LLM credentials: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/llm-test-connection")
async def test_llm_connection(request: dict):
    """Test LLM API connection (proxied through backend to avoid CORS)"""
    import httpx

    try:
        provider = request.get("provider")
        api_key = request.get("api_key")
        model = request.get("model")
        endpoint = request.get("endpoint")

        if not provider or not api_key:
            raise HTTPException(status_code=400, detail="Provider and API key required")

        test_prompt = 'Say "Hello! API connection successful." in a friendly way.'

        async with httpx.AsyncClient(timeout=30.0) as client:
            if provider == "openai":
                # o1 models use max_completion_tokens instead of max_tokens
                # and don't support temperature
                request_body = {
                    "model": model,
                    "messages": [{"role": "user", "content": test_prompt}],
                }

                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                    json=request_body,
                )
            elif provider == "azure":
                if not endpoint or not model:
                    raise HTTPException(
                        status_code=400,
                        detail="Azure requires endpoint and deployment name",
                    )
                endpoint_clean = endpoint.rstrip("/")
                url = f"{endpoint_clean}/openai/deployments/{model}/chat/completions?api-version=2025-01-01-preview"
                response = await client.post(
                    url,
                    headers={"Content-Type": "application/json", "api-key": api_key},
                    json={
                        "messages": [{"role": "user", "content": test_prompt}],
                        "max_tokens": 50,
                    },
                )
            elif provider == "claude":
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                    },
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": test_prompt}],
                        "max_tokens": 50,
                    },
                )
            elif provider == "gemini":
                url = f"https://generativelanguage.googleapis.com/v1/models/{model}:generateContent?key={api_key}"
                response = await client.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json={"contents": [{"parts": [{"text": test_prompt}]}]},
                )
            else:
                raise HTTPException(
                    status_code=400, detail=f"Unsupported provider: {provider}"
                )

            if response.status_code == 200:
                return {"success": True, "message": "API connection successful!"}
            else:
                error_data = response.json() if response.text else {}
                error_msg = (
                    error_data.get("error", {}).get("message")
                    or error_data.get("message")
                    or f"HTTP {response.status_code}"
                )
                return {"success": False, "message": error_msg}

    except httpx.TimeoutException:
        return {
            "success": False,
            "message": "Request timed out. Check your network connection.",
        }
    except Exception as e:
        logger.error(f"LLM test connection failed: {e}")
        return {"success": False, "message": str(e)}


# REST API endpoints for ZipRecruiter bot control
@app.post("/api/ziprecruiter-bot/{user_id}/{workflow_run_id}/start")
async def start_ziprecruiter_searching(
    user_id: str, workflow_run_id: str, request: StartSearchingRequest
):
    """Start ZipRecruiter bot searching process"""
    try:
        logger.info(
            f"Starting ZipRecruiter search for user {user_id}, workflow run {workflow_run_id}"
        )

        # workflow_run_id comes from URL path parameter
        bot_config = request.config or {}

        # Register workflow run for activity polling
        ziprecruiter_bot_controller.register_polling_session(workflow_run_id)

        # Start the bot with activity callback
        result = ziprecruiter_bot_controller.start_searching_controller(
            user_id, workflow_run_id, bot_config
        )

        return {
            "success": result.get("success", False),
            "bot_id": result.get("bot_id"),
            "workflow_run_id": workflow_run_id,
            "message": result.get("message", "Unknown result"),
            "polling_registered": True,
        }

    except Exception as e:
        logger.error(f"Failed to start ZipRecruiter search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ziprecruiter-bot/{workflow_run_id}/stop")
async def stop_ziprecruiter_searching(workflow_run_id: str):
    """Stop ZipRecruiter bot searching process"""
    try:
        logger.info(f"Stopping ZipRecruiter search for workflow run {workflow_run_id}")
        result = ziprecruiter_bot_controller.stop_searching_controller(workflow_run_id)

        return {
            "success": result.get("success", False),
            "message": result.get("message", "Unknown result"),
        }

    except Exception as e:
        logger.error(f"Failed to stop ZipRecruiter search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ziprecruiter-bot/{workflow_run_id}/pause")
async def pause_ziprecruiter_searching(workflow_run_id: str):
    """Pause ZipRecruiter bot searching process"""
    try:
        logger.info(f"Pausing ZipRecruiter search for workflow run {workflow_run_id}")
        result = ziprecruiter_bot_controller.pause_searching_controller(workflow_run_id)

        return {
            "success": result.get("success", False),
            "message": result.get("message", "Unknown result"),
        }

    except Exception as e:
        logger.error(f"Failed to pause ZipRecruiter search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ziprecruiter-bot/{workflow_run_id}/resume")
async def resume_ziprecruiter_searching(workflow_run_id: str):
    """Resume ZipRecruiter bot searching process"""
    try:
        logger.info(f"Resuming ZipRecruiter search for workflow run {workflow_run_id}")
        result = ziprecruiter_bot_controller.resume_searching_controller(
            workflow_run_id
        )
        return {
            "success": result.get("success", False),
            "message": result.get("message", "Unknown result"),
        }

    except Exception as e:
        logger.error(f"Failed to resume ZipRecruiter search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ziprecruiter-bot/{workflow_run_id}/status")
async def get_ziprecruiter_bot_status(workflow_run_id: str):
    """Get ZipRecruiter bot status"""
    try:
        result = ziprecruiter_bot_controller.get_bot_status(workflow_run_id)

        return BotStatusResponse(
            success=result.get("success", False),
            bot_id=result.get("bot_id"),
            is_running=result.get("is_running", False),
            status=result.get("status", "unknown"),
            current_url=result.get("current_url"),
            has_browser=result.get("has_browser", False),
            has_page=result.get("has_page", False),
            message=result.get("message"),
        )

    except Exception as e:
        logger.error(f"Failed to get ZipRecruiter bot status: {e}")
        return BotStatusResponse(success=False, error=str(e))


# REST API endpoints for Glassdoor bot control
@app.post("/api/glassdoor-bot/{user_id}/{workflow_run_id}/start")
async def start_glassdoor_searching(
    user_id: str, workflow_run_id: str, request: StartSearchingRequest
):
    """Start Glassdoor bot searching process"""
    try:
        logger.info(
            f"Starting Glassdoor search for user {user_id}, workflow run {workflow_run_id}"
        )

        # workflow_run_id comes from URL path parameter
        bot_config = request.config or {}

        # Register workflow run for activity polling
        glassdoor_bot_controller.register_polling_session(workflow_run_id)

        # Start the bot with activity callback
        result = glassdoor_bot_controller.start_searching_controller(
            user_id, workflow_run_id, bot_config
        )

        return {
            "success": result.get("success", False),
            "bot_id": result.get("bot_id"),
            "workflow_run_id": workflow_run_id,
            "message": result.get("message", "Unknown result"),
            "polling_registered": True,
        }

    except Exception as e:
        logger.error(f"Failed to start Glassdoor search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/glassdoor-bot/{workflow_run_id}/stop")
async def stop_glassdoor_searching(workflow_run_id: str):
    """Stop Glassdoor bot searching process"""
    try:
        logger.info(f"Stopping Glassdoor search for workflow run {workflow_run_id}")
        result = glassdoor_bot_controller.stop_searching_controller(workflow_run_id)

        return {
            "success": result.get("success", False),
            "message": result.get("message", "Unknown result"),
        }

    except Exception as e:
        logger.error(f"Failed to stop Glassdoor search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/glassdoor-bot/{workflow_run_id}/pause")
async def pause_glassdoor_searching(workflow_run_id: str):
    """Pause Glassdoor bot searching process"""
    try:
        logger.info(f"Pausing Glassdoor search for workflow run {workflow_run_id}")
        result = glassdoor_bot_controller.pause_searching_controller(workflow_run_id)

        return {
            "success": result.get("success", False),
            "message": result.get("message", "Unknown result"),
        }

    except Exception as e:
        logger.error(f"Failed to pause Glassdoor search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/glassdoor-bot/{workflow_run_id}/resume")
async def resume_glassdoor_searching(workflow_run_id: str):
    """Resume Glassdoor bot searching process"""
    try:
        logger.info(f"Resuming Glassdoor search for workflow run {workflow_run_id}")
        result = glassdoor_bot_controller.resume_searching_controller(workflow_run_id)
        return {
            "success": result.get("success", False),
            "message": result.get("message", "Unknown result"),
        }

    except Exception as e:
        logger.error(f"Failed to resume Glassdoor search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/glassdoor-bot/{workflow_run_id}/status")
async def get_glassdoor_bot_status(workflow_run_id: str):
    """Get Glassdoor bot status"""
    try:
        result = glassdoor_bot_controller.get_bot_status(workflow_run_id)

        return BotStatusResponse(
            success=result.get("success", False),
            bot_id=result.get("bot_id"),
            is_running=result.get("is_running", False),
            status=result.get("status", "unknown"),
            current_url=result.get("current_url"),
            has_browser=result.get("has_browser", False),
            has_page=result.get("has_page", False),
            message=result.get("message"),
        )

    except Exception as e:
        logger.error(f"Failed to get Glassdoor bot status: {e}")
        return BotStatusResponse(success=False, error=str(e))


# REST API endpoints for Dice bot control
@app.post("/api/dice-bot/{user_id}/{workflow_run_id}/start")
async def start_dice_searching(
    user_id: str, workflow_run_id: str, request: StartSearchingRequest
):
    """Start Dice bot searching process"""
    try:
        logger.info(
            f"Starting Dice search for user {user_id}, workflow run {workflow_run_id}"
        )

        # workflow_run_id comes from URL path parameter
        bot_config = request.config or {}

        # Register workflow run for activity polling
        dice_bot_controller.register_polling_session(workflow_run_id)

        # Start the bot with activity callback
        result = dice_bot_controller.start_searching_controller(
            user_id, workflow_run_id, bot_config
        )

        return {
            "success": result.get("success", False),
            "bot_id": result.get("bot_id"),
            "workflow_run_id": workflow_run_id,
            "message": result.get("message", "Unknown result"),
            "polling_registered": True,
        }

    except Exception as e:
        logger.error(f"Failed to start Dice search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/dice-bot/{workflow_run_id}/stop")
async def stop_dice_searching(workflow_run_id: str):
    """Stop Dice bot searching process"""
    try:
        logger.info(f"Stopping Dice search for workflow run {workflow_run_id}")
        result = dice_bot_controller.stop_searching_controller(workflow_run_id)

        return {
            "success": result.get("success", False),
            "message": result.get("message", "Unknown result"),
        }

    except Exception as e:
        logger.error(f"Failed to stop Dice search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/dice-bot/{workflow_run_id}/pause")
async def pause_dice_searching(workflow_run_id: str):
    """Pause Dice bot searching process"""
    try:
        logger.info(f"Pausing Dice search for workflow run {workflow_run_id}")
        result = dice_bot_controller.pause_searching_controller(workflow_run_id)

        return {
            "success": result.get("success", False),
            "message": result.get("message", "Unknown result"),
        }

    except Exception as e:
        logger.error(f"Failed to pause Dice search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/dice-bot/{workflow_run_id}/resume")
async def resume_dice_searching(workflow_run_id: str):
    """Resume Dice bot searching process"""
    try:
        logger.info(f"Resuming Dice search for workflow run {workflow_run_id}")
        result = dice_bot_controller.resume_searching_controller(workflow_run_id)
        return {
            "success": result.get("success", False),
            "message": result.get("message", "Unknown result"),
        }

    except Exception as e:
        logger.error(f"Failed to resume Dice search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dice-bot/{workflow_run_id}/status")
async def get_dice_bot_status(workflow_run_id: str):
    """Get Dice bot status"""
    try:
        result = dice_bot_controller.get_bot_status(workflow_run_id)

        return BotStatusResponse(
            success=result.get("success", False),
            bot_id=result.get("bot_id"),
            is_running=result.get("is_running", False),
            status=result.get("status", "unknown"),
            current_url=result.get("current_url"),
            has_browser=result.get("has_browser", False),
            has_page=result.get("has_page", False),
            message=result.get("message"),
        )

    except Exception as e:
        logger.error(f"Failed to get Dice bot status: {e}")
        return BotStatusResponse(success=False, error=str(e))


# Auth endpoints
@app.post("/api/auth/save-jwt")
async def save_jwt_token(request: Request):
    """Save JWT token from frontend (including refreshed tokens)"""  # noqa: E402
    try:
        data = await request.json()
        jwt_token = data.get("jwt_token")
        user_info = data.get("user_info", {})
        is_refresh = data.get("is_refresh", False)

        if not jwt_token:
            raise HTTPException(status_code=400, detail="JWT token is required")

        success = auth_helper.save_user_login(jwt_token, user_info)

        # Update logger with user email for BetterStack
        if success and user_info:
            from logger import update_user_email  # noqa: E402

            email = user_info.get("email") or user_info.get("user_metadata", {}).get(
                "email"
            )
            if email:
                update_user_email(email)

        if is_refresh:
            logger.info("JWT token refreshed and saved successfully")
        else:
            logger.info("JWT token saved successfully")

        return {
            "success": success,
            "message": (
                "JWT token refreshed and saved successfully"
                if is_refresh
                else (
                    "JWT token saved successfully"
                    if success
                    else "Failed to save JWT token"
                )
            ),
            "user_authenticated": success,
        }

    except Exception as e:
        logger.error(f"Failed to save JWT token: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/auth/status")
async def get_auth_status():
    """Get current authentication status"""
    try:
        is_authenticated = auth_helper.is_user_authenticated()
        return {
            "success": True,
            "auth_status": "authenticated" if is_authenticated else "not_authenticated",
            "is_authenticated": is_authenticated,
        }

    except Exception as e:
        logger.error(f"Failed to get auth status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/auth/logout")
async def logout():
    """Handle user logout"""
    try:
        success = auth_helper.logout_user()
        return {
            "success": success,
            "message": "Logged out successfully" if success else "Failed to logout",
        }

    except Exception as e:
        logger.error(f"Failed to logout: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Polling endpoint for getting pending activity messages
@app.get("/api/activity/pending/{workflow_run_id}")
async def get_pending_activity_messages(workflow_run_id: str):
    """Get pending activity messages for a workflow run (for polling)"""
    try:
        messages = []

        # Check LinkedIn bot controller for messages
        with linkedin_bot_controller._message_lock:
            linkedin_messages = linkedin_bot_controller.activity_messages.get(
                workflow_run_id, []
            )
            if linkedin_messages:
                messages.extend(linkedin_messages)
                # Clear messages after retrieving them
                linkedin_bot_controller.activity_messages[workflow_run_id] = []

        # Check Indeed bot controller for messages
        with indeed_bot_controller._message_lock:
            indeed_messages = indeed_bot_controller.activity_messages.get(
                workflow_run_id, []
            )
            if indeed_messages:
                messages.extend(indeed_messages)
                # Clear messages after retrieving them
                indeed_bot_controller.activity_messages[workflow_run_id] = []

        # Check ZipRecruiter bot controller for messages
        with ziprecruiter_bot_controller._message_lock:
            zip_messages = ziprecruiter_bot_controller.activity_messages.get(
                workflow_run_id, []
            )
            if zip_messages:
                messages.extend(zip_messages)
                ziprecruiter_bot_controller.activity_messages[workflow_run_id] = []

        # Check Glassdoor bot controller for messages
        with glassdoor_bot_controller._message_lock:
            glassdoor_messages = glassdoor_bot_controller.activity_messages.get(
                workflow_run_id, []
            )
            if glassdoor_messages:
                messages.extend(glassdoor_messages)
                glassdoor_bot_controller.activity_messages[workflow_run_id] = []

        # Check Dice bot controller for messages
        with dice_bot_controller._message_lock:
            dice_messages = dice_bot_controller.activity_messages.get(
                workflow_run_id, []
            )
            if dice_messages:
                messages.extend(dice_messages)
                dice_bot_controller.activity_messages[workflow_run_id] = []

        # Check autonomous search controller for messages
        with autonomous_search_controller._message_lock:
            auto_messages = autonomous_search_controller.activity_messages.get(
                workflow_run_id, []
            )
            if auto_messages:
                messages.extend(auto_messages)
                autonomous_search_controller.activity_messages[workflow_run_id] = []

        return {"messages": messages, "count": len(messages)}

    except Exception as e:
        logger.error(f"Failed to get pending activity messages: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# PDF Export Models
class PDFExportRequest(BaseModel):
    html_content: str
    filename: Optional[str] = "resume"


# LinkedIn Job Scraping Models
class LinkedInJobRequest(BaseModel):
    job_url: str


class LinkedInJobResponse(BaseModel):
    success: bool
    job_data: Optional[
        Dict[str, Any]
    ] = None  # Changed from Dict[str, str] to Dict[str, Any]  # noqa: E402
    message: Optional[str] = None


# Collect Contacts Models
class CollectContactsRequest(BaseModel):
    application_history_list: list[dict[str, Any]]


class CollectContactsResponse(BaseModel):
    success: bool
    contacts: Optional[list[dict[str, Any]]] = None
    processed_count: Optional[int] = None
    message: Optional[str] = None


# PDF Export endpoint
@app.post("/api/pdf/export")
async def export_resume_to_pdf(request: PDFExportRequest):
    """Export resume HTML to PDF using Playwright."""
    try:
        from util.pdf_generator import (  # noqa: E402
            create_resume_output_dir,
            generate_pdf_from_html_async,
        )

        # Create output directory
        output_dir = create_resume_output_dir()

        # Generate PDF
        pdf_path = await generate_pdf_from_html_async(
            html_content=request.html_content,
            output_dir=output_dir,
            filename=request.filename,
        )

        # Return the file path for frontend to handle
        return {
            "success": True,
            "pdf_path": str(pdf_path),
            "filename": pdf_path.name,
            "message": "PDF generated successfully",
        }

    except Exception as e:
        logger.exception("Error in export_resume_to_pdf")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/pdf/download/{file_path:path}")
async def download_pdf_file(file_path: str):
    """Download a generated PDF file."""
    try:
        from pathlib import Path  # noqa: E402

        from fastapi.responses import FileResponse  # noqa: E402

        # Security: Ensure the file path is within our output directory
        pdf_path = Path(file_path)
        if not pdf_path.is_absolute():
            # If relative path, make it relative to current working directory
            pdf_path = Path.cwd() / pdf_path

        # Validate the file exists and is within allowed directory
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail="PDF file not found")

        if not pdf_path.suffix.lower() == ".pdf":
            raise HTTPException(status_code=400, detail="Invalid file type")

        # Check if file is in our output directory (security measure)
        from constants import RESUME_DIR  # noqa: E402

        output_base = Path(RESUME_DIR)
        result = None

        try:
            pdf_path.resolve().relative_to(output_base.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")

        return FileResponse(
            path=str(pdf_path), filename=pdf_path.name, media_type="application/pdf"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in download_pdf_file")
        raise HTTPException(status_code=500, detail=str(e))


# LinkedIn Job Scraping endpoint
@app.post("/api/linkedin/extract-job", response_model=LinkedInJobResponse)
async def extract_linkedin_job_data(request: LinkedInJobRequest):
    """Extract job data from LinkedIn job URL using LinkedIn Bot Action."""
    try:
        logger.info(f"Extracting job data from URL: {request.job_url}")  # noqa: E402

        # Validate URL format
        if not request.job_url.startswith("https://www.linkedin.com/jobs/search"):
            return LinkedInJobResponse(
                success=False,
                message=(
                    "Invalid LinkedIn job URL. Must start with "
                    "https://www.linkedin.com/jobs/search"
                ),
            )

        # Run the action in a separate process to avoid asyncio conflicts
        import asyncio  # noqa: E402

        from linkedin_bot.actions.extract_job_data_action import (  # noqa: E402
            ExtractJobDataAction,
        )

        def run_job_extraction(job_url: str) -> dict[str, object]:
            """Execute the extraction synchronously in a worker thread."""
            try:
                mock_bot_cls = type(
                    "MockBot",
                    (),
                    {
                        "websocket_callback": None,
                        "bot_id": "job_extractor",
                    },
                )
                action = ExtractJobDataAction(mock_bot_cls())
                return action.execute(job_url)
            except Exception as exc:
                logger.exception("Job extraction worker failed")
                return {
                    "success": False,
                    "error": f"Job extraction failed: {exc}",
                    "job_data": None,
                }

        result = await asyncio.to_thread(run_job_extraction, request.job_url)

        if result["success"]:
            job_id = result["job_data"].get("job_id", "unknown")
            logger.info(f"Successfully extracted job data for job ID: {job_id}")
            return LinkedInJobResponse(
                success=True, job_data=result["job_data"], message=result["message"]
            )
        else:
            logger.warning(f"Job extraction failed: {result['error']}")
            return LinkedInJobResponse(success=False, message=result["error"])

    except Exception as e:
        logger.exception("Error in extract_linkedin_job_data")
        return LinkedInJobResponse(
            success=False, message=f"Failed to extract job data: {str(e)}"
        )


# Collect Contacts endpoint
@app.post("/api/linkedin/collect-contacts", response_model=CollectContactsResponse)
async def collect_contacts(request: CollectContactsRequest):
    """Collect hiring manager contacts from LinkedIn job applications."""  # noqa: E402
    try:
        app_count = len(request.application_history_list)
        logger.info(f"Collecting contacts for {app_count} applications")

        # Validate input
        if not request.application_history_list:
            return CollectContactsResponse(
                success=False,
                message="No application history records provided",
            )

        # Use the controller to execute the action
        result = linkedin_bot_controller.collect_contacts_controller(
            request.application_history_list
        )

        if result["success"]:
            proc_count = result.get("processed_count", 0)
            logger.info(
                f"Successfully collected contacts from {proc_count} applications"
            )
            return CollectContactsResponse(
                success=True,
                contacts=result.get("contacts", []),
                processed_count=result.get("processed_count", 0),
                message=result.get("message", "Contact collection completed"),
            )
        else:
            logger.warning(
                f"Contact collection failed: {result.get('error', 'Unknown error')}"
            )
            return CollectContactsResponse(
                success=False,
                message=result.get("error", "Failed to collect contacts"),
            )

    except Exception as e:
        logger.exception("Error in collect_contacts")
        return CollectContactsResponse(
            success=False, message=f"Failed to collect contacts: {str(e)}"
        )


@app.get("/api/linkedin/collection-status")
async def get_collection_status():
    """Check if contact collection is currently running."""
    try:
        is_running = "contact_collector" in linkedin_bot_controller.bots
        _bot = linkedin_bot_controller.bots.get("contact_collector")

        if _bot and hasattr(_bot, "is_running"):
            is_running = is_running and _bot.is_running

        return {"success": True, "is_collecting": is_running}
    except Exception as e:  # noqa: F841
        logger.exception("Error checking collection status")
        return {"success": True, "is_collecting": False}


@app.post("/api/linkedin/stop-collect-contacts")
async def stop_collect_contacts():
    """Stop the ongoing contact collection process."""
    try:
        logger.info("Stop collection request received")

        # Use the controller to stop collection
        result = linkedin_bot_controller.stop_collection_controller()

        if result.get("success"):
            logger.info("Contact collection stopped successfully")
            return {"success": True, "message": "Contact collection stopped"}
        else:
            logger.warning(f"Failed to stop collection: {result.get('message')}")
            return {
                "success": False,
                "message": result.get("message", "Failed to stop collection"),
            }

    except Exception as e:
        logger.exception("Error stopping contact collection")
        return {"success": False, "message": f"Failed to stop collection: {str(e)}"}


@app.post("/api/linkedin/connect-contacts")
async def connect_contacts(request: dict):
    """Send connection requests to contacts."""
    try:
        contacts = request.get("contacts", [])
        use_individual_messages = request.get("use_individual_messages", False)
        message_template = request.get("message_template")

        msg_type = (
            "with individual messages"
            if use_individual_messages
            else "with message"
            if message_template
            else "without message"
        )
        logger.info(
            f"Connection request received for {len(contacts)} contacts " f"({msg_type})"
        )

        if not contacts:
            return {
                "success": False,
                "message": "No contacts provided",
                "connected_count": 0,
            }

        # Use the controller to start connection
        result = linkedin_bot_controller.connect_contacts_controller(
            contacts, message_template, use_individual_messages
        )

        if result.get("success"):
            logger.info("Contact connection started successfully")
            return result
        else:
            logger.warning(f"Failed to start connection: {result.get('message')}")
            return result

    except Exception as e:
        logger.exception("Error starting contact connection")
        return {
            "success": False,
            "message": f"Failed to start connection: {str(e)}",
            "connected_count": 0,
        }


@app.post("/api/linkedin/stop-connect-contacts")
async def stop_connect_contacts():
    """Stop the ongoing contact connection process."""
    try:
        logger.info("Stop connection request received")

        # Use the controller to stop connection
        result = linkedin_bot_controller.stop_connect_controller()

        if result.get("success"):
            logger.info("Contact connection stopped successfully")
            return {"success": True, "message": "Contact connection stopped"}
        else:
            logger.warning(f"Failed to stop connection: {result.get('message')}")
            return {
                "success": False,
                "message": result.get("message", "Failed to stop connection"),
            }

    except Exception as e:
        logger.exception("Error stopping contact connection")
        return {"success": False, "message": f"Failed to stop connection: {str(e)}"}


# Frontend Logging Models
class FrontendLogEntry(BaseModel):
    timestamp: str
    level: str
    process: str
    module: str
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    stack: Optional[str] = None
    url: Optional[str] = None
    userAgent: Optional[str] = None


class FrontendLogsRequest(BaseModel):
    logs: list[FrontendLogEntry]


@app.post("/api/logs/frontend")
async def receive_frontend_logs(request: FrontendLogsRequest):
    """Receive logs from frontend and forward to BetterStack."""
    try:
        from logger import log_frontend_message  # noqa: E402

        for log_entry in request.logs:
            # Forward each log to the backend logger which will send to BetterStack
            log_frontend_message(
                level=log_entry.level.lower(),
                message=f"[{log_entry.module}] {log_entry.message}",
                data={
                    "process": log_entry.process,
                    "module": log_entry.module,
                    "timestamp": log_entry.timestamp,
                    "url": log_entry.url,
                    "userAgent": log_entry.userAgent,
                    "error": log_entry.error,
                    "stack": log_entry.stack,
                    **(log_entry.data or {}),
                },
            )

        return {
            "success": True,
            "message": f"Received and logged {len(request.logs)} frontend log entries",
        }

    except Exception as e:
        logger.exception("Error receiving frontend logs")
        return {
            "success": False,
            "message": f"Failed to log frontend entries: {str(e)}",
        }


if __name__ == "__main__":
    import argparse  # noqa: E402

    parser = argparse.ArgumentParser(description="LinkedIn Bot REST API Server")
    parser.add_argument("--port", type=int, default=58273, help="Port to run server on")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind to")

    args = parser.parse_args()

    logger.info(f"Starting LinkedIn Bot REST API on {args.host}:{args.port}")

    # Signal readiness to Electron BEFORE starting server
    print(
        json.dumps(
            {
                "type": "initialization",
                "status": "complete",
                "server_url": f"http://{args.host}:{args.port}",
            }
        ),
        flush=True,
    )

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
        loop="asyncio",
        access_log=False,  # Reduce logging overhead
        limit_concurrency=1000,  # Allow many concurrent connections
        limit_max_requests=100000,  # Increased limit for long-running infinite hunt (was 10000)
    )
