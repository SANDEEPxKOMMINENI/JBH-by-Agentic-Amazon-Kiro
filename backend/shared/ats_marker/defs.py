from typing import Dict


class JobData:
    """
    This class is used to store the job data.
    """

    def __init__(self, job_title, job_description, company_name, post_time, location):
        self.job_title = job_title
        self.company_name = company_name
        self.job_description = job_description
        self.post_time = post_time
        self.location = location


class ApplicantData:
    """
    This class is used to store the applicant data.
    """

    def __init__(
        self,
        resume,
        additional_skills_and_experience: str = "",
        selected_ats_template_id: str = None,
    ):
        self.resume = resume
        self.additional_skills_and_experience = additional_skills_and_experience
        self.selected_ats_template_id = selected_ats_template_id


class Requirement:
    """
    This class is used to store the job requirements.
    """

    def __init__(self, description: str):
        self.description = description


class Alignment:
    """
    This class is used to store the alignment of the job requirements to the applicant's resume.  # noqa: E501
    """

    def __init__(
        self,
        requirement: Requirement,
        alignment_score: int,
        reason: str,
        max_score: int,
    ):
        self.requirement = requirement
        self.alignment_score = alignment_score
        self.reason = reason
        self.max_score = max_score

    def to_dict(self) -> Dict:
        """Convert the Alignment object to a dictionary."""
        return {
            "requirement": self.requirement.description,
            "alignment_score": self.alignment_score,
            "reason": self.reason,
            "max_score": self.max_score,
        }
