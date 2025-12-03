"""
Supabase Client for Backend
@file purpose: Client to communicate with service-gateway for Supabase operations
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

import requests

from constants import SERVICE_GATEWAY_URL
from services.jwt_token_manager import jwt_token_manager  # noqa: E402
from shared.models import (  # noqa: E402
    AgentRunTemplate,
    InfiniteRun,
    Resume,
    UserFaq,
    WorkflowRun,
)
from shared.models.cover_letter_template import CoverLetterTemplate  # noqa: E402

logger = logging.getLogger(__name__)


class SupabaseClient:
    """Client for Supabase operations through service-gateway

    Authentication: Uses Supabase's built-in auth.users table (no separate user_profiles needed)  # noqa: E501
    Data tables: user_faq, resumes, workflow_runs, workflows, ats_templates
    """

    def __init__(self, auth_token: Optional[str] = None):
        """
        Initialize the Supabase client

        Args:
            auth_token: JWT token for authentication (if None, uses stored token dynamically)  # noqa: E501
        """
        self.base_url = SERVICE_GATEWAY_URL
        # Only store auth_token if explicitly provided, otherwise always get fresh token
        self.auth_token = auth_token if auth_token else None
        self.session = requests.Session()

        # Set default headers
        self.session.headers.update(
            {"Content-Type": "application/json", "User-Agent": "JobHuntr-Backend/2.0"}
        )

        # Note: Auth header is set dynamically in _make_request to always get latest token  # noqa: E501

    def _get_auth_headers(self) -> dict[str, str]:
        """
        Get authentication headers for making requests

        Returns:
            Dictionary with Authorization header if token is available
        """
        headers: dict[str, str] = {}
        current_token = jwt_token_manager.get_token() or self.auth_token
        if current_token:
            headers["Authorization"] = f"Bearer {current_token}"
        return headers

    def _make_request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """
        Make a request to the service gateway

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (without base URL)
            **kwargs: Additional arguments for requests

        Returns:
            Response object
        """
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"

        # Always get the latest token from storage first, fallback to provided token
        current_token = jwt_token_manager.get_token() or self.auth_token

        # Set auth header for this request if token is available
        headers = kwargs.get("headers", {})
        if current_token:
            headers["Authorization"] = f"Bearer {current_token}"
            kwargs["headers"] = headers
        else:
            logger.warning("No JWT token available for service-gateway request")

        try:
            response = self.session.request(method, url, timeout=30, **kwargs)

            # Handle 401 errors by checking if token needs refresh
            if response.status_code == 401:
                logger.warning("Received 401 - checking if token is expired")
                if jwt_token_manager.is_token_expired():
                    logger.error("JWT token is expired - user needs to re-authenticate")
                else:
                    logger.error(
                        "JWT token appears valid but received 401 - "
                        "possible server issue"
                    )

            return response
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {method} {url} - {e}")
            raise

    def get_user_faq(self, user_id: Optional[str] = None) -> Optional[List[UserFaq]]:
        """
        Get user FAQ templates from database  # noqa: E402

        Note: User filtering is handled automatically by the service gateway
        through JWT authentication.
        The user_id parameter is kept for compatibility but not used in the API call.

        Returns:
            List of UserFaq models or empty list if none found, None if error
        """
        try:
            # Note: The service gateway automatically filters by authenticated user's ID
            # so we don't need to pass user_id as a parameter
            logger.debug(
                "Making FAQ request to /api/faq/ "
                "(user filtering handled by JWT auth)"
            )
            response = self._make_request(
                "GET", "/api/faq/"  # Service gateway handles user filtering via JWT
            )

            response_snippet = response.text[:200] if response.text else "No content"
            logger.debug(
                "FAQ API response: %s - %s",
                response.status_code,
                response_snippet,
            )

            if response.status_code == 200:
                data = response.json()

                # Handle both direct list and wrapped response formats
                faq_data = []
                if isinstance(data, dict) and "faq_questions" in data:
                    faq_data = data["faq_questions"]
                elif isinstance(data, dict) and "faqs" in data:
                    faq_data = data["faqs"]
                elif isinstance(data, list):
                    faq_data = data

                logger.debug(f"Processed FAQ data: {len(faq_data)} items")

                # Convert to UserFaq models
                faqs = []
                for faq_item in faq_data:
                    try:
                        logger.debug(f"Processing FAQ item: {faq_item}")
                        faq = UserFaq(**faq_item)
                        faqs.append(faq)
                    except Exception as model_error:
                        logger.warning(
                            f"Failed to parse FAQ item {faq_item}: {model_error}"
                        )
                        continue

                logger.debug(f"Successfully converted {len(faqs)} FAQ items to models")
                return faqs

            elif response.status_code == 401:
                logger.warning(
                    "Authentication required for FAQ access - returning empty list"
                )
                return []
            else:
                logger.error(
                    f"Failed to get user FAQ: {response.status_code} - "
                    f"{response.text}"
                )
                return None

        except Exception as e:
            logger.error(f"Error getting user FAQ: {e}")
            import traceback  # noqa: E402

            logger.debug("FAQ error traceback: %s", traceback.format_exc())
            return None

    def get_user_resumes(self, user_id: Optional[str] = None) -> Optional[List[Resume]]:
        """
        Get user resumes from database  # noqa: E402

        Note: User filtering is handled automatically by the service gateway
        through JWT authentication.
        The user_id parameter is kept for compatibility but not used in the API call.

        Returns:
            List of Resume models or empty list if none found, None if error
        """
        try:
            response = self._make_request(
                "GET",
                "/api/resume/list",  # Use the actual resume list endpoint we found
            )

            if response.status_code == 200:
                data = response.json()

                # Handle both direct list and wrapped response formats
                resume_data = []
                if isinstance(data, dict) and "resumes" in data:
                    resume_data = data["resumes"]
                elif isinstance(data, list):
                    resume_data = data

                # Convert to Resume models
                resumes = []
                for resume_item in resume_data:
                    try:
                        resume = Resume(**resume_item)
                        resumes.append(resume)
                    except Exception as model_error:
                        logger.warning(f"Failed to parse resume item: {model_error}")
                        continue

                return resumes

            elif response.status_code == 401:
                logger.warning(
                    "Authentication required for resume access - returning empty list"
                )
                return []
            else:
                logger.error(
                    f"Failed to get user resumes: {response.status_code} - "
                    f"{response.text}"
                )
                return None

        except Exception as e:
            logger.error(f"Error getting user resumes: {e}")
            return None

    def get_resume_by_id(self, resume_id: str) -> Optional[Resume]:
        """
        Get a specific resume by ID

        Args:
            resume_id: Resume ID to fetch

        Returns:
            Resume model or None if not found/error
        """
        try:
            response = self._make_request("GET", f"/api/resume/{resume_id}")

            if response.status_code == 200:
                data = response.json()
                try:
                    return Resume(**data)
                except Exception as model_error:
                    logger.warning(f"Failed to parse resume: {model_error}")
                    return None

            elif response.status_code == 401:
                logger.warning("Authentication required for resume access")
                return None
            elif response.status_code == 404:
                logger.warning(f"Resume {resume_id} not found")
                return None
            else:
                logger.error(
                    f"Failed to get resume: {response.status_code} - "
                    f"{response.text}"
                )
                return None

        except Exception as e:
            logger.error(f"Error getting resume by ID: {e}")
            return None

    def get_cover_letter_template_by_id(
        self, template_id: str
    ) -> Optional[CoverLetterTemplate]:
        """
        Get a specific cover letter template by ID

        Args:
            template_id: Cover letter template ID to fetch

        Returns:
            CoverLetterTemplate model or None if not found/error
        """
        try:
            response = self._make_request(
                "GET", f"/api/cover-letter/templates/{template_id}"
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("success") and data.get("template"):
                    template_data = data["template"]
                    try:
                        return CoverLetterTemplate(**template_data)
                    except Exception as model_error:
                        logger.warning(
                            f"Failed to parse cover letter template: {model_error}"
                        )
                        return None
                else:
                    logger.warning(f"Invalid response format: {data}")
                    return None

            elif response.status_code == 401:
                logger.warning(
                    "Authentication required for cover letter template access"
                )
                return None
            elif response.status_code == 404:
                logger.warning(f"Cover letter template {template_id} not found")
                return None
            else:
                logger.error(
                    f"Failed to get cover letter template: {response.status_code} - "
                    f"{response.text}"
                )
                return None

        except Exception as e:
            logger.error(f"Error getting cover letter template by ID: {e}")
            return None

    def get_agent_run_template_by_id(
        self, template_id: str
    ) -> Optional[AgentRunTemplate]:
        """
        Get a specific agent run template by ID

        Args:
            template_id: Agent run template ID to fetch

        Returns:
            AgentRunTemplate model or None if not found/error
        """
        try:
            response = self._make_request(
                "GET", f"/api/agent-run-templates/{template_id}"
            )

            if response.status_code == 200:
                data = response.json()
                try:
                    return AgentRunTemplate(**data)
                except Exception as model_error:
                    logger.warning(f"Failed to parse agent run template: {model_error}")
                    return None

            elif response.status_code == 401:
                logger.warning("Authentication required for agent run template access")
                return None
            elif response.status_code == 404:
                logger.warning(f"Agent run template {template_id} not found")
                return None
            else:
                logger.error(
                    f"Failed to get agent run template: {response.status_code} - "
                    f"{response.text}"
                )
                return None

        except Exception as e:
            logger.error(f"Error getting agent run template by ID: {e}")
            return None

    def get_workflow_run(self, run_id: str) -> Optional[WorkflowRun]:
        """
        Get a specific workflow run by ID

        Args:
            run_id: Workflow run ID to fetch

        Returns:
            WorkflowRun model or None if not found/error
        """
        try:
            response = self._make_request("GET", f"/api/workflow-runs/{run_id}")

            if response.status_code == 200:
                data = response.json()
                try:
                    return WorkflowRun(**data)
                except Exception as model_error:
                    logger.warning(f"Failed to parse workflow run: {model_error}")
                    return None

            elif response.status_code == 401:
                logger.warning("Authentication required for workflow run access")
                return None
            elif response.status_code == 404:
                logger.warning(f"Workflow run {run_id} not found")
                return None
            else:
                logger.error(
                    f"Failed to get workflow run: {response.status_code} - "
                    f"{response.text}"
                )
                return None

        except Exception as e:
            logger.error(f"Error getting workflow run: {e}")
            return None

    def list_workflow_runs(
        self,
        *,
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 25,
    ) -> List[WorkflowRun]:
        """
        Fetch workflow runs for the authenticated user via the service gateway.
        """
        params = []
        if workflow_id:
            params.append(f"workflow_id={workflow_id}")
        if status:
            params.append(f"status={status}")
        params.append(f"page={page}")
        params.append(f"page_size={page_size}")
        endpoint = "/api/workflow-runs/"
        if params:
            endpoint = f"{endpoint}?{'&'.join(params)}"

        try:
            response = self._make_request("GET", endpoint)
            if response.status_code != 200:
                logger.error(
                    "Failed to list workflow runs: %s - %s",
                    response.status_code,
                    response.text,
                )
                return []

            payload = response.json()
            runs_payload = payload.get("runs") or []
            results: List[WorkflowRun] = []
            for run_data in runs_payload:
                try:
                    results.append(WorkflowRun(**run_data))
                except Exception as exc:
                    logger.warning("Failed to parse workflow run: %s", exc)
            return results
        except Exception as exc:
            logger.error("Error listing workflow runs: %s", exc)
            return []

    def get_latest_workflow_run(self, workflow_id: str) -> Optional[WorkflowRun]:
        """
        Convenience helper that fetches the most recent run for a workflow.
        """
        runs = self.list_workflow_runs(
            workflow_id=workflow_id,
            page=1,
            page_size=1,
        )
        return runs[0] if runs else None

    def create_workflow_run(self, payload: Dict[str, Any]) -> Optional[WorkflowRun]:
        """
        Create a new workflow run record using the service gateway API.
        Ensures the payload is JSON-serializable (e.g., converts UUIDs to strings).
        """

        def _json_safe(value: Any) -> Any:
            if isinstance(value, UUID):
                return str(value)
            if isinstance(value, dict):
                return {k: _json_safe(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [_json_safe(v) for v in value]
            return value

        safe_payload = _json_safe(payload)

        try:
            response = self._make_request(
                "POST",
                "/api/workflow-runs/",
                json=safe_payload,
            )
            if response.status_code not in (200, 201):
                logger.error(
                    "Failed to create workflow run: %s - %s",
                    response.status_code,
                    response.text,
                )
                return None
            run_data = response.json()
            return WorkflowRun(**run_data)
        except Exception as exc:
            logger.error("Error creating workflow run: %s", exc)
            return None

    def get_workflow_run_by_run_id(self, run_id: str) -> Optional[WorkflowRun]:
        """
        Get a workflow run by run id

        Args:
            run_id: Workflow run ID to fetch runs for

        Returns:
            Most recent WorkflowRun model for this workflow or None if not found/error
        """
        try:
            # Get workflow run by run_id
            logger.info(f"Making request to get workflow run: {run_id}")
            response = self._make_request("GET", f"/api/workflow-runs/{run_id}")
            logger.info(
                f"Response status: {response.status_code}, Response text: {response.text[:500]}"  # noqa: E501
            )

            if response.status_code == 200:
                data = response.json()

                # Handle single WorkflowRunResponse from the specific endpoint
                if isinstance(data, dict):
                    try:
                        # The response should be a single workflow run object
                        logger.debug(f"Parsing workflow run data: {data}")
                        workflow_run = WorkflowRun(**data)
                        logger.info(
                            f"Successfully parsed workflow run: {workflow_run.id}"
                        )
                        return workflow_run
                    except Exception as model_error:
                        logger.error(f"Failed to parse workflow run: {model_error}")
                        logger.error(f"Raw workflow data: {data}")
                        import traceback  # noqa: E402

                        logger.error(f"Traceback: {traceback.format_exc()}")
                        return None
                else:
                    logger.warning(f"Unexpected response format for run_id {run_id}")
                    return None

            elif response.status_code == 401:
                logger.warning("Authentication required for workflow run access")
                return None
            elif response.status_code == 404:
                logger.warning(f"No workflow runs found for run_id {run_id}")
                return None
            else:
                logger.error(
                    f"Failed to get workflow runs: {response.status_code} - "
                    f"{response.text}"
                )
                return None

        except Exception as e:
            logger.error(f"Error getting workflow run by run_id: {e}")
            return None

    def get_authenticated_user_id(self) -> Optional[str]:
        """
        Check if user is authenticated (has valid token)
        Note: In service-gateway architecture, we don't extract user_id locally

        Returns:
            True if token exists (service-gateway validates), None otherwise
        """
        return "authenticated" if self.auth_token else None

    def query_database(
        self,
        table: str,
        operation: str = "select",
        data: Optional[Dict[str, Any]] = None,
        filters: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Execute a database query through service gateway

        Args:
            table: Table name to query
            operation: Database operation (select, insert, update, delete)
            data: Data for insert/update operations
            filters: Filter string for queries

        Returns:
            Query result or None on failure
        """
        try:
            payload = {"table": table, "operation": operation}

            if data:
                payload["data"] = data
            if filters:
                payload["filters"] = filters

            response = self._make_request("POST", "/api/supabase/query", json=payload)

            if response.status_code in [200, 201, 204]:
                return response.json() if response.content else {"success": True}
            else:
                logger.error(
                    f"Database query failed: {response.status_code} - "
                    f"{response.text}"
                )
                return None

        except Exception as e:
            logger.error(f"Error executing database query: {e}")
            return None

    def update_auth_token(self, token: str):
        """
        Update the authentication token

        Args:
            token: New JWT token
        """
        self.auth_token = token
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        logger.info("Auth token updated")

    def clear_auth_token(self):
        """Clear the authentication token"""
        self.auth_token = None
        if "Authorization" in self.session.headers:
            del self.session.headers["Authorization"]
        logger.info("Auth token cleared")

    def create_application_history(self, application_data: Dict[str, Any]) -> bool:
        """
        Create a new application history record

        Args:
            application_data: Dictionary containing application information

        Returns:
            True if successful, False otherwise

        Raises:
            SubscriptionLimitException: When user has reached their
            application limit (402)
        """
        try:
            logger.debug(
                "Creating application history with data: %s",
                list(application_data.keys()),
            )

            response = self._make_request(
                "POST",
                "/api/application-history/",
                json=application_data,
            )

            if response.status_code in [200, 201]:
                logger.info(
                    f"Application history created successfully with id: {application_data.get('id')}"
                )
                return True
            elif response.status_code == 402:
                # Handle subscription limit reached
                logger.warning(
                    "Application limit reached - subscription upgrade required"
                )
                try:
                    from exceptions import SubscriptionLimitException  # noqa: E402

                    error_detail = response.json().get("detail", {})
                    if isinstance(error_detail, str):
                        # If detail is a string, create default values
                        raise SubscriptionLimitException(
                            message=error_detail,
                            tier="free",
                            limit=0,
                            used=0,
                            remaining=0,
                        )
                    else:
                        # Parse the detailed error response
                        raise SubscriptionLimitException(
                            message=error_detail.get(
                                "message", "Application limit reached"
                            ),
                            tier=error_detail.get("tier", "free"),
                            limit=error_detail.get("limit", 0),
                            used=error_detail.get("used", 0),
                            remaining=error_detail.get("remaining", 0),
                        )
                except SubscriptionLimitException:
                    raise  # Re-raise the exception we just created
                except Exception as parse_error:
                    logger.error(f"Failed to parse 402 response: {parse_error}")
                    # Raise a generic subscription exception
                    from exceptions import SubscriptionLimitException  # noqa: E402

                    raise SubscriptionLimitException(
                        message=(
                            "Application limit reached. Please upgrade "
                            "your subscription."
                        ),
                        tier="free",
                        limit=0,
                        used=0,
                        remaining=0,
                    )
            elif response.status_code == 429:
                # Handle rate limit / daily limit reached
                logger.warning("Daily limit reached - rate limit exceeded")
                try:
                    from exceptions import DailyLimitException  # noqa: E402

                    error_detail = response.json()
                    if isinstance(error_detail, str):
                        # If detail is a string, create default values
                        raise DailyLimitException(
                            message=error_detail,
                            daily_limit=0,
                            daily_used=0,
                            daily_remaining=0,
                            next_reset="",
                        )
                    else:
                        # Parse the detailed error response with correct field names
                        raise DailyLimitException(
                            message=error_detail.get("message", "Daily limit reached"),
                            daily_limit=error_detail.get("daily_limit", 0),
                            daily_used=error_detail.get("daily_used", 0),
                            daily_remaining=error_detail.get("daily_remaining", 0),
                            next_reset=error_detail.get("next_reset", ""),
                        )
                except DailyLimitException:
                    raise  # Re-raise the exception we just created
                except Exception as parse_error:
                    logger.error(f"Failed to parse 429 response: {parse_error}")
                    # Raise a generic daily limit exception
                    from exceptions import DailyLimitException  # noqa: E402

                    raise DailyLimitException(
                        message="Daily limit reached. Please try again later.",
                        daily_limit=0,
                        daily_used=0,
                        daily_remaining=0,
                        next_reset="",
                    )
            else:
                logger.error(
                    f"Failed to create application history: {response.status_code} - "
                    f"{response.text}"
                )
                return False

        except Exception as e:
            # Re-raise limit exceptions without catching them
            from exceptions import DailyLimitException  # noqa: E402
            from exceptions import SubscriptionLimitException  # noqa: E402

            if isinstance(e, (SubscriptionLimitException, DailyLimitException)):
                raise
            logger.error(f"Error creating application history: {e}")
            return False

    def update_application_history(
        self, app_history_id: str, application_data: Dict[str, Any]
    ) -> bool:
        """
        Update an existing application history record with partial data

        Args:
            app_history_id: Application history ID to update
            application_data: Dictionary containing only the attributes to update

        Returns:
            True if successful, False otherwise
        """
        try:
            logger.debug(
                f"Updating {app_history_id} with attributes: {list(application_data.keys())}"  # noqa: E501
            )

            response = self._make_request(
                "PUT",
                f"/api/application-history/{app_history_id}",
                json=application_data,
            )

            if response.status_code in [200, 204]:
                logger.info(
                    f"Application history updated successfully for job {app_history_id}"
                )
                return True
            else:
                logger.error(
                    f"Failed to update application history: {response.status_code} - "
                    f"{response.text}"
                )
                return False

        except Exception as e:
            logger.error(f"Error updating application history: {e}")
            return False

    def get_application_history(
        self, user_id: Optional[str] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get application history for the authenticated user

        Args:
            user_id: User ID (optional, handled by JWT auth)

        Returns:
            List of application history records or None if error
        """
        try:
            response = self._make_request("GET", "/api/application-history/")

            if response.status_code == 200:
                data = response.json()

                # Handle both direct list and wrapped response formats
                if isinstance(data, dict) and "applications" in data:
                    return data["applications"]
                elif isinstance(data, list):
                    return data
                else:
                    return []

            elif response.status_code == 401:
                logger.warning("Authentication required for application history access")
                return []
            else:
                logger.error(
                    f"Failed to get application history: {response.status_code} - "
                    f"{response.text}"
                )
                return None

        except Exception as e:
            logger.error(f"Error getting application history: {e}")
            return None

    def get_application_history_by_id(
        self, app_history_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get a specific application history record by its ID

        Args:
            app_history_id: Application history ID to fetch

        Returns:
            Application history record or None if not found/error
        """
        try:
            response = self._make_request(
                "GET", f"/api/application-history/{app_history_id}"
            )

            if response.status_code == 200:
                data = response.json()

                # Handle wrapped response format
                if isinstance(data, dict) and "application" in data:
                    return data["application"]
                else:
                    return data

            elif response.status_code == 404:
                logger.info(f"Application history record {app_history_id} not found")
                return None
            else:
                logger.error(
                    f"Failed to get application history by ID: {response.status_code} - "  # noqa: E501
                    f"{response.text}"
                )
                return None

        except Exception as e:
            logger.error(
                f"Error getting application history by ID {app_history_id}: {e}"
            )
            return None

    def get_applications_by_status(
        self, status: str, user_id: Optional[str] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get application history records filtered by status, ordered by created_at ascending  # noqa: E501

        Args:
            status: Application status to filter by (e.g., "submitting")
            user_id: User ID (optional, handled by JWT auth)

        Returns:
            List of application history records with the specified status or None if error  # noqa: E501
        """
        try:
            # Use the query_database method to filter by status
            filters = f"status=eq.{status}&order=created_at.asc"

            result = self.query_database(
                table="application_history", operation="select", filters=filters
            )

            if result:
                # The result should be a list of applications
                if isinstance(result, list):
                    return result
                elif isinstance(result, dict) and "data" in result:
                    return result["data"]
                else:
                    logger.warning(
                        f"Unexpected response format for status query: {result}"
                    )
                    return []
            else:
                logger.info(f"No applications found with status: {status}")
                return []

        except Exception as e:
            logger.error(f"Error getting applications by status {status}: {e}")
            return None

    def get_applications_by_status_and_workflow(
        self, status: str, workflow_run_id: str, user_id: Optional[str] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get application history records filtered by status and workflow_run_id, ordered by created_at ascending  # noqa: E501

        Args:
            status: Application status to filter by (e.g., "submitting")
            workflow_run_id: Workflow run ID to filter by
            user_id: User ID (optional, handled by JWT auth)

        Returns:
            List of application history records with the specified status and workflow_run_id or None if error  # noqa: E501
        """
        try:
            # Use the query_database method to filter by status and workflow_run_id
            filters = f"status=eq.{status}&workflow_run_id=eq.{workflow_run_id}&order=created_at.asc"  # noqa: E501

            result = self.query_database(
                table="application_history", operation="select", filters=filters
            )

            if result:
                # The result should be a list of applications
                if isinstance(result, list):
                    return result
                elif isinstance(result, dict) and "data" in result:
                    return result["data"]
                else:
                    logger.warning(
                        f"Unexpected response format for status and workflow query: {result}"  # noqa: E501
                    )
                    return []
            else:
                logger.info(
                    f"No applications found with status: {status} and workflow_run_id: {workflow_run_id}"  # noqa: E501
                )
                return []

        except Exception as e:
            logger.error(
                f"Error getting applications by status {status} and workflow {workflow_run_id}: {e}"  # noqa: E501
            )
            return None

    def create_or_update_job_description(
        self, job_description_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Create or update a job description (upsert operation)

        Args:
            job_description_data: Dictionary containing job description information

        Returns:
            Created/updated job description record or None if error
        """
        try:
            logger.debug(
                "Creating/updating job description with ID: %s",
                job_description_data.get("id"),
            )

            response = self._make_request(
                "POST",
                "/api/job-descriptions/",
                json=job_description_data,
            )

            if response.status_code in [200, 201]:
                result = response.json()
                logger.info(
                    f"Job description created/updated successfully: {job_description_data.get('id')}"
                )
                return result
            else:
                logger.error(
                    f"Failed to create/update job description: {response.status_code} - {response.text}"
                )
                return None

        except Exception as e:
            logger.error(f"Error creating/updating job description: {e}")
            return None

    def get_job_description_by_id(
        self, job_description_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get a job description by ID

        Args:
            job_description_id: Job description ID

        Returns:
            Job description record or None if not found
        """
        try:
            response = self._make_request(
                "GET",
                f"/api/job-descriptions/{job_description_id}",
            )

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                logger.debug(f"Job description not found: {job_description_id}")
                return None
            else:
                logger.error(
                    f"Failed to get job description: {response.status_code} - {response.text}"
                )
                return None

        except Exception as e:
            logger.error(f"Error getting job description {job_description_id}: {e}")
            return None

    def get_job_description_by_url(
        self, application_url: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get a job description by application URL

        Args:
            application_url: LinkedIn job URL

        Returns:
            Job description record or None if not found
        """
        try:
            response = self._make_request(
                "GET",
                f"/api/job-descriptions/by-url/?url={application_url}",
            )

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                logger.debug(f"Job description not found for URL: {application_url}")
                return None
            else:
                logger.error(
                    f"Failed to get job description by URL: {response.status_code} - {response.text}"
                )
                return None

        except Exception as e:
            logger.error(f"Error getting job description by URL {application_url}: {e}")
            return None

    def create_contact(self, contact_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Create a new contact record

        Args:
            contact_data: Dictionary containing contact information

        Returns:
            Created contact record or None if error
        """
        try:
            response = self._make_request(
                "POST",
                "/api/contacts/",
                json=contact_data,
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("success") and result.get("contact"):
                    logger.info(
                        f"Contact created successfully: " f"{contact_data.get('name')}"
                    )
                    return result["contact"]
                else:
                    logger.warning(f"Unexpected response format: {result}")
                    return None
            else:
                logger.error(
                    f"Failed to create contact: {response.status_code} - "
                    f"{response.text}"
                )
                return None

        except Exception as e:
            logger.error(f"Error creating contact: {e}")
            import traceback  # noqa: E402

            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    def get_contacts(
        self,
        application_history_id: Optional[str] = None,
        status: Optional[str] = None,
        category: Optional[str] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get contacts with optional filters

        Args:
            application_history_id: Filter by application
            status: Filter by status (collected, listed, outreached)
            category: Filter by category (recruiter, peer, hiring_manager)

        Returns:
            List of contacts or None if error
        """
        try:
            # Build query params
            params = []
            if application_history_id:
                params.append(f"application_history_id={application_history_id}")
            if status:
                params.append(f"status={status}")
            if category:
                params.append(f"category={category}")

            endpoint = "/api/contacts/"
            if params:
                endpoint += "?" + "&".join(params)

            response = self._make_request("GET", endpoint)

            if response.status_code == 200:
                data = response.json()

                # Handle wrapped response
                if isinstance(data, dict) and "contacts" in data:
                    return data["contacts"]
                elif isinstance(data, list):
                    return data
                else:
                    return []

            elif response.status_code == 401:
                logger.warning("Authentication required for contacts access")
                return []
            else:
                logger.error(
                    f"Failed to get contacts: {response.status_code} - "
                    f"{response.text}"
                )
                return None

        except Exception as e:
            logger.error(f"Error getting contacts: {e}")
            return None

    def update_contact(
        self, contact_id: str, update_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Update a contact record

        Args:
            contact_id: Contact ID to update
            update_data: Dictionary containing fields to update

        Returns:
            Updated contact record or None if error
        """
        try:
            response = self._make_request(
                "PATCH",
                f"/api/contacts/{contact_id}",
                json=update_data,
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("success") and result.get("contact"):
                    logger.info(f"Contact {contact_id} updated successfully")
                    return result["contact"]
                else:
                    logger.warning(f"Unexpected response format: {result}")
                    return None
            else:
                logger.error(
                    f"Failed to update contact: {response.status_code} - "
                    f"{response.text}"
                )
                return None

        except Exception as e:
            logger.error(f"Error updating contact: {e}")
            return None

    def get_staffing_companies(self) -> List[Dict[str, Any]]:
        """
        Get all staffing companies from database  # noqa: E402

        Note: User filtering is handled automatically by the service gateway
        through JWT authentication.

        Returns:
            List of staffing company dictionaries or empty list if none found/error
        """
        try:
            logger.debug(
                "Fetching staffing companies from service gateway"
            )  # noqa: E402
            response = self._make_request("GET", "/api/company/staffing-companies")

            if response.status_code == 200:
                data = response.json()

                # Return the list directly (service gateway returns a list)
                if isinstance(data, list):
                    return data
                else:
                    logger.warning(f"Unexpected response format: {type(data)}")
                    return []
            else:
                logger.warning(
                    f"Failed to get staffing companies: {response.status_code} - {response.text}"  # noqa: E501
                )
                return []

        except Exception as e:
            logger.error(f"Error getting staffing companies: {e}")
            return []

    def get_user_additional_info(self) -> Optional[str]:
        """
        Fetch About Me body text for the authenticated user.
        Returns the body string directly, or None if not found.
        """
        try:
            response = self._make_request("GET", "/api/about-me/info")
            if response.status_code != 200:
                logger.error("Failed to fetch additional info: %s", response.text)
                return None

            data = response.json() or {}
            # API returns a single entry in "additional_info" field
            entry = data.get("additional_info")
            if entry and isinstance(entry, dict):
                return entry.get("body", "")
            return None
        except Exception as exc:
            logger.error("Error getting additional info: %s", exc)
            return None

    def get_infinite_run(self) -> Optional[InfiniteRun]:
        """
        Return the persisted infinite hunt configuration for the current user.
        """
        try:
            response = self._make_request("GET", "/api/infinite-runs/me")
            if response.status_code != 200:
                # 404 is expected when no infinite run exists for the user
                if response.status_code == 404:
                    logger.debug("No infinite run config found for user")
                else:
                    logger.error(
                        "Failed to fetch infinite run config: %s", response.text
                    )
                return None

            payload = response.json()
            run_data = payload.get("infinite_run")
            if not run_data:
                return None
            return InfiniteRun(**run_data)
        except Exception as exc:
            logger.error("Error fetching infinite run: %s", exc)
            return None

    def save_infinite_run_config(
        self, config: Dict[str, Any], status: Optional[str] = None
    ) -> Optional[InfiniteRun]:
        """
        Persist new configuration/settings for the infinite hunt loop.
        """
        try:
            body: Dict[str, Any] = {"config": config}
            if status:
                body["status"] = status

            response = self._make_request(
                "POST",
                "/api/infinite-runs/",
                json=body,
            )

            if response.status_code not in (200, 201):
                logger.error("Failed to save infinite run config: %s", response.text)
                return None

            payload = response.json()
            run_data = payload.get("infinite_run")
            if not run_data:
                return None
            return InfiniteRun(**run_data)
        except Exception as exc:
            logger.error("Error saving infinite hunt config: %s", exc)
            return None

    def update_infinite_run_state(
        self,
        *,
        status: Optional[str] = None,
        last_run_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Optional[InfiniteRun]:
        """
        Patch runtime metadata for the infinite hunt entry.

        Only fields that actually exist on the `infinite_runs` table are sent.
        """
        payload: Dict[str, Any] = {}
        if status is not None:
            payload["status"] = status
        if last_run_id is not None:
            payload["last_run_id"] = last_run_id
        if session_id is not None:
            payload["session_id"] = session_id

        if not payload:
            logger.warning("No fields provided for infinite run state update")
            return self.get_infinite_run()

        try:
            response = self._make_request(
                "PATCH",
                "/api/infinite-runs/state",
                json=payload,
            )

            if response.status_code != 200:
                logger.error("Failed to update infinite run state: %s", response.text)
                return None

            payload = response.json()
            run_data = payload.get("infinite_run")
            if not run_data:
                return None
            return InfiniteRun(**run_data)
        except Exception as exc:
            logger.error("Error updating infinite run state: %s", exc)
            return None

    def block_template(self, agent_run_template_id: str) -> Optional[InfiniteRun]:
        """
        Block a template due to verification requirement.

        This moves the template from selected_ordered_run_template_ids to
        bot_blocked_run_template_ids.

        Args:
            agent_run_template_id: The template ID to block
        """
        try:
            response = self._make_request(
                "POST",
                "/api/infinite-runs/block-template",
                json={"agent_run_template_id": agent_run_template_id},
            )

            if response.status_code != 200:
                logger.error(
                    "Failed to block template %s: %s",
                    agent_run_template_id,
                    response.text,
                )
                return None

            payload = response.json()
            run_data = payload.get("infinite_run")
            if not run_data:
                return None
            return InfiniteRun(**run_data)
        except Exception as exc:
            logger.error("Error blocking template %s: %s", agent_run_template_id, exc)
            return None

    def unblock_template(self, agent_run_template_id: str) -> Optional[InfiniteRun]:
        """
        Unblock a template after successful bot execution.

        This removes the template from bot_blocked_run_template_ids.

        Args:
            agent_run_template_id: The template ID to unblock
        """
        try:
            # Ensure UUID is converted to string for JSON serialization
            template_id_str = str(agent_run_template_id)
            response = self._make_request(
                "POST",
                "/api/infinite-runs/unblock-template",
                json={"agent_run_template_id": template_id_str},
            )

            if response.status_code != 200:
                logger.error(
                    "Failed to unblock template %s: %s",
                    agent_run_template_id,
                    response.text,
                )
                return None

            payload = response.json()
            run_data = payload.get("infinite_run")
            if not run_data:
                return None
            return InfiniteRun(**run_data)
        except Exception as exc:
            logger.error("Error unblocking template %s: %s", agent_run_template_id, exc)
            return None

    def set_infinite_run_status(
        self, action: str, message: Optional[str] = None
    ) -> Optional[InfiniteRun]:
        """
        Update infinite hunt status using convenience action endpoints.

        Args:
            action: One of start, pause, resume, stop
            message: Optional user-facing string
        """
        if action not in {"start", "pause", "resume", "stop"}:
            raise ValueError(f"Unsupported infinite run action: {action}")

        try:
            request_kwargs = (
                {"json": {"message": message}} if message is not None else {}
            )
            response = self._make_request(
                "POST",
                f"/api/infinite-runs/{action}",
                **request_kwargs,
            )

            if response.status_code != 200:
                logger.error("Failed to %s infinite run: %s", action, response.text)
                return None

            status_payload = response.json()
            current = self.get_infinite_run()
            if current:
                current.status = status_payload.get("status", current.status)
                current.active_agent_run_id = status_payload.get(
                    "active_agent_run_id", current.active_agent_run_id
                )
                current.last_run_id = status_payload.get(
                    "last_run_id", current.last_run_id
                )
                if "session_id" in status_payload:
                    session_val = status_payload.get("session_id")
                    current.session_id = UUID(session_val) if session_val else None
            return current
        except Exception as exc:
            logger.error("Error updating infinite run status: %s", exc)
            return None

    def update_workflow_run_status(
        self,
        run_id: str,
        status: str,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> bool:
        """
        Update workflow run status in the database.

        Args:
            run_id: Workflow run ID
            status: New status (pending/running/paused/completed/failed/cancelled)
            started_at: Optional timestamp when the run started
            completed_at: Optional timestamp when the run completed

        Returns:
            True if successful, False otherwise
        """
        try:
            payload: Dict[str, Any] = {"status": status}
            if started_at:
                payload["started_at"] = started_at
            if completed_at:
                payload["completed_at"] = completed_at

            response = self._make_request(
                "PUT",
                f"/api/workflow-runs/{run_id}",
                json=payload,
            )

            if response.status_code != 200:
                logger.error("Failed to update workflow run status: %s", response.text)
                return False

            logger.info(f"Updated workflow run {run_id} status to {status}")
            return True
        except Exception as exc:
            logger.error("Error updating workflow run status: %s", exc)
            return False

    def get_dynamic_config(self, key: str) -> Optional[int]:
        """
        Fetch a configuration value from the dynamic_config table.

        Args:
            key: The configuration key to fetch

        Returns:
            The integer value if found, None otherwise
        """
        try:
            response = self._make_request(
                "GET",
                f"/api/dynamic-config/{key}",
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("value")
            elif response.status_code == 404:
                logger.debug(f"Dynamic config key '{key}' not found")
                return None
            else:
                logger.warning(
                    f"Failed to get dynamic config '{key}': "
                    f"{response.status_code} - {response.text}"
                )
                return None
        except Exception as exc:
            logger.error(f"Error fetching dynamic config '{key}': {exc}")
            return None


# Global client instance
supabase_client = SupabaseClient()
