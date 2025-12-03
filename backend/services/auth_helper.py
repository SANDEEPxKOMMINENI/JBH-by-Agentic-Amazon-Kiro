"""
Authentication Helper for Frontend Integration
@file purpose: Helper functions for managing user authentication flow
"""

import logging
from typing import Any, Dict, Optional

from services.jwt_token_manager import jwt_token_manager
from services.supabase_client import supabase_client

logger = logging.getLogger(__name__)


class AuthHelper:
    """Helper class for authentication operations"""

    @staticmethod
    def save_user_login(jwt_token: str, user_info: Dict[str, Any] = None) -> bool:
        """
        Save user JWT token and info after successful login

        Args:
            jwt_token: JWT token from Supabase authentication  # noqa: E402
            user_info: Optional user information

        Returns:
            True if saved successfully, False otherwise
        """
        try:
            jwt_token_manager.save_token(jwt_token, user_info)
            logger.info("User authentication saved locally")

            # Notify that token has been refreshed - this ensures active services
            # will pick up the new token on their next request
            AuthHelper._notify_token_refresh()

            return True
        except Exception as e:
            logger.error(f"Failed to save user authentication: {e}")
            return False

    @staticmethod
    def _notify_token_refresh():
        """
        Internal method to handle token refresh notifications
        This ensures that all services will pick up the new token
        """
        try:
            # Clear any cached auth tokens in global client instances
            # Since our SupabaseClient now gets tokens dynamically,
            # we just need to log that the token was refreshed
            logger.info(
                "JWT token refreshed - services will use new token on next request"
            )

        except Exception as e:
            logger.error(f"Error during token refresh notification: {e}")

    @staticmethod
    def is_user_authenticated() -> bool:
        """
        Check if user is currently authenticated

        Returns:
            True if user has valid stored token, False otherwise
        """
        return jwt_token_manager.is_token_available()

    @staticmethod
    def get_current_token() -> Optional[str]:
        """
        Get current user's JWT token

        Returns:
            JWT token or None if not authenticated
        """
        return jwt_token_manager.get_token()

    @staticmethod
    def logout_user() -> bool:
        """
        Logout user and clear stored authentication

        Returns:
            True if logout successful, False otherwise
        """
        try:
            jwt_token_manager.clear_token()
            logger.info("User logged out successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to logout user: {e}")
            return False

    @staticmethod
    def test_authentication() -> bool:
        """
        Test if current authentication works with service-gateway

        Returns:
            True if authentication is valid, False otherwise
        """
        try:
            if not jwt_token_manager.is_token_available():
                logger.warning("No authentication token available")
                return False

            # Try to fetch user resumes to test authentication
            client = supabase_client
            resumes = client.get_user_resumes()

            if resumes is not None:
                logger.info("Authentication test successful")
                return True

            logger.warning(
                "Authentication test failed - resume retrieval returned None"
            )
            return False

        except Exception as e:
            logger.error(f"Authentication test failed: {e}")
            return False

    @staticmethod
    def get_user_info() -> Dict[str, Any]:
        """
        Get stored user information

        Returns:
            User information dictionary
        """
        return jwt_token_manager.get_user_info()


# Global auth helper instance
auth_helper = AuthHelper()
