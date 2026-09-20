"""
Branch domain model.

Represents an academic branch / department in the college.
Encapsulates branch identity, display name, and canonical abbreviations.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class Branch:
    """
    Branch or department entity.

    Attributes:
        branch_id:   Canonical branch code, e.g. ``CSE``, ``Civil``.
        branch_name: Full display name, e.g. ``Computer Science Engineering``.
        short_name:  Optional short abbreviation or alias, e.g. ``CE`` for Civil.
    """
    branch_id: str
    branch_name: str
    short_name: Optional[str] = None


# Authoritative canonical branches for academic timetable scheduling.
CANONICAL_BRANCHES: List[Branch] = [
    Branch(branch_id="CSE", branch_name="Computer Science & Engineering", short_name="CSE"),
    Branch(branch_id="ECE", branch_name="Electronics & Communication Engineering", short_name="ECE"),
    Branch(branch_id="EE", branch_name="Electrical Engineering", short_name="EE"),
    Branch(branch_id="ME", branch_name="Mechanical Engineering", short_name="ME"),
    Branch(branch_id="Civil", branch_name="Civil Engineering", short_name="CE"),
]

# Canonical branch lookup by ID or alias (case-insensitive)
_BRANCH_NORMALIZE_MAP: Dict[str, str] = {
    "CSE": "CSE",
    "ECE": "ECE",
    "EE": "EE",
    "ME": "ME",
    "CIVIL": "Civil",
    "CE": "Civil",
    "APPLIED SCIENCE": "Applied Science",
    "APPLIED_SCIENCE": "Applied Science",
    "AS": "Applied Science",
    "WORKSHOP": "Workshop",
    "WS": "Workshop",
}


def normalize_branch(branch: Optional[str]) -> str:
    """
    Normalize a branch identifier or alias to its canonical representation.

    Maps common aliases like ``CE`` -> ``Civil`` and handles case differences.
    Returns the stripped original string if unmapped.
    """
    if not branch:
        return ""
    cleaned = branch.strip()
    return _BRANCH_NORMALIZE_MAP.get(cleaned.upper(), cleaned)
