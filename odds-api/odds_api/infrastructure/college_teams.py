"""Explicit school aliases seen in the college provider feeds."""

from odds_api.domain.college import COLLEGE_SPORTS, SCHOOL_ALIASES, school_key

__all__ = ["COLLEGE_SPORTS", "school_key"]

# Keep complete school identities: a prefix match would confuse Michigan with
# Michigan State, and Miami's Florida and Ohio campuses must remain distinct.
SCHOOL_NAMES = {
    "Miami Florida": ("Miami FL", "Miami (FL)", "Miami Hurricanes"),
    "Miami Ohio": ("Miami OH", "Miami (OH)", "Miami RedHawks"),
    "Massachusetts": ("UMass", "UMass Minutemen"),
    "Mississippi": ("Ole Miss", "Ole Miss Rebels"),
    "Duke": ("Duke Blue Devils",),
    "Army": ("Army Black Knights",),
    "Illinois": ("Illinois Fighting Illini",),
    "Fairleigh Dickinson": ("Fairleigh Dickinson Knights", "FDU Knights", "FDU"),
}
ALIASES = SCHOOL_ALIASES
