import logging
import re
from datetime import datetime, timedelta, timezone

from browser.automation import Page

logger = logging.getLogger(__name__)


class PositionInfoExtractor:
    """Extract job information from Dice job detail page"""

    def __init__(self, page: Page):
        """
        Initialize PositionInfoExtractor for Dice

        Args:
            page: Playwright page object
        """
        self.page = page

    def _get_title(self):
        """Return the primary job title locator and its parent containers."""
        if not self.page:
            return None, None, None

        title_locator = self.page.locator("h1")
        if title_locator.count() == 0:
            return None, None, None

        title_element = title_locator.first
        parent = title_element.locator("..")
        container = parent.locator("..")
        return title_element, parent, container

    def _parse_post_time(self, raw_value: str) -> str:
        """Convert Dice relative post-time to ISO format."""
        # Try to get post time from span#timeAgo first
        time_value = raw_value
        try:
            if self.page:
                time_ago_locator = (
                    self.page.locator("h1").locator("..").locator("span#timeAgo")
                )
                if time_ago_locator.count() > 0:
                    time_value = time_ago_locator.first.inner_text()
        except Exception as e:
            logger.debug(f"Could not get time from span#timeAgo: {e}")

        if not time_value:
            return ""

        # Handle 'Posted 2 days ago | Updated 2 days ago' format
        if "|" in time_value:
            time_value = time_value.split("|")[0].strip()

        cleaned = time_value.replace("•", "").strip()
        if not cleaned:
            return ""

        lowered = cleaned.lower()
        if lowered.startswith("posted"):
            lowered = lowered[len("posted") :].strip()
        if lowered.endswith("ago"):
            lowered = lowered[: -len("ago")].strip()
        lowered = lowered.replace("+", "").strip()

        now = datetime.now(timezone.utc)

        if lowered in ("", "just now", "moments ago", "moment ago"):
            return now.isoformat()

        if lowered.startswith("today"):
            return now.isoformat()

        if lowered.startswith("yesterday"):
            return (now - timedelta(days=1)).isoformat()

        match = re.search(r"(\d+)\s*(minute|hour|day|week|month|year)s?", lowered)
        if match:
            value = int(match.group(1))
            unit = match.group(2)
            if unit == "minute":
                delta = timedelta(minutes=value)
            elif unit == "hour":
                delta = timedelta(hours=value)
            elif unit == "day":
                delta = timedelta(days=value)
            elif unit == "week":
                delta = timedelta(weeks=value)
            elif unit == "month":
                delta = timedelta(days=value * 30)
            else:
                delta = timedelta(days=value * 365)
            return (now - delta).isoformat()

        return cleaned

    def _parse_salary_range(self, salary_text: str) -> list[int]:
        """Convert a salary string into a [min, max] range in annual salary.

        Examples:
            - 'USD 225,400.00 - 257,200.00 per year' -> [225400, 257200]
            - 'USD50 - USD70 per hour' -> [104000, 145600] (converted to annual)
            - '$50-70/hr+' -> [104000, 145600] (converted to annual)
        """
        if not salary_text:
            return []

        # Detect if it's hourly or annual
        salary_lower = salary_text.lower()
        is_hourly = any(
            indicator in salary_lower
            for indicator in ["per hour", "/hr", "/hour", "hr+", "hourly"]
        )
        is_annual = any(
            indicator in salary_lower
            for indicator in ["per year", "annually", "yearly", "/year"]
        )

        # Match numbers - handle formats like "USD50", "$50", "50", "50,000"
        # This pattern matches numbers that may be prefixed with currency codes or symbols
        matches = re.findall(
            r"(?:USD|usd|\$)?\s*([\d,]+(?:\.\d+)?)", salary_text, re.IGNORECASE
        )
        if not matches:
            return []

        # Remove commas and decimal parts, convert to int
        # Filter out empty strings that might be matched
        values = [
            int(m.replace(",", "").split(".")[0])
            for m in matches
            if m.strip() and m.replace(",", "").split(".")[0].isdigit()
        ]
        if not values:
            return []

        # Convert hourly to annual if needed (assuming 2080 hours/year)
        if is_hourly and not is_annual:
            values = [int(v * 2080) for v in values]

        if len(values) >= 2:
            return sorted(values[:2])  # Ensure min, max order
        return [values[0], values[0]]

    def get_job_title(self) -> str:
        """Extract job title from the page"""
        try:
            title_element, _, _ = self._get_title()
            if title_element is None:
                logger.warning("Job title element not found")
                return ""
            return title_element.inner_text().strip()
        except Exception as e:
            logger.error(f"Error extracting job title: {e}")
            return ""

    def get_company_name(self) -> str:
        """Extract company name from the page"""
        try:
            title_element, _, container = self._get_title()
            if container is None:
                logger.warning("Company name container not found")
                return ""

            company_locator = container.locator("a")
            if company_locator.count() == 0:
                logger.warning("Company name element not found")
                return ""

            return company_locator.first.inner_text().strip()
        except Exception as e:
            logger.error(f"Error extracting company name: {e}")
            return ""

    def get_location(self) -> str:
        """Extract location from the page"""
        try:
            # Try prioritized selector first
            location_locator = self.page.locator("li[data-cy*=location]")
            if location_locator.count() > 0:
                return location_locator.first.inner_text().strip()

            # Fallback to original method
            _, parent, _ = self._get_title()
            if parent is None:
                logger.warning("Location container not found")
                return ""

            spans = parent.locator("span")
            if spans.count() <= 1:
                logger.warning("Location element not found")
                return ""

            return spans.nth(1).inner_text().strip()
        except Exception as e:
            logger.error(f"Error extracting location: {e}")
            return ""

    def get_application_url(self) -> str:
        """
        Extract application URL from the page
        For Dice, we use the current page URL as the application URL
        """
        try:
            return self.page.url
        except Exception as e:
            logger.error(f"Error extracting application URL: {e}")
            return ""

    def get_job_description(self) -> str:
        """Extract full job description text"""
        try:
            details_header = self.page.locator("h2", has_text="Job Details")
            if details_header.count() == 0:
                logger.warning("Job Details heading not found")
                return ""

            details_container = details_header.first.locator("..")
            description_locator = details_container.locator(
                "div[class*=job-detail-description-module]"
            )

            if description_locator.count() == 0:
                # Try alternative selector for job description
                alternative_locator = (
                    self.page.locator("h2", has_text="Job Details")
                    .first.locator("..")
                    .locator("div#jobDescription")
                )

                if alternative_locator.count() > 0:
                    return alternative_locator.first.inner_text().strip()

                logger.warning("Job description container not found")
                return ""

            return description_locator.first.inner_text().strip()
        except Exception as e:
            logger.error(f"Error extracting job description: {e}")
            return ""

    def get_job_type(self) -> str:
        """Extract job type (On Site, Remote, Hybrid, etc.)"""
        try:
            # Try prioritized selector first
            job_type_locator = self.page.locator("span[id*=location]")
            if job_type_locator.count() > 0:
                return job_type_locator.first.inner_text().strip()

            # Fallback to original method
            _, _, container = self._get_title()
            if container is None:
                logger.warning("Job type container not found")
                return ""

            badge_locator = container.locator("div[class*=SeuiInfoBadge]")
            if badge_locator.count() == 0:
                logger.warning("Job type element not found")
                return ""

            return badge_locator.nth(0).inner_text().strip()
        except Exception as e:
            logger.error(f"Error extracting job type: {e}")
            return ""

    def get_salary_range(self) -> list[int]:
        """Extract salary range if available."""
        try:
            # Try prioritized selector first
            salary_locator = self.page.locator("span[id*=payChip]")
            if salary_locator.count() > 0:
                salary_text = salary_locator.first.inner_text().strip()
                return self._parse_salary_range(salary_text)

            # Fallback to original method
            _, _, container = self._get_title()
            if container is None:
                logger.warning("Salary container not found")
                return []

            badge_locator = container.locator("div[class*=SeuiInfoBadge]")
            badge_count = badge_locator.count()
            if badge_count == 0:
                logger.warning("Salary element not found")
                return []

            salary_text = badge_locator.nth(badge_count - 1).inner_text().strip()
            return self._parse_salary_range(salary_text)
        except Exception as e:
            logger.error(f"Error extracting salary range: {e}")
            return []

    def get_post_time(self) -> str:
        """Extract when the job was posted"""
        try:
            # Try to get post time from parent spans as fallback
            fallback_value = ""
            try:
                _, parent, _ = self._get_title()
                if parent is not None:
                    spans = parent.locator("span")
                    if spans.count() > 2:
                        fallback_value = spans.nth(2).inner_text()
            except Exception:
                pass

            # _parse_post_time will first try span#timeAgo, then use fallback
            return self._parse_post_time(fallback_value)
        except Exception as e:
            logger.error(f"Error extracting post time: {e}")
            return ""

    def extract_all_info(self) -> dict:
        """
        Extract all job information from the current page

        Returns:
            dict with job information
        """
        try:
            if not self.page:
                logger.warning("No page available for job info extraction")
                return {
                    "job_title": "",
                    "company_name": "",
                    "location": "",
                    "application_url": "",
                    "pos_context": "",
                    "job_type": "",
                    "salary_range": [],
                    "post_time": "",
                }

            job_info = {
                "job_title": self.get_job_title(),
                "company_name": self.get_company_name(),
                "location": self.get_location(),
                "application_url": self.get_application_url(),
                "pos_context": self.get_job_description(),
                "job_type": self.get_job_type(),
                "salary_range": self.get_salary_range(),
                "post_time": self.get_post_time(),
            }

            logger.info(
                f"Extracted job info: {job_info['job_title']} at "
                f"{job_info['company_name']}"
            )
            return job_info

        except Exception as e:
            logger.error(f"Error extracting all job info: {e}")
            application_url = ""
            try:
                application_url = self.page.url
            except Exception:
                application_url = ""
            return {
                "job_title": "",
                "company_name": "",
                "location": "",
                "application_url": application_url,
                "pos_context": "",
                "job_type": "",
                "salary_range": [],
                "post_time": "",
            }
