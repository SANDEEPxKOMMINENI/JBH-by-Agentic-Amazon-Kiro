"""
Application History ID Generator Utility
Generates consistent global IDs for application history tracking
"""

import hashlib
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


def format_hash_as_uuid(hash_string: str) -> str:
    """
    Format a 32-character hash string as UUID format with dashes

    Args:
        hash_string: 32-character hex string (e.g., MD5 hash)

    Returns:
        str: UUID-formatted string (8-4-4-4-12 pattern)

    Example:
        '21c0bd53210d24439b9cdbbc800d0906' -> '21c0bd53-210d-2443-9b9c-dbbc800d0906'
    """
    if len(hash_string) != 32:
        return hash_string  # Return as-is if not standard 32-char hash

    return f"{hash_string[:8]}-{hash_string[8:12]}-{hash_string[12:16]}-{hash_string[16:20]}-{hash_string[20:]}"  # noqa: E501


def generate_job_description_id(application_url: str) -> str:
    """
    Generate job description ID from application_url only (shared across users)

    Args:
        application_url: LinkedIn job URL (required)

    Returns:
        str: Job description ID (UUID-formatted hash)

    Raises:
        ValueError: If application_url is not provided
    """
    if not application_url or not application_url.strip():
        raise ValueError("application_url is required for job description ID")

    try:
        hash_input = application_url.strip().lower()
        hash_string = hashlib.md5(hash_input.encode("utf-8")).hexdigest()
        job_desc_id = format_hash_as_uuid(hash_string)
        logger.debug(f"Generated job_description_id from URL: {job_desc_id}")
        return job_desc_id
    except Exception as e:
        logger.error(f"Error generating job description ID: {e}")
        raise


def generate_application_history_id(
    application_url: str,
    user_id: str,
    linkedin_job_id: Optional[str] = None,
    company_name: Optional[str] = None,
    job_title: Optional[str] = None,
) -> str:
    """
    Generate a consistent user-specific ID for application history tracking

    IMPORTANT: This ID is unique per user + job combination to prevent collisions
    when multiple users apply to the same job.

    Priority order:
    1. Hash of application_url + user_id (most reliable, prevents collisions)
    2. Hash of linkedin_job_id + user_id (for manual jobs)
    3. Hash of company_name + job_title + user_id (fallback)
    4. Hash of timestamp + user_id (last resort)

    Args:
        application_url: LinkedIn job URL (required for priority 1)
        user_id: User ID (required to prevent multi-user collisions)
        linkedin_job_id: LinkedIn job ID or manual job ID (optional)
        company_name: Company name (for fallback)
        job_title: Job title (for fallback)

    Returns:
        str: Application history ID (UUID-formatted hash)

    Raises:
        ValueError: If user_id is not provided
    """
    if not user_id or not user_id.strip():
        raise ValueError("user_id is required to generate application history ID")

    try:
        # Priority 1: application_url + user_id (prevents multi-user collisions)
        if application_url and application_url.strip():
            hash_input = f"{application_url.strip().lower()}_{user_id.strip()}"
            hash_string = hashlib.md5(hash_input.encode("utf-8")).hexdigest()
            app_history_id = format_hash_as_uuid(hash_string)
            logger.debug(
                f"Generated application_history_id from URL+user_id: {app_history_id}"
            )
            return app_history_id

        # Priority 2: linkedin_job_id + user_id (for manual jobs)
        if linkedin_job_id and linkedin_job_id.strip():
            hash_input = f"{linkedin_job_id.strip()}_{user_id.strip()}"
            hash_string = hashlib.md5(hash_input.encode("utf-8")).hexdigest()
            app_history_id = format_hash_as_uuid(hash_string)
            logger.debug(
                f"Generated application_history_id from job_id+user_id: {app_history_id}"
            )
            return app_history_id

        # Priority 3: company_name + job_title + user_id (fallback)
        if company_name and job_title:
            hash_input = f"{company_name.strip().lower()}_{job_title.strip().lower()}_{user_id.strip()}"
            hash_string = hashlib.md5(hash_input.encode("utf-8")).hexdigest()
            app_history_id = format_hash_as_uuid(hash_string)
            logger.debug(
                "Generated application_history_id from company+title+user_id: %s",
                app_history_id,
            )
            return app_history_id

        # Last resort: timestamp + user_id
        fallback_identifier = (
            f"unknown_job_{datetime.now().isoformat()}_{user_id.strip()}"
        )
        hash_string = hashlib.md5(fallback_identifier.encode("utf-8")).hexdigest()
        app_history_id = format_hash_as_uuid(hash_string)
        logger.warning(f"Generated fallback application_history_id: {app_history_id}")
        return app_history_id

    except Exception as e:
        logger.error(f"Error generating application history ID: {e}")
        # Emergency fallback with user_id
        emergency_id = f"error_{datetime.now().timestamp()}_{user_id.strip()}"
        hash_string = hashlib.md5(emergency_id.encode("utf-8")).hexdigest()
        return format_hash_as_uuid(hash_string)
