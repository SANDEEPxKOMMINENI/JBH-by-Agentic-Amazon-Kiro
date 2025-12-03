import logging
from typing import Any, Dict, Optional, Union

import requests

logger = logging.getLogger(__name__)


class AIEngineClient:
    """Client for calling the service-gateway AI engine API"""

    def __init__(
        self,
        service_gateway_url: Optional[str] = None,
        auth_token: Optional[str] = None,
    ):
        from constants import SERVICE_GATEWAY_URL  # noqa: E402

        self.base_url = service_gateway_url or SERVICE_GATEWAY_URL
        self.api_url = f"{self.base_url}/ai-engine"
        self.auth_token = auth_token  # Store explicit token if provided

        # Setup session with basic headers
        self.session = requests.Session()
        self.session.headers.update(
            {"Content-Type": "application/json", "User-Agent": "JobHuntr-Backend/2.0"}
        )

        # Note: Auth header will be set dynamically per request

    def call_ai(
        self,
        prompt: str,
        system: Optional[str] = "",
        format: Optional[Dict[str, Any]] = None,
        model: Optional[str] = "gpt-4.1",
        additional_system_prompt: Optional[str] = "",
        retry_times: Optional[int] = 3,
        application_id: Optional[str] = None,
    ) -> Union[Dict[str, Any], str, None]:
        """
        Call the AI engine through service gateway

        Args:
            prompt: The main prompt/query to send to AI
            system: System prompt to set context
            format: Expected response format (for structured responses)
            model: AI model to use
            additional_system_prompt: Additional system context
            retry_times: Number of retries on failure
            application_id: Application ID for tracking (optional)

        Returns:
            AI response result or None on failure
        """
        try:
            # Get current token dynamically
            from services.jwt_token_manager import jwt_token_manager  # noqa: E402

            # Refresh token if needed
            if not self.auth_token:
                jwt_token_manager.refresh_token_if_needed()

            current_token = self.auth_token or jwt_token_manager.get_token()

            # Prepare headers with fresh auth token
            headers = {}
            if current_token:
                headers["Authorization"] = f"Bearer {current_token}"
                logger.debug(f"Using JWT token: {current_token[:20]}...")
            else:
                logger.warning("No JWT token available - may need to re-auth")

            payload = {
                "prompt": prompt,
                "system": system,
                "format": format,
                "model": model,
                "additional_system_prompt": additional_system_prompt,
                "retry_times": retry_times,
                "application_id": application_id,
            }

            response = self.session.post(
                f"{self.api_url}/call", json=payload, headers=headers, timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    return result.get("result")
                else:
                    logger.error(f"AI call failed: {result.get('error')}")
                    return None
            else:
                logger.error(
                    "HTTP error calling AI engine: "
                    f"{response.status_code} - {response.text}"
                )
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error calling AI engine: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error calling AI engine: {e}")
            return None

    def health_check(self) -> bool:
        """
        Check if the AI engine service is healthy

        Returns:
            True if service is healthy, False otherwise
        """
        try:
            # Get current token dynamically for health check
            from services.jwt_token_manager import jwt_token_manager  # noqa: E402

            # Refresh token if needed
            if not self.auth_token:
                jwt_token_manager.refresh_token_if_needed()

            current_token = self.auth_token or jwt_token_manager.get_token()

            # Prepare headers with fresh auth token
            headers = {}
            if current_token:
                headers["Authorization"] = f"Bearer {current_token}"

            response = self.session.get(
                f"{self.api_url}/health", headers=headers, timeout=10
            )

            if response.status_code == 200:
                result = response.json()
                return result.get("status") == "healthy"
            else:
                return False

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False
