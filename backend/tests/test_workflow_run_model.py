"""
Unit Tests for WorkflowRun Model

Tests the WorkflowRun Pydantic model, focusing on:
- to_filter_config() method with platform_filters support
- Backward compatibility with NULL platform_filters
- Extraction methods for job_types and blacklist_companies
"""

from datetime import datetime
from uuid import uuid4

import pytest

from shared.models.workflow_run import WorkflowRun


class TestWorkflowRunFilterConfig:
    """Test the to_filter_config() method with platform_filters"""

    def test_to_filter_config_with_platform_filters(self):
        """Test that to_filter_config uses platform_filters when available"""
        workflow_run = WorkflowRun(
            id=uuid4(),
            user_id=uuid4(),
            workflow_id="linkedin-apply",
            platform="linkedin",
            status="pending",
            # NEW: platform_filters has data
            platform_filters={
                "linkedin": {
                    "country": "canada",
                    "salary_bound": 120000,
                    "experience_levels": [2, 3, 4],
                    "remote_types": [1, 2],
                    "specific_locations": ["Toronto", "Montreal"],
                }
            },
            # OLD: These should be ignored when platform_filters exists
            country="usa",
            salary_bound=100000,
            experience_levels=[1],
            remote_types=[3],
            specific_locations=["New York"],
            # Common fields
            job_types=["full-time"],
            blacklist_companies=["Company A"],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        result = workflow_run.to_filter_config()

        # Should use platform_filters values (NOT old columns)
        assert result["country"] == "canada"
        assert result["salary_bound"] == 120000
        assert result["experience_levels"] == [2, 3, 4]
        assert result["remote_types"] == [1, 2]
        assert result["specific_locations"] == ["Toronto", "Montreal"]

        # Common fields should still be included
        assert result["job_types"] == ["full-time"]
        assert result["blacklist_companies"] == ["Company A"]

    def test_to_filter_config_without_platform_filters(self):
        """Test backward compatibility: NULL platform_filters uses old columns"""
        workflow_run = WorkflowRun(
            id=uuid4(),
            user_id=uuid4(),
            workflow_id="linkedin-apply",
            platform="linkedin",
            status="pending",
            # NEW: platform_filters is NULL (existing users)
            platform_filters=None,
            # OLD: These should be used
            country="usa",
            salary_bound=100000,
            experience_levels=[1, 2],
            remote_types=[1],
            specific_locations=["San Francisco"],
            # Common fields
            job_types=["full-time"],
            blacklist_companies=["Company A"],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        result = workflow_run.to_filter_config()

        # Should use old columns (backward compatibility)
        assert result["country"] == "usa"
        assert result["salary_bound"] == 100000
        assert result["experience_levels"] == [1, 2]
        assert result["remote_types"] == [1]
        assert result["specific_locations"] == ["San Francisco"]
        assert result["job_types"] == ["full-time"]
        assert result["blacklist_companies"] == ["Company A"]

    def test_to_filter_config_with_empty_platform_filters(self):
        """Test that empty platform_filters dict falls back to old columns"""
        workflow_run = WorkflowRun(
            id=uuid4(),
            user_id=uuid4(),
            workflow_id="linkedin-apply",
            platform="linkedin",
            status="pending",
            # Empty platform_filters (no linkedin key)
            platform_filters={},
            # Should fall back to these
            country="usa",
            salary_bound=100000,
            experience_levels=[1],
            remote_types=[1],
            specific_locations=["Boston"],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        result = workflow_run.to_filter_config()

        # Should fall back to old columns
        assert result["country"] == "usa"
        assert result["salary_bound"] == 100000

    def test_to_filter_config_with_wrong_platform_in_filters(self):
        """Test fallback when platform_filters has different platform"""
        workflow_run = WorkflowRun(
            id=uuid4(),
            user_id=uuid4(),
            workflow_id="linkedin-apply",
            platform="linkedin",  # Current platform
            status="pending",
            # platform_filters only has 'indeed', not 'linkedin'
            platform_filters={"indeed": {"posted_within_days": 7}},
            # Should fall back to these
            country="usa",
            salary_bound=100000,
            experience_levels=[1],
            remote_types=[1],
            specific_locations=["Seattle"],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        result = workflow_run.to_filter_config()

        # Should fall back to old columns since 'linkedin' not in platform_filters
        assert result["country"] == "usa"
        assert result["salary_bound"] == 100000


class TestWorkflowRunExtractionMethods:
    """Test the extraction helper methods"""

    def test_extract_job_types_list(self):
        """Test extracting job_types when it's a plain list"""
        workflow_run = WorkflowRun(
            id=uuid4(),
            user_id=uuid4(),
            workflow_id="linkedin-apply",
            platform="linkedin",
            status="pending",
            job_types=["full-time", "contract"],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        result = workflow_run._extract_job_types()
        assert result == ["full-time", "contract"]

    def test_extract_job_types_dict_with_types_key(self):
        """Test extracting job_types when it's a dict with 'types' key"""
        workflow_run = WorkflowRun(
            id=uuid4(),
            user_id=uuid4(),
            workflow_id="linkedin-apply",
            platform="linkedin",
            status="pending",
            job_types={"types": ["full-time", "part-time"]},
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        result = workflow_run._extract_job_types()
        assert result == ["full-time", "part-time"]

    def test_extract_job_types_dict_with_values_key(self):
        """Test extracting job_types when it's a dict with 'values' key"""
        workflow_run = WorkflowRun(
            id=uuid4(),
            user_id=uuid4(),
            workflow_id="linkedin-apply",
            platform="linkedin",
            status="pending",
            job_types={"values": ["contract"]},
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        result = workflow_run._extract_job_types()
        assert result == ["contract"]

    def test_extract_job_types_none(self):
        """Test extracting job_types when it's None"""
        workflow_run = WorkflowRun(
            id=uuid4(),
            user_id=uuid4(),
            workflow_id="linkedin-apply",
            platform="linkedin",
            status="pending",
            job_types=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        result = workflow_run._extract_job_types()
        assert result == []

    def test_extract_blacklist_companies_list(self):
        """Test extracting blacklist_companies when it's a plain list"""
        workflow_run = WorkflowRun(
            id=uuid4(),
            user_id=uuid4(),
            workflow_id="linkedin-apply",
            platform="linkedin",
            status="pending",
            blacklist_companies=["Company A", "Company B"],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        result = workflow_run._extract_blacklist_companies()
        assert result == ["Company A", "Company B"]

    def test_extract_blacklist_companies_dict(self):
        """Test extracting blacklist_companies when it's a dict"""
        workflow_run = WorkflowRun(
            id=uuid4(),
            user_id=uuid4(),
            workflow_id="linkedin-apply",
            platform="linkedin",
            status="pending",
            blacklist_companies={"companies": ["Company C", "Company D"]},
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        result = workflow_run._extract_blacklist_companies()
        assert result == ["Company C", "Company D"]

    def test_extract_blacklist_companies_none(self):
        """Test extracting blacklist_companies when it's None"""
        workflow_run = WorkflowRun(
            id=uuid4(),
            user_id=uuid4(),
            workflow_id="linkedin-apply",
            platform="linkedin",
            status="pending",
            blacklist_companies=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        result = workflow_run._extract_blacklist_companies()
        assert result == []


class TestWorkflowRunDefaults:
    """Test default values and edge cases"""

    def test_default_country_when_not_provided(self):
        """Test that country defaults to 'usa'"""
        workflow_run = WorkflowRun(
            id=uuid4(),
            user_id=uuid4(),
            workflow_id="linkedin-apply",
            platform="linkedin",
            status="pending",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        result = workflow_run.to_filter_config()
        assert result["country"] == "usa"

    def test_empty_lists_when_not_provided(self):
        """Test that lists default to empty"""
        workflow_run = WorkflowRun(
            id=uuid4(),
            user_id=uuid4(),
            workflow_id="linkedin-apply",
            platform="linkedin",
            status="pending",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        result = workflow_run.to_filter_config()
        assert result["experience_levels"] == []
        assert result["remote_types"] == []
        assert result["specific_locations"] == []
        assert result["job_types"] == []
        assert result["blacklist_companies"] == []

    def test_semantic_instructions_default(self):
        """Test that semantic_instructions defaults to empty string"""
        workflow_run = WorkflowRun(
            id=uuid4(),
            user_id=uuid4(),
            workflow_id="linkedin-apply",
            platform="linkedin",
            status="pending",
            semantic_instructions=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        result = workflow_run.to_filter_config()
        assert result["semantic_instructions"] == ""


# Run with: pytest backend/tests/test_workflow_run_model.py -v
