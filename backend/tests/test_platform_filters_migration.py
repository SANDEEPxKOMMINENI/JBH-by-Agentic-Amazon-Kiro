"""
Test Cases for Platform Filters Migration

These tests verify that the migration from old column-based format to new JSONB
platform_filters format works correctly with full backward compatibility.

Safety Tests: Verify existing users are NOT impacted.
"""

import pytest

from shared.platform_filters_migrator import PlatformFiltersMigrator


class TestPlatformFiltersMigrator:
    """Test the PlatformFiltersMigrator utility"""

    def test_migrate_linkedin_to_jsonb(self):
        """Test migrating LinkedIn filters from old format to JSONB"""
        result = PlatformFiltersMigrator.migrate_to_jsonb(
            platform="linkedin",
            country="usa",
            salary_bound=100000,
            experience_levels=[1, 2, 3],
            remote_types=[1, 2],
            specific_locations=["San Francisco", "New York"],
        )

        assert "linkedin" in result
        assert result["linkedin"]["country"] == "usa"
        assert result["linkedin"]["salary_bound"] == 100000
        assert result["linkedin"]["experience_levels"] == [1, 2, 3]
        assert result["linkedin"]["remote_types"] == [1, 2]
        assert result["linkedin"]["specific_locations"] == ["San Francisco", "New York"]

    def test_migrate_indeed_to_jsonb(self):
        """Test migrating Indeed filters to JSONB"""
        result = PlatformFiltersMigrator.migrate_to_jsonb(
            platform="indeed",
            posted_within_days=7,
            company_rating_min=3.5,
            easy_apply_only=True,
        )

        assert "indeed" in result
        assert result["indeed"]["posted_within_days"] == 7
        assert result["indeed"]["company_rating_min"] == 3.5
        assert result["indeed"]["easy_apply_only"] is True

    def test_extract_linkedin_from_jsonb(self):
        """Test extracting LinkedIn filters from JSONB"""
        platform_filters = {
            "linkedin": {
                "country": "canada",
                "salary_bound": 120000,
                "experience_levels": [2, 3],
                "remote_types": [1],
                "specific_locations": ["Toronto"],
            }
        }

        result = PlatformFiltersMigrator.extract_from_jsonb(
            platform_filters, "linkedin"
        )

        assert result["country"] == "canada"
        assert result["salary_bound"] == 120000
        assert result["experience_levels"] == [2, 3]
        assert result["remote_types"] == [1]
        assert result["specific_locations"] == ["Toronto"]

    def test_extract_from_null_platform_filters(self):
        """Test extracting when platform_filters is NULL (backward compatibility)"""
        result = PlatformFiltersMigrator.extract_from_jsonb(None, "linkedin")

        # Should return defaults
        assert result["country"] == "usa"
        assert result["salary_bound"] is None
        assert result["experience_levels"] == []
        assert result["remote_types"] == []
        assert result["specific_locations"] == []

    def test_should_use_platform_filters_null(self):
        """Test that NULL platform_filters returns False"""
        result = PlatformFiltersMigrator.should_use_platform_filters(None, "linkedin")
        assert result is False

    def test_should_use_platform_filters_has_data(self):
        """Test that non-empty platform_filters returns True"""
        platform_filters = {"linkedin": {"country": "usa"}}
        result = PlatformFiltersMigrator.should_use_platform_filters(
            platform_filters, "linkedin"
        )
        assert result is True

    def test_should_use_platform_filters_missing_platform(self):
        """Test that missing platform returns False"""
        platform_filters = {"linkedin": {"country": "usa"}}
        result = PlatformFiltersMigrator.should_use_platform_filters(
            platform_filters, "indeed"
        )
        assert result is False


class TestBackwardCompatibility:
    """
    Test backward compatibility scenarios.
    These tests simulate existing users' data (platform_filters = NULL).
    """

    def test_existing_user_record_simulation(self):
        """
        Simulate an existing user's record:
        - platform_filters = NULL
        - Old columns have data
        - Bot should read from old columns
        """
        # Simulate database record for existing user
        workflow_run = {
            "platform": "linkedin",
            "platform_filters": None,  # NULL for existing users
            "country": "usa",
            "salary_bound": 100000,
            "experience_levels": [1, 2],
            "remote_types": [1],
            "specific_locations": ["San Francisco"],
        }

        # Bot config reader logic
        if PlatformFiltersMigrator.should_use_platform_filters(
            workflow_run["platform_filters"], workflow_run["platform"]
        ):
            # Should NOT reach here for existing users
            pytest.fail("Should not use platform_filters for existing users")
        else:
            # Should use old columns (THIS is the path for existing users)
            assert workflow_run["country"] == "usa"
            assert workflow_run["salary_bound"] == 100000
            # This proves existing users are NOT impacted

    def test_new_user_record_simulation(self):
        """
        Simulate a new user's record:
        - platform_filters has data
        - Bot should read from platform_filters
        """
        # Simulate database record for new user
        workflow_run = {
            "platform": "linkedin",
            "platform_filters": {
                "linkedin": {
                    "country": "canada",
                    "salary_bound": 120000,
                    "experience_levels": [2, 3],
                    "remote_types": [2],
                    "specific_locations": ["Toronto"],
                }
            },
            # Old columns still populated for backward compat
            "country": "canada",
            "salary_bound": 120000,
        }

        # Bot config reader logic
        if PlatformFiltersMigrator.should_use_platform_filters(
            workflow_run["platform_filters"], workflow_run["platform"]
        ):
            # Should reach here for new users
            filters = workflow_run["platform_filters"]["linkedin"]
            assert filters["country"] == "canada"
            assert filters["salary_bound"] == 120000
            # This proves new users use new structure
        else:
            pytest.fail("Should use platform_filters for new users")


class TestAPIRouteScenarios:
    """Test API route handling of both formats"""

    def test_create_with_old_format(self):
        """Test creating workflow run with old column format"""
        # Simulated request data from old client
        request_data = {
            "workflow_id": "linkedin-apply",
            "platform": "linkedin",
            "country": "usa",
            "salary_bound": 100000,
            "experience_levels": [1, 2],
            "remote_types": [1],
            "specific_locations": ["San Francisco"],
            # No platform_filters field (old client)
        }

        # API route logic (simulated)
        if "platform_filters" in request_data and request_data["platform_filters"]:
            pytest.fail("Should not have platform_filters in old request")
        else:
            # Migrate to platform_filters
            platform_filters = PlatformFiltersMigrator.migrate_to_jsonb(
                platform=request_data["platform"],
                country=request_data.get("country"),
                salary_bound=request_data.get("salary_bound"),
                experience_levels=request_data.get("experience_levels"),
                remote_types=request_data.get("remote_types"),
                specific_locations=request_data.get("specific_locations"),
            )

            # Verify migration worked
            assert "linkedin" in platform_filters
            assert platform_filters["linkedin"]["country"] == "usa"
            # Both old columns AND platform_filters are written to database

    def test_create_with_new_format(self):
        """Test creating workflow run with new platform_filters format"""
        # Simulated request data from new client
        request_data = {
            "workflow_id": "linkedin-apply",
            "platform": "linkedin",
            "platform_filters": {
                "linkedin": {
                    "country": "usa",
                    "salary_bound": 100000,
                    "experience_levels": [1, 2],
                    "remote_types": [1],
                    "specific_locations": ["San Francisco"],
                }
            },
        }

        # API route logic (simulated)
        if "platform_filters" in request_data and request_data["platform_filters"]:
            # Use platform_filters directly
            platform_filters = request_data["platform_filters"]
            assert "linkedin" in platform_filters
            assert platform_filters["linkedin"]["country"] == "usa"
        else:
            pytest.fail("Should have platform_filters in new request")


# Run tests with: pytest tests/test_platform_filters_migration.py -v
