"""
ATS Marker for V2 implementation - uses ATS template endpoints
"""

import logging
from typing import Callable, List, Optional, Tuple

import requests

from constants import SERVICE_GATEWAY_URL  # noqa: E402
from shared.ats_marker.defs import Alignment, ApplicantData, JobData, Requirement

logger = logging.getLogger(__name__)


class ATSMarker:
    """
    Check alignment of job to applicant's resume.
    Returns score between 0-100. Uses ATS template endpoints.
    """

    def __init__(
        self,
        job_data: JobData,
        applicant_data: ApplicantData,
        bot: any = None,
        model: str = "gpt-4.1",
        display_thinking_callback: Callable = None,
        alignment_score_threshold: float = 0.8,
        service_gateway_url: str = SERVICE_GATEWAY_URL,
        user_token: Optional[str] = None,
    ):
        self.job_data = job_data
        self.applicant_data = applicant_data
        self.bot = bot
        self.model = model
        self.alignment_score_threshold = alignment_score_threshold
        self.display_thinking_callback = display_thinking_callback
        self.service_gateway_url = service_gateway_url
        self.user_token = user_token

    def run(self) -> Tuple[int, List[Alignment], List[str]]:
        """Run the ATS analysis using ATS template endpoints"""
        try:
            # Call the ATS analyze endpoint
            score, alignments, keywords = self.analyze_ats_score()
            return score, alignments, keywords
        except Exception as e:
            logger.error(f"ATS analysis failed: {e}")
            return 0, [], []

    def analyze_ats_score(self) -> Tuple[int, List[Alignment], List[str]]:
        """Call the ATS analyze endpoint"""
        headers = {"Content-Type": "application/json"}
        if self.user_token:
            headers["Authorization"] = f"Bearer {self.user_token}"

        # Check if we should use ATS template's original resume text (pre-loaded)
        resume_text = self.applicant_data.resume

        payload = {
            "resume_text": resume_text,
            "job_title": self.job_data.job_title,
            "job_description": self.job_data.job_description,
            "company_name": self.job_data.company_name,
            "post_time": self.job_data.post_time,
            "location": self.job_data.location,
            "additional_skills": self.applicant_data.additional_skills_and_experience,
        }

        response = requests.post(
            f"{self.service_gateway_url}/api/ats/analyze-ats-score",
            json=payload,
            headers=headers,
            timeout=(30.0, 180.0),  # (connection_timeout, read_timeout)
        )

        if response.status_code != 200:
            logger.error(
                f"ATS analysis failed: {response.status_code} - " f"{response.text}"
            )
            raise Exception(f"ATS analysis failed: {response.status_code}")

        result = response.json()
        if not result.get("success"):
            msg = result.get("message", "Unknown error")
            logger.error(f"ATS analysis unsuccessful: {msg}")
            raise Exception(f"ATS analysis unsuccessful: {msg}")

        # Convert API response to our format
        score = result.get("ats_score", 0)
        alignments_data = result.get("alignments", [])
        keywords = result.get("keywords_to_add", [])

        # Convert alignments to our Alignment objects
        alignments = []
        for alignment_data in alignments_data:
            requirement = Requirement(description=alignment_data.get("requirement", ""))
            alignment = Alignment(
                requirement=requirement,
                alignment_score=alignment_data.get("alignment_score", 0),
                reason=alignment_data.get("reason", ""),
                max_score=10,  # Fixed max score for consistency
            )
            alignments.append(alignment)

        logger.info(
            f"ATS analysis completed: score={score}, "
            f"alignments={len(alignments)}, keywords={len(keywords)}"
        )
        return score, alignments, keywords

    def format_alignments(self, score: int, alignments: List[Alignment]) -> str:
        """
        Format the alignments as a markdown table.
        """
        msg = f"**ATS Score: {score}**\n\n"

        if not alignments:
            return msg + "No requirements analyzed."

        # Create markdown table
        msg += "| Requirement | Status |\n"
        msg += "|-------------|--------|\n"

        for alignment in alignments:
            # Keep full description for better context
            requirement_text = alignment.requirement.description.replace(
                "|", "\\|"
            )  # Escape pipes for markdown

            threshold = alignment.max_score * self.alignment_score_threshold
            alignment_status = (
                "Yes" if alignment.alignment_score >= threshold else "❌ No"
            )

            msg += f"| {requirement_text} | {alignment_status} |\n"

        return msg.strip()
