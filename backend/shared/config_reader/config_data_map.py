"""
Configuration Data Mappings
Maps raw database values to human-readable strings
"""

from typing import Any, Dict


class ConfigMapper:
    """Maps database values to readable strings for display"""

    # Experience level mappings (LinkedIn standard levels)
    experience_level_map = {
        1: "Internship",
        2: "Entry Level",
        3: "Associate",
        4: "Mid-Senior Level",
        5: "Director",
        6: "Executive",
    }

    # Remote work preference mappings
    remote_type_map = {1: "Remote", 2: "Hybrid", 3: "On-site"}

    # Job type mappings (LinkedIn job type codes)
    job_type_map = {
        "F": "Full-time",
        "P": "Part-time",
        "C": "Contract",
        "T": "Temporary",
        "V": "Volunteer",
        "I": "Internship",
        "O": "Other",
    }

    @classmethod
    def get_experience_levels(cls, levels):
        """Convert experience level numbers to readable strings"""
        if not levels:
            return []
        if isinstance(levels, int):
            levels = [levels]
        return [
            cls.experience_level_map.get(level, f"Level {level}") for level in levels
        ]

    @classmethod
    def get_remote_types(cls, types):
        """Convert remote type numbers to readable strings"""
        if not types:
            return []
        if isinstance(types, int):
            types = [types]
        return [cls.remote_type_map.get(rtype, f"Type {rtype}") for rtype in types]

    @classmethod
    def get_job_types(cls, types):
        """Convert job type codes to readable strings"""
        if not types:
            return []
        if isinstance(types, str):
            types = [types]
        return [cls.job_type_map.get(jtype, jtype) for jtype in types]

    @classmethod
    def convert_all(cls, config_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Convert all config values to readable strings"""
        new_config_dict = {}
        for key, value in config_dict.items():
            if key == "experience_levels":
                new_config_dict["experience_levels"] = cls.get_experience_levels(value)
            elif key == "remote_types":
                new_config_dict["remote_types"] = cls.get_remote_types(value)
            elif key == "job_types":
                new_config_dict["job_types"] = cls.get_job_types(value)
            else:
                new_config_dict[key] = value
        return new_config_dict
