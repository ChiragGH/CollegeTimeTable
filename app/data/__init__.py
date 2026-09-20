"""
Data access layer for the College Timetable system.

Provides Excel I/O and master data validation.
"""

from app.data.loader import DataLoader
from app.data.validators import DataValidator, ValidationError, ValidationResult

__all__ = [
    "DataLoader",
    "DataValidator",
    "ValidationError",
    "ValidationResult",
]
