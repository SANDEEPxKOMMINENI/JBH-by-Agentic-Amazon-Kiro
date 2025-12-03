"""
Platform Filters Migration Utility

Handles bidirectional conversion between old column-based format and new JSONB format.
Used during the transition period to support both data structures.

Safety: This utility never modifies database records directly - it only transforms data.
"""

from typing import Any, Dict, List, Optional


class PlatformFiltersMigrator:
    """
    Handles migration between old column-based and new platform_filters JSONB format.

    Usage:
        # Convert old format to new JSONB format
        platform_filters = PlatformFiltersMigrator.migrate_to_jsonb(
            platform="linkedin",
            country="usa",
            salary_bound=100000,
            experience_levels=[1, 2],
            remote_types=[1],
            specific_locations=["San Francisco"]
        )

        # Extract old format from JSONB (for backward compatibility)
        old_format = PlatformFiltersMigrator.extract_from_jsonb(
            platform_filters={"linkedin": {"country": "usa", ...}},
            platform="linkedin"
        )
    """

    @staticmethod
    def migrate_to_jsonb(
        platform: str,
        country: Optional[str] = None,
        salary_bound: Optional[int] = None,
        experience_levels: Optional[List[int]] = None,
        remote_types: Optional[List[int]] = None,
        specific_locations: Optional[List[str]] = None,
        existing_platform_filters: Optional[Dict[str, Any]] = None,
        merge_mode: bool = False,  # NEW: If True, only update provided fields
        **kwargs,  # Accept additional platform-specific filters
    ) -> Dict[str, Any]:
        """
        Convert old column values to new platform_filters JSONB format.

        Args:
            platform: Platform name ('linkedin', 'indeed', etc.)
            country: Country code (LinkedIn)
            salary_bound: Minimum salary (LinkedIn)
            experience_levels: List of experience level codes (LinkedIn)
            remote_types: List of remote type codes (LinkedIn)
            specific_locations: List of location strings (LinkedIn)
            existing_platform_filters: Existing JSONB to merge with (preserves other platforms)
            merge_mode: If True, only update provided fields (preserves existing values)
            **kwargs: Additional platform-specific filters

        Returns:
            Complete platform_filters JSONB object

        Example:
            >>> migrate_to_jsonb(
            ...     platform="linkedin",
            ...     country="usa",
            ...     salary_bound=100000,
            ...     experience_levels=[1, 2]
            ... )
            {
                "linkedin": {
                    "country": "usa",
                    "salary_bound": 100000,
                    "experience_levels": [1, 2],
                    "remote_types": [],
                    "specific_locations": []
                }
            }
        """
        # Start with existing platform_filters or empty dict
        result = existing_platform_filters.copy() if existing_platform_filters else {}

        if platform == "linkedin":
            if merge_mode and platform in result:
                # Merge mode: preserve existing values, only update provided ones
                existing = result[platform]
                result["linkedin"] = {
                    "country": country
                    if country is not None
                    else existing.get("country", "usa"),
                    "salary_bound": salary_bound
                    if salary_bound is not None
                    else existing.get("salary_bound"),
                    "experience_levels": experience_levels
                    if experience_levels is not None
                    else existing.get("experience_levels", []),
                    "remote_types": remote_types
                    if remote_types is not None
                    else existing.get("remote_types", []),
                    "specific_locations": specific_locations
                    if specific_locations is not None
                    else existing.get("specific_locations", []),
                }
            else:
                # Replace mode: set all values (default behavior for CREATE)
                result["linkedin"] = {
                    "country": country or "usa",
                    "salary_bound": salary_bound,
                    "experience_levels": experience_levels or [],
                    "remote_types": remote_types or [],
                    "specific_locations": specific_locations or [],
                }
        elif platform == "indeed":
            # Indeed-specific filters (extend as needed)
            if merge_mode and platform in result:
                # Merge mode: preserve existing values
                existing = result[platform]
                indeed_filters = {
                    "posted_within_days": kwargs.get(
                        "posted_within_days", existing.get("posted_within_days")
                    ),
                    "company_rating_min": kwargs.get(
                        "company_rating_min", existing.get("company_rating_min")
                    ),
                    "easy_apply_only": kwargs.get(
                        "easy_apply_only", existing.get("easy_apply_only")
                    ),
                    "exclude_sponsored": kwargs.get(
                        "exclude_sponsored", existing.get("exclude_sponsored")
                    ),
                }
            else:
                # Replace mode
                indeed_filters = {
                    "posted_within_days": kwargs.get("posted_within_days"),
                    "company_rating_min": kwargs.get("company_rating_min"),
                    "easy_apply_only": kwargs.get("easy_apply_only"),
                    "exclude_sponsored": kwargs.get("exclude_sponsored"),
                }
            # Remove None values
            indeed_filters = {k: v for k, v in indeed_filters.items() if v is not None}
            result["indeed"] = indeed_filters
        elif platform == "glassdoor":
            # Glassdoor-specific filters (extend as needed)
            if merge_mode and platform in result:
                # Merge mode: preserve existing values
                existing = result[platform]
                glassdoor_filters = {
                    "company_rating_min": kwargs.get(
                        "company_rating_min", existing.get("company_rating_min")
                    ),
                    "easy_apply_only": kwargs.get(
                        "easy_apply_only", existing.get("easy_apply_only")
                    ),
                }
            else:
                # Replace mode
                glassdoor_filters = {
                    "company_rating_min": kwargs.get("company_rating_min"),
                    "easy_apply_only": kwargs.get("easy_apply_only"),
                }
            # Remove None values
            glassdoor_filters = {
                k: v for k, v in glassdoor_filters.items() if v is not None
            }
            result["glassdoor"] = glassdoor_filters
        else:
            # Generic platform - store kwargs as-is
            if merge_mode and platform in result:
                existing = result[platform]
                result[platform] = {
                    **existing,
                    **{k: v for k, v in kwargs.items() if v is not None},
                }
            else:
                result[platform] = {k: v for k, v in kwargs.items() if v is not None}

        return result

    @staticmethod
    def extract_from_jsonb(
        platform_filters: Optional[Dict[str, Any]], platform: str
    ) -> Dict[str, Any]:
        """
        Extract old-style column values from platform_filters JSONB.
        Used for backward compatibility when code expects old column names.

        Args:
            platform_filters: The JSONB platform_filters object
            platform: Platform to extract filters for

        Returns:
            Dict with old column names and values

        Example:
            >>> extract_from_jsonb(
            ...     platform_filters={"linkedin": {"country": "usa", "salary_bound": 100000}},
            ...     platform="linkedin"
            ... )
            {
                "country": "usa",
                "salary_bound": 100000,
                "experience_levels": [],
                "remote_types": [],
                "specific_locations": []
            }
        """
        # If no platform_filters or platform not in it, return defaults
        if not platform_filters or platform not in platform_filters:
            if platform == "linkedin":
                return {
                    "country": "usa",
                    "salary_bound": None,
                    "experience_levels": [],
                    "remote_types": [],
                    "specific_locations": [],
                }
            elif platform == "indeed":
                # Indeed has no legacy columns to extract to
                return {}
            elif platform == "glassdoor":
                # Glassdoor has no legacy columns to extract to
                return {}
            else:
                return {}

        filters = platform_filters[platform]

        if platform == "linkedin":
            return {
                "country": filters.get("country", "usa"),
                "salary_bound": filters.get("salary_bound"),
                "experience_levels": filters.get("experience_levels", []),
                "remote_types": filters.get("remote_types", []),
                "specific_locations": filters.get("specific_locations", []),
            }
        elif platform == "indeed":
            # Indeed-specific extraction (if needed for backward compat)
            return {
                "posted_within_days": filters.get("posted_within_days"),
                "company_rating_min": filters.get("company_rating_min"),
                "easy_apply_only": filters.get("easy_apply_only"),
                "exclude_sponsored": filters.get("exclude_sponsored"),
            }
        elif platform == "glassdoor":
            # Glassdoor-specific extraction
            return {
                "date_posted": filters.get("date_posted"),
                "company_rating_min": filters.get("company_rating_min"),
                "easy_apply_only": filters.get("easy_apply_only"),
            }
        else:
            # Generic platform - return as-is
            return filters

    @staticmethod
    def should_use_platform_filters(
        platform_filters: Optional[Dict[str, Any]], platform: str
    ) -> bool:
        """
        Determine if platform_filters should be used (vs old columns).

        Returns True if:
        - platform_filters exists (not None)
        - platform_filters has data for the specified platform

        Args:
            platform_filters: The JSONB platform_filters object
            platform: Platform to check

        Returns:
            True if should use platform_filters, False if should use old columns

        Example:
            >>> should_use_platform_filters(None, "linkedin")
            False  # NULL -> use old columns

            >>> should_use_platform_filters({"linkedin": {"country": "usa"}}, "linkedin")
            True  # Has data -> use platform_filters

            >>> should_use_platform_filters({"linkedin": {}}, "indeed")
            False  # Indeed not in dict -> use old columns
        """
        return (
            platform_filters is not None
            and isinstance(platform_filters, dict)
            and platform in platform_filters
            and bool(platform_filters[platform])  # Has actual data
        )
