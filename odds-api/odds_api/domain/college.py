"""College school aliases and player identities backed by explicit school context."""

import json
import re
import unicodedata
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

COLLEGE_LEAGUES = {"ncaaf_football", "ncaab_basketball"}
COLLEGE_SPORTS = {"football_ncaaf", "basketball_ncaab"}


def name_key(value):
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]", "", text)


def alias_key(name):
    name = re.sub(r"^\s*(?:\(\d{1,2}\)|#\d{1,2})\s*", "", name.strip())
    return name_key(re.sub(r"\bSt\.?$", "State", name, flags=re.IGNORECASE))


DATA = json.loads(Path(__file__).with_name("college_schools.json").read_text(encoding="utf-8"))
_schools = defaultdict(set)
SCHOOL_LABELS = {}
for _school in DATA["schools"]:
    _key = alias_key(_school["name"])
    SCHOOL_LABELS[_key] = _school["name"]
    for _alias in (_school["name"], *_school["aliases"]):
        _schools[alias_key(_alias)].add(_key)
_ambiguous = {alias_key(value) for value in DATA["ambiguous_aliases"]}
SCHOOL_CANDIDATES = {alias: frozenset(keys) for alias, keys in _schools.items()}
SCHOOL_ALIASES = {
    alias: next(iter(keys)) for alias, keys in _schools.items() if len(keys) == 1 and alias not in _ambiguous
}


@lru_cache(maxsize=4096)
def school_key(name):
    key = alias_key(name)
    if key in _ambiguous or len(SCHOOL_CANDIDATES.get(key, ())) > 1:
        return "ambiguous:" + key
    return SCHOOL_ALIASES.get(key, key)


def school_label(name):
    return SCHOOL_LABELS.get(school_key(name), name)


@lru_cache(maxsize=16384)
def player_parts(description):
    """Strip a trailing school tag only when it is a recognized school alias."""
    match = re.fullmatch(r"(.+?)\s*\(([^()]+)\)\s*", description)
    if match and alias_key(match[2]) in SCHOOL_ALIASES:
        return match[1].strip(), school_key(match[2])
    return description.strip(), None


class CollegePlayers:
    """Resolve school + exact normalized full name within one confirmed fixture."""

    def __init__(self, home, away):
        self.schools = {school_key(home), school_key(away)}
        self.school_labels = {school_key(name): school_label(name) for name in (home, away)}
        self.affiliations = defaultdict(set)
        self.labels = {}
        self.players = defaultdict(set)

    def parts(self, description):
        name, school = player_parts(description)
        if school is None:
            match = re.fullmatch(r"(.+?)\s*\(([^()]+)\)\s*", description)
            if match:
                candidates = SCHOOL_CANDIDATES.get(alias_key(match[2]), frozenset())
                confirmed = candidates & self.schools
                if len(confirmed) == 1:
                    return match[1].strip(), next(iter(confirmed))
                if candidates:
                    return match[1].strip(), "<ambiguous>"
                if school_key(match[2]) in self.schools:
                    return match[1].strip(), school_key(match[2])
        return name, school

    def add(self, description, player_id=None, school=None):
        name, tagged_school = self.parts(description)
        school = school_key(school) if school else tagged_school
        if school not in self.schools:
            return
        key = name_key(name)
        self.affiliations[key].add(school)
        if player_id or (key, school) not in self.labels:
            self.labels[key, school] = name
        if player_id:
            self.players[key, school].add(player_id)

    def resolve(self, description):
        name, school = self.parts(description)
        key = name_key(name)
        if school and school not in self.schools:
            return None
        schools = {school} if school else self.affiliations.get(key, set())
        if len(schools) > 1:
            return None
        if not schools:
            return name, None, set()
        school = next(iter(schools))
        known = self.players.get((key, school), set())
        if len(known) > 1:
            return None
        display = self.labels.get((key, school), name)
        return f"{display} ({self.school_labels[school]})", school, known


def consolidate_rows(rows, events):
    """Apply the same affiliation to retained quotes without rewriting saved odds."""
    resolvers = {
        event_id: CollegePlayers(event["home"], event["away"])
        for event_id, event in events.items()
        if event["league_key"] in COLLEGE_LEAGUES
    }
    for row in rows:
        quote = row["quote"]
        resolver = resolvers.get(quote["event_id"])
        if resolver and quote["description"]:
            resolver.add(
                quote["description"],
                quote["player_id"] if row["book_key"].startswith("unabated_") else None,
            )
    result = []
    for row in rows:
        quote = row["quote"]
        resolver = resolvers.get(quote["event_id"])
        if resolver and quote["description"]:
            resolved = resolver.resolve(quote["description"])
            if resolved is None:
                continue
            row = {**row, "quote": {**quote, "description": resolved[0]}}
            if "outcome" in row:
                row["outcome"] = {**row["outcome"], "description": resolved[0]}
        result.append(row)
    return result
