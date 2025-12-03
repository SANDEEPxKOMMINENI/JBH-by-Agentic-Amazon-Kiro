"""Test LinkedIn bot config parsing to ensure filters are preserved."""

import sys
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_path))

from infinite_hunt.config_models.linkedin import LinkedInBotConfig, LinkedInFilters


def test_linkedin_config_with_nested_platform_filters():
    """Test that LinkedInBotConfig correctly parses nested platform_filters structure."""

    # This is what comes from the service gateway
    config_from_service_gateway = {
        "platform": "linkedin",
        "search_keywords": "AI Project Lead",
        "linkedin_starter_url": None,
        "semantic_instructions": "Senior AI Project lead at Texas",
        "blacklist_companies": [],
        "auto_apply": True,
        "generate_cover_letter": False,
        "send_connection_request": True,
        "submit_confident_application": True,
        "daily_application_limit": 15,
        "skip_previously_skipped_jobs": True,
        "skip_staffing_companies": True,
        "platform_filters": {
            "linkedin": {
                "country": "usa",
                "experience_levels": [5, 6],
                "remote_types": [1, 2, 3],
                "specific_locations": ["houston, tx", "austin, tx", "dallas, tx"],
                "salary_bound": 120,
            }
        },
        "selected_resume_id": "fc096b6b-f801-4825-80aa-8cf31ff75c97",
        "selected_cover_letter_template_id": None,
        "selected_ats_template_id": "508a58b6-4fc9-4f46-8bbe-59559feec058",
        "use_ats_optimized": False,
    }

    # Parse with LinkedInBotConfig
    model = LinkedInBotConfig(**config_from_service_gateway)

    # Get the platform_filters
    platform_filters = model.platform_filters

    # Check if it's still a dict (nested structure)
    if isinstance(platform_filters, dict):
        linkedin_filters = platform_filters.get("linkedin", {})
    else:
        # It's a LinkedInFilters object
        linkedin_filters = platform_filters.model_dump()

    print(
        f"\nInput platform_filters: {config_from_service_gateway['platform_filters']}"
    )
    print(f"Output platform_filters: {platform_filters}")
    print(f"LinkedIn filters: {linkedin_filters}")

    # Assertions - these should all pass
    assert linkedin_filters["country"] == "usa", "Country should be preserved"
    assert linkedin_filters["experience_levels"] == [
        5,
        6,
    ], f"Experience levels should be [5, 6], got {linkedin_filters['experience_levels']}"
    assert linkedin_filters["remote_types"] == [
        1,
        2,
        3,
    ], f"Remote types should be [1, 2, 3], got {linkedin_filters['remote_types']}"
    assert linkedin_filters["specific_locations"] == [
        "houston, tx",
        "austin, tx",
        "dallas, tx",
    ], f"Locations should be preserved, got {linkedin_filters['specific_locations']}"
    assert (
        linkedin_filters["salary_bound"] == 120
    ), f"Salary should be 120, got {linkedin_filters['salary_bound']}"

    print("\n✅ All assertions passed!")


def test_linkedin_config_with_flat_platform_filters():
    """Test that LinkedInBotConfig also accepts flat platform_filters (backward compatibility)."""

    config_flat = {
        "search_keywords": "Software Engineer",
        "platform_filters": {
            "country": "usa",
            "experience_levels": [3, 4],
            "remote_types": [1],
            "specific_locations": ["san francisco, ca"],
            "salary_bound": 150,
        },
    }

    model = LinkedInBotConfig(**config_flat)

    # Should create a LinkedInFilters object
    if isinstance(model.platform_filters, dict):
        filters = model.platform_filters
    else:
        filters = model.platform_filters.model_dump()

    assert filters["country"] == "usa"
    assert filters["experience_levels"] == [3, 4]
    assert filters["remote_types"] == [1]
    assert filters["specific_locations"] == ["san francisco, ca"]
    assert filters["salary_bound"] == 150

    print("\n✅ Flat structure also works!")


if __name__ == "__main__":
    print("=" * 80)
    print("Testing LinkedIn Config Parsing")
    print("=" * 80)

    try:
        test_linkedin_config_with_nested_platform_filters()
    except AssertionError as e:
        print(f"\n❌ FAILED: {e}")
        print("\nThis confirms the bug - filters are being lost during parsing!")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")

    print("\n" + "=" * 80)

    try:
        test_linkedin_config_with_flat_platform_filters()
    except AssertionError as e:
        print(f"\n❌ FAILED: {e}")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
