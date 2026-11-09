"""Publish links already returned with odds; never request link generation."""

import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class BetLinkEnricher:
    def __init__(self, partner_code="sharpedge"):
        self.partner_code = partner_code or "sharpedge"

    @classmethod
    def from_env(cls):
        return cls(os.environ.get("UNABATED_PARTNER_CODE", "sharpedge"))

    def prepare(self, link):
        if not isinstance(link, dict):
            return "unavailable"
        app = link.pop("app_url", None)
        if isinstance(app, str):
            try:
                parsed_app = urlsplit(app)
                if (not parsed_app.username and not parsed_app.password
                        and ((parsed_app.scheme == "https" and parsed_app.hostname)
                             or (link.get("provider") == "propline"
                                 and parsed_app.scheme in {"courtside", "prophetx"}
                                 and (parsed_app.netloc or parsed_app.path)))):
                    link["app_url"] = app
            except ValueError:
                pass
        value = link.pop("url", None)
        if isinstance(value, str):
            try:
                parsed = urlsplit(value)
                valid = (parsed.scheme == "https" and parsed.hostname
                         and not parsed.username and not parsed.password)
            except ValueError:
                valid = False
            if valid:
                if (link.get("provider") == "unabated"
                        and parsed.hostname in {"gambly.com", "www.gambly.com"}
                        and parsed.path.startswith("/deeplink/odds/")):
                    query = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
                             if key != "utm_campaign"]
                    query.append(("utm_campaign", self.partner_code))
                    value = urlunsplit(parsed._replace(query=urlencode(query)))
                link["url"] = value
                link["status"] = "event_support" if link.get("provider") == "propline" else "provided"
                return "event" if link["status"] == "event_support" else "provided"
        if link.get("app_url"):
            link["status"] = "event_support"
            return "event"
        link["status"] = "unavailable"
        return "unavailable"

    def enrich(self, ev):
        stats = {"provided": 0, "event": 0, "unavailable": 0}
        for bets in ev.values():
            for row in bets:
                stats[self.prepare(row.get("bet_link"))] += 1
        return stats

    def attach_related(self, ev, arbitrage):
        for bets in ev.values():
            for row in bets:
                for field in ("other_books", "away_other_books", "over_other_books", "under_other_books"):
                    for quote in row.get(field, []):
                        self.prepare(quote.get("bet_link"))
        for bets in arbitrage.values():
            for row in bets:
                for side in (1, 2):
                    self.prepare(row.get(f"bet_link{side}"))
