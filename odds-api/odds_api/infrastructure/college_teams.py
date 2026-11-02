"""Explicit school aliases seen in the college provider feeds."""

import re

from odds_api.infrastructure.bet365 import normalized

COLLEGE_SPORTS = {"basketball_ncaab", "football_ncaaf"}
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
ALIASES = {
    normalized(alias): normalized(school)
    for school, aliases in SCHOOL_NAMES.items()
    for alias in (school, *aliases)
}


def school_key(name):
    # Rankings change during the season and are presentation metadata.
    name = re.sub(r"^\s*\(\d{1,2}\)\s*", "", name)
    name = re.sub(r"\bSt\.?$", "State", name, flags=re.IGNORECASE)
    key = normalized(name)
    return ALIASES.get(key, key)
