import logging
from typing import Callable, Dict, List, Optional, Tuple

import requests

from constants import SERVICE_GATEWAY_URL  # noqa: E402
from services.jwt_token_manager import jwt_token_manager  # noqa: E402
from shared.interest_marker.defs import Interest, InterestAlignment, JobData

logger = logging.getLogger(__name__)

INTEREST_MARKER_ENDPOINT = f"{SERVICE_GATEWAY_URL}/api/interest-marker/analyze"


class InterestMarker:
    """
    This class is used to check the alignment between a user's interests and a job description.  # noqa: E501
    It will return a score between 0 and 100, where 100 indicates perfect alignment.
    """

    def __init__(
        self,
        job_data: JobData,
        original_job_search_criteria: str,
        model: str = "gpt-4.1",
        display_thinking_callback: Callable = None,
    ):
        self.job_data = job_data
        self.original_job_search_criteria = original_job_search_criteria
        self.model = model
        self.display_thinking_callback = display_thinking_callback
        self.max_alignment_score_per_interest = 10
        self.session = requests.Session()
        self.base_url = INTEREST_MARKER_ENDPOINT
        self.user_token: Optional[str] = None

    def run(self):
        interests, alignments, should_skip, reasoning = self._call_interest_marker_api()
        return alignments, should_skip, reasoning

    def _call_interest_marker_api(
        self,
    ) -> Tuple[List[str], List[InterestAlignment], bool, str]:
        headers = {"Content-Type": "application/json"}

        jwt_token_manager.refresh_token_if_needed()
        if not self.user_token:
            self.user_token = jwt_token_manager.get_token()
        else:
            # Refresh cached token in case it was rotated
            self.user_token = jwt_token_manager.get_token() or self.user_token

        if self.user_token:
            headers["Authorization"] = f"Bearer {self.user_token}"
        else:
            logger.warning("Interest marker request has no JWT token; call may fail.")

        payload = {
            "job_data": {
                "job_title": self.job_data.job_title,
                "job_description": self.job_data.job_description,
                "company_name": self.job_data.company_name,
                "post_time": self.job_data.post_time,
                "location": self.job_data.location,
            },
            "job_search_criteria": self.original_job_search_criteria,
            "model": self.model,
        }

        try:
            response = self.session.post(
                self.base_url,
                json=payload,
                headers=headers,
                timeout=(15, 90),
            )
            response.raise_for_status()
            data = response.json()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"Interest marker request failed: "
                f"{response.status_code} - {response.text}"
            ) from exc
        except requests.RequestException as exc:
            raise RuntimeError(f"Interest marker request error: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError("Interest marker returned invalid JSON") from exc

        interests_raw = data.get("interests", [])
        interests = [
            Interest(interest_description=item)
            for item in interests_raw
            if isinstance(item, str)
        ]

        alignments_payload = data.get("alignments", [])
        alignments: List[InterestAlignment] = []
        for item in alignments_payload:
            if not isinstance(item, dict):
                continue
            criteria = item.get("criteria")
            aligned = item.get("whether_aligned")
            if isinstance(criteria, str):
                alignments.append(
                    InterestAlignment(
                        criteria=criteria,
                        whether_aligned=bool(aligned),
                    )
                )

        should_skip = bool(data.get("should_skip", False))
        reasoning = data.get("reasoning", "")

        if self.display_thinking_callback and reasoning:
            self.display_thinking_callback(reasoning)

        logger.info(
            "interest alignments: %s, should_skip: %s, reasoning: %s",
            alignments_payload,
            should_skip,
            reasoning,
        )

        return (
            interests,
            alignments,
            should_skip,
            reasoning,
        )

    def format_alignments(self, alignments: List[InterestAlignment]):
        """
        Format the alignments to a string.
        """
        msg = ""
        alignment_table_data = []
        for alignment in alignments:
            alignment_table_data.append(
                {
                    "criteria": alignment.criteria,
                    "alignment": "Yes" if alignment.whether_aligned else "❌ No",
                }
            )
        # Simple table formatting for V2 (no format_table_msg dependency)
        for item in alignment_table_data:
            msg += f"{item['criteria']}: {item['alignment']}\n"
        return msg.strip()
