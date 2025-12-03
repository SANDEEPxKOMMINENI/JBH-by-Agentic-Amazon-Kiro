"""
JWT Token Manager for Local Storage
@file purpose: Manage user JWT tokens stored locally in app data directory
"""

import json
import logging
import os
from typing import Optional

from constants import BASE_DIR

logger = logging.getLogger(__name__)


class JWTTokenManager:
    """Manager for storing and retrieving user JWT tokens locally"""

    def __init__(self):
        self.token_file = os.path.join(BASE_DIR, "user_auth.json")
        self.current_token = None
        self._load_token()

    def _load_token(self):
        """Load saved JWT token from local storage"""  # noqa: E402
        try:
            if os.path.exists(self.token_file):
                with open(self.token_file, "r") as f:
                    data = json.load(f)
                    self.current_token = data.get("jwt_token")
                    if self.current_token:
                        logger.info("Loaded saved JWT token")
        except Exception as e:
            logger.error(f"Error loading JWT token: {e}")
            self.current_token = None

    def save_token(self, jwt_token: str, user_info: dict = None):
        """
        Save JWT token to local storage
        Only replaces existing token when saving new one

        Args:
            jwt_token: JWT token from user authentication  # noqa: E402
            user_info: Optional user information to store
        """
        try:
            # Get existing timestamp if file exists
            timestamp = (
                os.path.getmtime(self.token_file)
                if os.path.exists(self.token_file)
                else 0
            )

            data = {
                "jwt_token": jwt_token,
                "user_info": user_info or {},
                "timestamp": str(timestamp),
            }

            # Ensure directory exists
            os.makedirs(os.path.dirname(self.token_file), exist_ok=True)

            # Save new token (this replaces the old one atomically)
            with open(self.token_file, "w") as f:
                json.dump(data, f, indent=2)

            self.current_token = jwt_token
            logger.info("JWT token saved to local storage")

        except Exception as e:
            logger.error(f"Error saving JWT token: {e}")

    def get_token(self) -> Optional[str]:
        """Get the current JWT token"""
        if self.current_token:
            logger.debug(f"🔑 Retrieved JWT token: {self.current_token[:20]}...")
        else:
            logger.warning("No JWT token available - user may need to re-authenticate")
        return self.current_token

    def clear_token(self):
        """Clear the stored JWT token - only called when replacing with new token"""
        try:
            if os.path.exists(self.token_file):
                os.remove(self.token_file)
            self.current_token = None
            logger.info(
                "🗑JWT token cleared from local storage (preparing for new token)"  # noqa: E402
            )
        except Exception as e:
            logger.error(f"Error clearing JWT token: {e}")

    def is_token_available(self) -> bool:
        """Check if a JWT token is available"""
        return self.current_token is not None

    def is_token_expired(self) -> bool:
        """Check if the current JWT token is expired (without clearing it)"""
        if not self.current_token:
            return True

        try:
            # Decode JWT to check expiration
            import base64  # noqa: E402
            import json  # noqa: E402

            # JWT has 3 parts separated by dots
            parts = self.current_token.split(".")
            if len(parts) != 3:
                logger.warning("Invalid JWT token format")
                return True

            # Decode the payload (second part)
            payload = parts[1]
            # Add padding if needed for base64 decoding
            payload += "=" * (4 - len(payload) % 4)
            decoded_payload = base64.b64decode(payload)
            payload_data = json.loads(decoded_payload)

            # Check if token is expired
            import time  # noqa: E402

            current_time = int(time.time())
            exp_time = payload_data.get("exp", 0)

            is_expired = current_time >= exp_time
            if is_expired:
                logger.info(
                    "JWT token is expired but keeping file for frontend refresh. "
                    f"Current: {current_time}, Exp: {exp_time}"
                )

            return is_expired

        except Exception as e:
            logger.error(f"Error checking token expiration: {e}")
            return True  # Assume expired if we can't decode

    def refresh_token_if_needed(self) -> bool:
        """
        Check if token needs refresh - but don't clear it automatically
        Token refresh should be handled by the frontend
        Returns True if token is valid, False if expired
        """
        if not self.current_token:
            return False

        if self.is_token_expired():
            logger.warning("JWT token is expired - frontend should refresh it")
            # Don't clear the token automatically - let frontend handle refresh
            return False

        return True

    def get_user_info(self) -> dict:
        """Get stored user information"""
        try:
            if os.path.exists(self.token_file):
                with open(self.token_file, "r") as f:
                    data = json.load(f)
                    return data.get("user_info", {})
        except Exception as e:
            logger.error(f"Error loading user info: {e}")
        return {}


# Global token manager instance
jwt_token_manager = JWTTokenManager()
