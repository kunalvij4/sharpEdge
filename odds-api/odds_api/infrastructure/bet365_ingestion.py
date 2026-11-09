"""Bounded, source-verified HTTP snapshots from the user's local collector."""

from datetime import datetime
from time import perf_counter
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from odds_api.infrastructure.bet365 import MARKETS, boards
from scripts.organize_bet365_league_dump import organize_leagues
from scripts.verify_bet365_dump import verify

MAX_CAPTURE_BYTES = 8 * 1024 * 1024


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = Field(min_length=1, max_length=12)
    fields: dict[str, str] = Field(max_length=100)

    @field_validator("fields")
    @classmethod
    def bounded_fields(cls, values):
        if any(len(k) > 32 or len(v) > 16384 for k, v in values.items()):
            raise ValueError("Oversized protocol field")
        return values


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: str = Field(max_length=150)
    received_at: AwareDatetime
    source_url: str = Field(max_length=1000)
    records: list[Record] = Field(min_length=1, max_length=60000)


class Capture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    region: Literal["nj", "va"]
    league: str = Field(max_length=40)
    messages: list[Message] = Field(min_length=1, max_length=150)


def ingest_capture(capture: Capture, repository, settings, now: datetime):
    started = perf_counter()
    if capture.league not in settings.collection_leagues:
        raise ValueError("League is not enabled for collection")
    messages = capture.model_dump(mode="json")["messages"]
    for message in capture.messages:
        url = urlsplit(message.source_url)
        if (
            url.scheme != "https"
            or url.hostname != f"www.{capture.region}.bet365.com"
            or url.username
            or url.password
            or url.query
            or url.fragment
            or (message.received_at - now).total_seconds() > 5
        ):
            raise ValueError("Invalid source or capture timestamp")
    report = organize_leagues(messages, region=capture.region)
    verification = verify(report, messages)
    if not verification["source_checks_passed"] or report["normalization_issues"]:
        raise ValueError("Bet365 source validation failed")
    report["leagues"] = [league for league in report["leagues"] if league["key"] == capture.league]
    normalized = perf_counter()
    output, counts = boards(
        report,
        repository,
        now,
        max_age=settings.bet365_max_age,
        support_age=max(settings.collected_ttl, settings.props_cache_ttl),
        coverage={
            league["key"]: ("h2h", "spreads", "totals", *MARKETS.get(league["title"], {}).values())
            for league in report["leagues"]
        },
    )
    matched = perf_counter()
    counts["offered_prop_selections"] = sum(
        len(prop["selections"])
        for league in report["leagues"]
        for event in league["events"]
        for prop in event["player_props"]
        if (
            prop["source_label"] in MARKETS.get(league["title"], {})
            and prop.get("offering_context") in {"league_player_props", "event_player_props"}
            and prop.get("both_sides_present")
        )
        or prop.get("offering_context") == "event_player_milestone"
    )
    if hasattr(repository, "save_bet365"):
        repository.save_bet365([board for board in output if board.quotes])
    else:
        for board in output:
            if board.quotes:
                repository.save(board)
    accepted = sum(len(board.quotes) for board in output)
    result = {
        "accepted_selections": accepted,
        "counts": counts,
        "timings": {
            "normalize_seconds": round(normalized - started, 3),
            "match_seconds": round(matched - normalized, 3),
            "write_seconds": round(perf_counter() - matched, 3),
        },
    }
    if hasattr(repository, "record_bet365_ingestion"):
        repository.record_bet365_ingestion(
            capture.league,
            {
                "state": "success" if accepted else "no_matching_prices",
                "last_received": now.isoformat(),
                "captured_at": max(message.received_at for message in capture.messages).isoformat(),
                **result,
            },
        )
    return result
