#!/usr/bin/env python3
"""
Position Info Extractor for ZipRecruiter

TODO: Manually implement ZipRecruiter-specific CSS selectors by:
1. Opening ZipRecruiter in a browser
2. Inspecting the HTML structure using DevTools
3. Finding selectors for job cards, titles, companies, locations, etc.
4. Updating the selectors in this file
"""

import logging
from typing import Optional

from browser.automation import Page

logger = logging.getLogger(__name__)


class PositionInfoExtractor:
    """Extract job information from ZipRecruiter job detail page"""

    def __init__(self, page: Page):
        """
        Initialize PositionInfoExtractor for ZipRecruiter

        Args:
            page: Playwright page object
        """
        self.page = page

    def get_job_title(self) -> str:
        """
        Extract job title from the page

        TODO: Update selector for ZipRecruiter job title element
        Example: title_locator = self.page.locator("h1[class*='job-title']")
        """
        try:
            # TODO: Update selector
            title_locator = self.page.locator("h1")  # Placeholder
            if title_locator.count() > 0:
                title = title_locator.first.inner_text().strip()
                return title
            else:
                logger.warning("Job title element not found")
                return ""
        except Exception as e:
            logger.error(f"Error extracting job title: {e}")
            return ""

    def get_company_name(self) -> str:
        """
        Extract company name from the page

        TODO: Update selector for ZipRecruiter company name element
        """
        try:
            # TODO: Update selector
            company_locator = self.page.locator("a[class*='company']")  # Placeholder
            if company_locator.count() > 0:
                return company_locator.first.inner_text().strip()
            else:
                logger.warning("Company name element not found")
                return ""
        except Exception as e:
            logger.error(f"Error extracting company name: {e}")
            return ""

    def get_location(self) -> str:
        """
        Extract location from the page

        TODO: Update selector for ZipRecruiter location element
        """
        try:
            # TODO: Update selector
            location_locator = self.page.locator(
                "div[class*='location']"
            )  # Placeholder
            if location_locator.count() > 0:
                return location_locator.first.inner_text().strip()
            else:
                logger.warning("Location element not found")
                return ""
        except Exception as e:
            logger.error(f"Error extracting location: {e}")
            return ""

    def get_application_url(self) -> str:
        """
        Extract application URL from the page

        TODO: Update logic for ZipRecruiter application URL extraction
        """
        try:
            # For now, return current page URL
            url = self.page.url if self.page.url else ""
            if not url:
                logger.warning("Page URL is empty, cannot extract application URL")
            return url
        except Exception as e:
            logger.error(f"Error extracting application URL: {e}")
            return ""

    def get_job_description(self) -> str:
        """
        Extract full job description text

        TODO: Update selector for ZipRecruiter job description container
        """
        try:
            # TODO: Update selector
            desc_locator = self.page.locator(
                "div[class*='job-description']"
            )  # Placeholder
            if desc_locator.count() > 0:
                return desc_locator.first.inner_text().strip()
            else:
                logger.warning("Job description element not found")
                return ""
        except Exception as e:
            logger.error(f"Error extracting job description: {e}")
            return ""

    def get_job_type(self) -> str:
        """
        Extract job type (Full-time, Part-time, Contract, etc.)

        TODO: Update selector for ZipRecruiter job type element
        """
        try:
            # TODO: Update selector
            job_type_locator = self.page.locator(
                "span[class*='job-type']"
            )  # Placeholder
            if job_type_locator.count() > 0:
                return job_type_locator.first.inner_text().strip()
            logger.warning("Job type element not found")
            return ""
        except Exception as e:
            logger.error(f"Error extracting job type: {e}")
            return ""

    def get_salary_range(self) -> list[int]:
        """
        Extract salary range if available
        Format: '$145,000 - $175,000 a year' -> [145000, 175000]

        TODO: Update selector for ZipRecruiter salary element
        """
        try:
            # TODO: Update selector for ZipRecruiter
            salary_locator = self.page.locator("span[class*='salary']")  # Placeholder
            if salary_locator.count() > 0:
                salary_text = salary_locator.first.inner_text().strip()
                # Parse salary range from text
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

    def get_post_time(self) -> str:
        """
        Extract when the job was posted

        TODO: Update selector for ZipRecruiter post time element
        """
        try:
            # TODO: Update selector
            post_time_locator = self.page.locator(
                "span[class*='posted']"
            )  # Placeholder
            if post_time_locator.count() > 0:
                return post_time_locator.first.inner_text().strip()
            return ""
        except Exception as e:
            logger.error(f"Error extracting post time: {e}")
            return ""

    def extract_all_info(self) -> dict:
        """
        Extract all job information at once

        Returns dict with all job fields
        """
        return {
            "job_title": self.get_job_title(),
            "company_name": self.get_company_name(),
            "location": self.get_location(),
            "application_url": self.get_application_url(),
            "pos_context": self.get_job_description(),
            "job_type": self.get_job_type(),
            "salary_range": self.get_salary_range(),
            "post_time": self.get_post_time(),
        }
