"""Public sportsbook names are independent of provider-owned storage identities."""

import re
import unicodedata

ALIASES = {
    "draftkingssportsbook": "draftkings",
    "fanduelsportsbook": "fanduel",
    "betmgmsportsbook": "betmgm",
    "caesarssportsbook": "caesars",
    "hardrocksportsbook": "hardrockbet",
    "betriverssportsbook": "betrivers",
    "prophetx": "prophetxchange",
    "prophetexchange": "prophetxchange",
    "underdogfantasy": "underdog",
    "underdogpickem": "underdog",
    "dkpick6": "draftkingspick6",
    "pick6": "draftkingspick6",
}

TITLES = {
    "prophetxchange": "ProphetXchange",
    "prizepicks": "PrizePicks",
    "underdog": "Underdog",
    "sportzino": "Sportzino",
    "draftkingspick6": "DraftKings Pick6",
}


def sportsbook_key(key: str, title: str) -> str:
    """Normalize names from both feeds; keep unknown/unnamed books distinct."""
    name = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().casefold()
    name = re.sub(r"[^a-z0-9]", "", name)
    return ALIASES.get(name, name) if name else key


def sportsbook_title(public_key: str, source_title: str) -> str:
    """Use a stable public title for books with different feed names."""
    return TITLES.get(public_key, source_title)
