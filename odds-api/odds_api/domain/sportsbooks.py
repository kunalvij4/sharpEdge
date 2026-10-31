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
}


def sportsbook_key(key: str, title: str) -> str:
    """Normalize names from both feeds; keep unknown/unnamed books distinct."""
    name = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().casefold()
    name = re.sub(r"[^a-z0-9]", "", name)
    return ALIASES.get(name, name) if name else key
