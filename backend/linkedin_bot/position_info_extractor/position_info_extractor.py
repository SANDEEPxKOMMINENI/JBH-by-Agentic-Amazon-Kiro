import logging
import re

from browser.automation import Locator, Page
from services.ai_engine_client import AIEngineClient
from shared.models.application_history import ApplicationStatus
from util.application_history_id_generator import (
    generate_application_history_id,
    generate_job_description_id,
)
from util.time_util import get_current_timestamp

logger = logging.getLogger(__name__)


class PositionInfoExtractor:
    def __init__(self, page: Page):
        """
        Simplified PositionInfoExtractor for v2 - works with async Playwright

        Args:
            page: Async Playwright page object
        """
        self.page = page
        self.ai_client = AIEngineClient()

    def _timestamp_to_iso(self, timestamp) -> str:
        """Convert timestamp (float/int/string) to ISO string format"""
        if timestamp is None:
            return ""

        try:
            # Handle different timestamp formats
            if isinstance(timestamp, str):
                # Try to convert string to float first
                timestamp = float(timestamp)

            if isinstance(timestamp, (int, float)):
                from datetime import datetime, timezone  # noqa: E402

                return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()

            return str(timestamp)  # Fallback
        except (ValueError, TypeError):
            return str(timestamp) if timestamp else ""

    def get_linkedin_job_id(self) -> str:
        """Extract job ID from URL"""  # noqa: E402
        try:
            url = self.page.url
            if "currentJobId=" in url:
                return url.split("currentJobId=")[1].split("&")[0]
            elif "/view/" in url:
                return url.split("/view/")[-1].split("/")[0].split("?")[0]
            else:
                logger.warning(
                    f"Could not extract job ID from URL: {url}"
                )  # noqa: E402
                return ""
        except Exception as e:
            logger.error(f"Error extracting job ID: {e}")
            return ""

    def get_pos_title(self) -> str:
        """Extract job title from the page"""  # noqa: E402
        try:
            title_element = self.page.locator(
                "div.job-details-jobs-unified-top-card__job-title"
            ).locator("a")
            if title_element.count() > 0:
                return (title_element.inner_text()).strip()
            else:
                logger.warning("Job title element not found")
                return ""
        except Exception as e:
            logger.error(f"Error extracting job title: {e}")
            return ""

    def get_company_name(self) -> str:
        """Extract company name from the page"""  # noqa: E402
        try:
            company_element = self.page.locator(
                "div.job-details-jobs-unified-top-card__company-name"
            )
            if company_element.count() > 0:
                return (company_element.inner_text()).strip()
            else:
                logger.warning("Company name element not found")
                return ""
        except Exception as e:
            logger.error(f"Error extracting company name: {e}")
            return ""

    def get_location(self) -> str:
        """Extract and parse location from the page"""  # noqa: E402
        try:
            location_element = self.page.locator(
                "div.job-details-jobs-unified-top-card__primary-description-container"
            )
            if location_element.count() > 0:
                location_text = location_element.inner_text()
                location = location_text.strip().split("·")[0]

                if "," not in location:
                    # this is a country - use AI to parse location
                    try:
                        parsed_location = self._parse_location_with_ai(location)
                        city = parsed_location.get("city", "")
                        state = parsed_location.get("state", "")
                        if city and state:
                            return f"{city}, {state}"
                        else:
                            # Fallback to original location string if parsing fails
                            return location
                    except Exception as e:
                        logger.error(f"Error parsing location via AI: {e}")
                        # Fallback to original location string if parsing fails
                        return location

                city = location.split(",")[0].strip()
                state = location.split(",")[1].strip()
                return f"{city}, {state}"
            else:
                logger.warning("Location element not found")
                return ""
        except Exception as e:
            logger.error(f"Error extracting location: {e}")
            return ""

    # get number of applicants
    def get_num_applicants(self) -> int:
        """
        Extract number of applicants from the page  # noqa: E402
        There are only 2 cases:
        1. "xxx applicants" - return xxx
        2. "Over xxx applicants" - return 100
        """
        try:
            num_applicants_element = self.page.locator(
                "div.job-details-jobs-unified-top-card__primary-description-container"
            )
            if num_applicants_element.count() > 0:
                num_applicants_text = (num_applicants_element.inner_text()).strip()
                num_applicants_text = (
                    num_applicants_text.split("\n")[0].split("·")[-1].strip()
                )
                if "applicant" not in num_applicants_text:
                    return -1

                if num_applicants_text.lower().startswith("over"):
                    number = (
                        num_applicants_text.split(" ")[1]
                        if len(num_applicants_text.split(" ")) > 1
                        else 100
                    )
                    return int(number)
                else:
                    return int(num_applicants_text.split(" ")[0])
        except Exception as e:
            logger.error(f"Error extracting number of applicants: {e}")
            return -1

    def get_posted_ts(self) -> int:
        """Extract posted timestamp from the page"""  # noqa: E402
        try:
            location_element = self.page.locator(
                "div.job-details-jobs-unified-top-card__primary-description-container"
            )
            if location_element.count() > 0:
                location_text = location_element.inner_text()
                time_parts = location_text.strip().split("·")
                if len(time_parts) > 1:
                    posted_time_str = time_parts[1].strip()
                else:
                    logger.warning(
                        "Could not extract posted time from location text"
                    )  # noqa: E402
                    return (
                        get_current_timestamp() - 7 * 24 * 60 * 60
                    )  # Default to 1 week ago
            else:
                logger.warning("Location element not found for posted time")
                return get_current_timestamp() - 7 * 24 * 60 * 60
        except Exception as e:
            logger.error(f"Error extracting posted time: {e}")
            return get_current_timestamp() - 7 * 24 * 60 * 60

        # Parse the posted time string
        cur_ts = get_current_timestamp()
        if "month" in posted_time_str:
            # xxx N months/month ago
            words = posted_time_str.split(" ")
            month_index = next(i for i, word in enumerate(words) if "month" in word)
            month_num = int(words[month_index - 1].replace("month", ""))
            posted_ts = cur_ts - month_num * 30 * 24 * 60 * 60
        elif "week" in posted_time_str:
            # xxx N weeks/week ago
            words = posted_time_str.split(" ")
            week_index = next(i for i, word in enumerate(words) if "week" in word)
            week_num = int(words[week_index - 1].replace("week", ""))
            posted_ts = cur_ts - week_num * 7 * 24 * 60 * 60
        elif "day" in posted_time_str:
            # xxx N days/day ago
            words = posted_time_str.split(" ")
            # find index of word containing day
            day_index = next(i for i, word in enumerate(words) if "day" in word)
            # get the day number
            day_num = int(words[day_index - 1].replace("day", ""))
            # get the timestamp of day_num days ago
            posted_ts = cur_ts - day_num * 24 * 60 * 60
        elif "hour" in posted_time_str:
            words = posted_time_str.split(" ")
            # find index of word containing hour
            hour_index = next(i for i, word in enumerate(words) if "hour" in word)
            # get the hour number
            hour_num = int(words[hour_index - 1].replace("hour", ""))
            # get the timestamp of hour_num hours ago
            posted_ts = cur_ts - hour_num * 60 * 60
        elif "minute" in posted_time_str:
            words = posted_time_str.split(" ")
            # find index of word containing minute
            minute_index = next(i for i, word in enumerate(words) if "minute" in word)
            # get the minute number
            minute_num = int(words[minute_index - 1].replace("minute", ""))
            # get the timestamp of minute_num minutes ago
            posted_ts = cur_ts - minute_num * 60
        elif "second" in posted_time_str:
            words = posted_time_str.split(" ")
            # find index of word containing second
            second_index = next(i for i, word in enumerate(words) if "second" in word)
            # get the second number
            second_num = int(words[second_index - 1].replace("second", ""))
            # get the timestamp of second_num seconds ago
            posted_ts = cur_ts - second_num
        else:
            # by default, set it as 1 week ago
            logger.warning(f"Unknown posted time format: {posted_time_str}")
            posted_ts = cur_ts - 7 * 24 * 60 * 60
        return posted_ts

    def get_pos_link(self) -> str:
        """Get LinkedIn job link"""
        linkedin_job_id = self.get_linkedin_job_id()
        return f"https://www.linkedin.com/jobs/search/?currentJobId={linkedin_job_id}"

    def get_pos_context(self) -> str:
        """Extract job description from the page"""  # noqa: E402
        try:
            # Try primary selector first
            element = self.page.locator("div.jobs-description__content")
            if element.count() > 0:
                return (element.inner_text()).strip()

            # Fallback selector
            fallback_element = self.page.locator(".jobs-description")
            if fallback_element.count() > 0:
                return (fallback_element.first.inner_text()).strip()

            logger.warning("Job description element not found")
            return ""
        except Exception as e:
            logger.error(f"Error extracting job description: {e}")
            return ""

    def get_hiring_team(self) -> dict:
        """Extract hiring team information"""
        try:
            hiring_team_card = self.page.locator(
                ".job-details-people-who-can-help__section--two-pane:has-text('Meet the hiring team')"  # noqa: E501
            )
            if hiring_team_card.count() == 0:
                logger.info("No hiring team card found")
                return {}

            hiring_team_card = hiring_team_card.first
            name_element = hiring_team_card.locator("strong")
            if name_element.count() == 0:
                logger.info("No name found in hiring team card")
                return {}

            name = (name_element.first.inner_text()).strip()

            about_text_element = hiring_team_card.locator("div.linked-area").locator(
                "div.text-body-small"
            )
            about_text = ""
            if about_text_element.count() > 0:
                about_text = (about_text_element.first.inner_text()).strip()

            linkedin_url_element = hiring_team_card.locator("a")
            linkedin_url = ""
            if linkedin_url_element.count() > 0:
                linkedin_url = linkedin_url_element.first.get_attribute("href")

            return {
                "name": name,
                "about_text": about_text,
                "linkedin_url": linkedin_url,
            }
        except Exception as e:
            logger.error(f"Error extracting hiring team: {e}")
            return {}

    def get_job_type(self, job_card: Locator | None = None) -> str:
        """Extract job type (Full-time, Part-time, Contract, etc.)"""
        try:
            # LinkedIn shows job type in the criteria section
            job_type_element = self.page.locator(
                "li.job-details-jobs-unified-top-card__job-insight:has-text('Employment type')"
            )
            if job_type_element.count() > 0:
                job_type_text = job_type_element.first.inner_text()
                # Extract the actual job type from text like "Employment type\nFull-time"
                if "\n" in job_type_text:
                    return job_type_text.split("\n")[-1].strip()
                return job_type_text.replace("Employment type", "").strip()
            elif job_card:
                # Fallback: try to infer job type from the job card metadata
                try:
                    metadata_lists = job_card.locator(
                        "div[class*=artdeco-entity-lockup__caption]"
                    ).locator("ul[class*=job-card-container__metadata-wrapper]")

                    if metadata_lists.count() > 0:
                        metadata_text = metadata_lists.first.inner_text().strip()
                        # Example: "Los Angeles, CA (On-site)" → "On-site"
                        match = re.search(r"\(([^()]*)\)", metadata_text)
                        if match:
                            return match.group(1).strip()
                except Exception as inner_e:
                    logger.debug(f"Error extracting job type from job card: {inner_e}")

            logger.warning("Job type element not found")

            return ""
        except Exception as e:
            logger.error(f"Error extracting job type: {e}")
            return ""

    def get_salary_range(self, job_card: Locator | None = None) -> list[int]:
        """
        Extract salary range if available
        Format: '$145,000 - $175,000 a year' -> [145000, 175000]
        """
        try:
            # LinkedIn shows salary in the criteria section
            salary_element = self.page.locator(
                "li.job-details-jobs-unified-top-card__job-insight:has-text('$')"
            )
            if salary_element.count() > 0:
                salary_text = salary_element.first.inner_text()
                numbers = self._parse_salary_numbers(salary_text)
                if len(numbers) >= 2:
                    return numbers[:2]
                if len(numbers) == 1:
                    return [numbers[0], numbers[0]]

            # Fallback: try to parse salary from the job card metadata
            if job_card:
                try:
                    metadata_element = job_card.locator(
                        "div[class*=artdeco-entity-lockup__metadata]"
                    )
                    if metadata_element.count() > 0:
                        metadata_text = metadata_element.first.inner_text().strip()
                        numbers = self._parse_salary_numbers(metadata_text)
                        if len(numbers) >= 2:
                            return numbers[:2]
                        if len(numbers) == 1:
                            return [numbers[0], numbers[0]]
                except Exception as inner_e:
                    logger.debug(f"Error extracting salary from job card: {inner_e}")

            logger.warning("Salary element not found")
            return []
        except Exception as e:
            logger.error(f"Error extracting salary range: {e}")
            return []

    def _parse_salary_numbers(self, text: str) -> list[int]:
        """
        Parse monetary amounts from a salary string.

        Handles formats like:
        - '$145,000 - $175,000 a year'
        - '$160K/yr - $250K/yr'
        - '$140.8K/yr - $184K/yr · Vision, 401(k)'
        """
        numbers: list[int] = []
        try:
            # Match dollar amounts with optional K suffix
            # Group 1: numeric part (with commas/decimals)
            # Group 2: optional 'K' meaning thousands
            matches = re.findall(r"\$([\d.,]+)\s*([Kk])?", text)
            for amount_str, suffix in matches:
                # Normalize number string
                normalized = amount_str.replace(",", "")
                try:
                    value = float(normalized)
                except ValueError:
                    continue

                if suffix:
                    value *= 1000.0

                numbers.append(int(round(value)))
        except Exception as e:
            logger.debug(f"Error parsing salary numbers from text '{text}': {e}")

        return numbers

    def _parse_location_with_ai(self, location: str) -> dict:
        """
        Parse location string into city and state using AI

        This is PositionInfoExtractor-specific business logic for handling
        location data from LinkedIn job postings.  # noqa: E402

        Args:
            location: Location string to parse (e.g., "Germany", "United States")

        Returns:
            Dictionary with 'city' and 'state' keys
        """
        try:
            system_prompt = (
                "find city and state from the string, return as a json object"
                " (e.g. {'city': 'San Francisco', 'state': 'CA'}), if not found, "
                "return an empty json object"
            )

            format_spec = {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "state": {"type": "string"},
                },
                "required": ["city", "state"],
            }

            result = self.ai_client.call_ai(
                prompt=location,
                system=system_prompt,
                format=format_spec,
                model="gpt-4.1",
            )

            if result and isinstance(result, dict):
                return {
                    "city": result.get("city", ""),
                    "state": result.get("state", ""),
                }
            else:
                logger.warning(
                    f"Unexpected AI response format for location parsing: {result}"
                )
                return {"city": "", "state": ""}

        except Exception as e:
            logger.error(f"Error parsing location with AI: {e}")
            return {"city": "", "state": ""}

    def get_linkedin_job_id_v2(self) -> str:
        """Extract LinkedIn's original job ID from URL"""  # noqa: E402
        try:
            url = self.page.url
            if "currentJobId=" in url:
                return url.split("currentJobId=")[1].split("&")[0]
            elif "/view/" in url:
                return url.split("/view/")[-1].split("/")[0].split("?")[0]
            else:
                logger.warning(
                    f"Could not extract LinkedIn job ID from URL: {url}"
                )  # noqa: E402
                return ""
        except Exception as e:
            logger.error(f"Error extracting LinkedIn job ID: {e}")
            return ""

    def get_position_info(
        self, job_card: dict = None, workflow_run_id: str = None, user_id: str = None
    ) -> dict:
        """
        Extract comprehensive position information - v2 async version of v1's get_position_info  # noqa: E501

        Args:
            workflow_run_id: Optional workflow run ID to track which run collected this job  # noqa: E501
            user_id: User ID for generating user-specific application history ID

        Returns:
            dict: Complete position information matching v1's format
        """
        try:
            # Get basic job info
            application_url = self.get_pos_link()
            linkedin_job_id = self.get_linkedin_job_id()  # LinkedIn's original job ID
            company_name = self.get_company_name()
            job_title = self.get_pos_title()

            # Generate job description ID (shared across users)
            job_description_id = generate_job_description_id(
                application_url=application_url
            )

            # Generate application history ID (user-specific to prevent collisions)
            app_history_id = generate_application_history_id(
                application_url=application_url,
                user_id=user_id,
                linkedin_job_id=linkedin_job_id,
                company_name=company_name,
                job_title=job_title,
            )

            data = {
                "application_history_id": app_history_id,  # Application history ID
                "job_description_id": job_description_id,  # Job description ID (shared)
                "linkedin_job_id": linkedin_job_id,  # LinkedIn's original job ID
                "company_name": company_name,
                "job_title": job_title,
                "pos_context": self.get_pos_context(),
                "application_url": application_url,
                "post_time": self._timestamp_to_iso(self.get_posted_ts()),
                # Note: application_datetime is NOT set here - it should only be set
                # when the application is actually submitted, not when viewing the job
                "location": self.get_location(),
                "hiring_team": self.get_hiring_team(),
                "num_applicants": self.get_num_applicants(),  # Add number of applicants
                "job_type": self.get_job_type(job_card=job_card),
                "salary_range": self.get_salary_range(job_card=job_card),
                "status": ApplicationStatus.STARTED.value,
                # Initialize submission queue fields with defaults
                "ats_score": 0,
                "ats_alignments": [],
                "ats_keyword_to_add_to_resume": [],
                "optimized_ats_score": None,
                "optimized_ats_alignments": [],
                "criteria_alignment": [],
                # Workflow tracking
                "workflow_run_id": workflow_run_id,
            }

            logger.info(
                f"Extracted position info for job {app_history_id} (LinkedIn: {linkedin_job_id}): {data.get('company_name')} - {data.get('job_title')}"  # noqa: E501
            )
            return data

        except Exception as e:
            logger.error(f"Error extracting complete position info: {e}")
            return {}
