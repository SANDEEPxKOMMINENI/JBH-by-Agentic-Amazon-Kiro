import logging
from typing import Optional

from browser.automation import Page

logger = logging.getLogger(__name__)


class PositionInfoExtractor:
    """Extract job information from Indeed job detail page"""

    def __init__(self, page: Page):
        """
        Initialize PositionInfoExtractor for Indeed

        Args:
            page: Playwright page object
        """
        self.page = page

    def get_job_title(self) -> str:
        """Extract job title from the page"""
        try:
            title_locator = self.page.locator(
                "h2[class*=jobsearch-JobInfoHeader-title]"
            )
            if title_locator.count() > 0:
                title = title_locator.inner_text().strip()
                # Handle Indeed "- job post" even if a newline precedes it
                if title.endswith("\n- job post"):
                    title = title[: -len("\n- job post")].strip()
                else:
                    suffixes_to_remove = [
                        " - job post",
                        "- job post",
                        " -job post",
                        "-job post",
                    ]
                    for suffix in suffixes_to_remove:
                        if title.endswith(suffix):
                            title = title[: -len(suffix)].strip()
                            break
                return title
            else:
                logger.warning("Job title element not found")
                return ""
        except Exception as e:
            logger.error(f"Error extracting job title: {e}")
            return ""

    def get_company_name(self) -> str:
        """Extract company name from the page"""
        try:
            company_locator = self.page.locator("div[data-company-name=true]")
            if company_locator.count() > 0:
                return company_locator.inner_text().strip()
            else:
                logger.warning("Company name element not found")
                return ""
        except Exception as e:
            logger.error(f"Error extracting company name: {e}")
            return ""

    def get_location(self) -> str:
        """Extract location from the page"""
        try:
            location_locator = self.page.locator(
                "div[data-testid*='inlineHeader-companyLocation']"
            )
            if location_locator.count() > 0:
                return location_locator.inner_text().strip()
            else:
                logger.warning("Location element not found")
                return ""
        except Exception as e:
            logger.error(f"Error extracting location: {e}")
            return ""

    def get_application_url(self) -> str:
        """
        Extract application URL from the page

        Two scenarios:
        1. Indeed Apply button exists -> use current page URL
        2. "Apply on company site" button -> extract href
        """
        try:
            # Check for Indeed Apply button
            indeed_apply_btn = self.page.locator("button#indeedApplyButton")
            if indeed_apply_btn.count() > 0:
                logger.info("Found Indeed Apply button, using current URL")
                return self.page.url

            # Check for "Apply on company site" button
            external_apply_btn = self.page.locator(
                "button[contenthtml*='Apply on company site'], " "a[href*='apply']"
            )
            if external_apply_btn.count() > 0:
                href = external_apply_btn.first.get_attribute("href")
                if href:
                    logger.info(f"Found external apply button with href: {href}")
                    return href
                else:
                    logger.warning("External apply button found but no href")
                    return self.page.url
            else:
                logger.warning("No apply button found, using current URL")
                return self.page.url

        except Exception as e:
            logger.error(f"Error extracting application URL: {e}")
            return self.page.url

    def get_job_description(self) -> str:
        """Extract full job description text"""
        try:
            # Indeed job description container
            desc_locator = self.page.locator("div#jobDescriptionText")
            if desc_locator.count() > 0:
                return desc_locator.inner_text().strip()
            else:
                logger.warning("Job description element not found")
                return ""
        except Exception as e:
            logger.error(f"Error extracting job description: {e}")
            return ""

    def get_job_type(self) -> str:
        """Extract job type (Full-time, Part-time, Contract, etc.)"""
        try:
            job_type_container = self.page.locator("div[aria-label*='Job type']")
            if job_type_container.count() > 0:
                job_type_item = job_type_container.locator("li").first
                if job_type_item.count() > 0:
                    return job_type_item.inner_text().strip()
            logger.warning("Job type element not found")
            return ""
        except Exception as e:
            logger.error(f"Error extracting job type: {e}")
            return ""

    def get_salary_range(self) -> list[int]:
        """
        Extract salary range if available
        Format: '$145,000 - $175,000 a year' -> '[145000, 175000]'
        """
        try:
            salary_container = self.page.locator("div[aria-label*=Pay]")
            if salary_container.count() > 0:
                salary_item = salary_container.locator("li").first
                if salary_item.count() > 0:
                    salary_text = salary_item.inner_text().strip()
                    # Parse salary range from text like '$145,000 - $175,000 a year'
                    import re

                    # Extract numbers from salary text
                    numbers = re.findall(r"\$?([\d,]+)", salary_text)
                    if len(numbers) >= 2:
                        # Remove commas and convert to integers
                        min_salary = int(numbers[0].replace(",", ""))
                        max_salary = int(numbers[1].replace(",", ""))
                        return [min_salary, max_salary]
                    elif len(numbers) == 1:
                        # Single salary value
                        salary = int(numbers[0].replace(",", ""))
                        return [salary, salary]
            logger.warning("Salary element not found")
            return []
        except Exception as e:
            logger.error(f"Error extracting salary range: {e}")
            return []

    def extract_all_info(self) -> dict:
        """
        Extract all job information from the current page

        Returns:
            dict with job information
        """
        try:
            job_info = {
                "job_title": self.get_job_title(),
                "company_name": self.get_company_name(),
                "location": self.get_location(),
                "application_url": self.get_application_url(),
                "pos_context": self.get_job_description(),
                "job_type": self.get_job_type(),
                "salary_range": self.get_salary_range(),
            }

            logger.info(
                f"Extracted job info: {job_info['job_title']} at "
                f"{job_info['company_name']}"
            )
            return job_info

        except Exception as e:
            logger.error(f"Error extracting all job info: {e}")
            return {
                "job_title": "",
                "company_name": "",
                "location": "",
                "application_url": "",
                "pos_context": "",
                "job_type": "",
                "salary_range": [],
            }
