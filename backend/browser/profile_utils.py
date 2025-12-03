import os
from typing import Optional

from constants import BASE_DIR
from services.auth_helper import auth_helper

PROFILE_NAME_PREFIX = "jobhuntr_chrome_profile"
LEGACY_PROFILE_NAME = "jobhuntr-chrome-profile"
DEFAULT_PROFILE_SUFFIX = "default"


def _sanitize_local_part(local_part: Optional[str]) -> str:
    if not local_part:
        return DEFAULT_PROFILE_SUFFIX

    sanitized = "".join(ch for ch in local_part.lower() if ch.isalnum())
    return sanitized or DEFAULT_PROFILE_SUFFIX


def _extract_local_part(user_email: Optional[str]) -> str:
    if not user_email:
        return DEFAULT_PROFILE_SUFFIX

    local_part = user_email.split("@")[0]
    return _sanitize_local_part(local_part)


def _resolve_email(provided_email: Optional[str] = None) -> Optional[str]:
    if provided_email:
        return provided_email

    user_info = auth_helper.get_user_info() or {}
    return (
        user_info.get("email")
        or user_info.get("user_metadata", {}).get("email")
        or user_info.get("user_metadata", {}).get("preferred_email")
    )


def get_jobhuntr_profile_name(user_email: Optional[str] = None) -> str:
    email = _resolve_email(user_email)
    suffix = _extract_local_part(email)
    return f"{PROFILE_NAME_PREFIX}_{suffix}"


def get_jobhuntr_profile_path(user_email: Optional[str] = None) -> str:
    return os.path.join(BASE_DIR, get_jobhuntr_profile_name(user_email))
