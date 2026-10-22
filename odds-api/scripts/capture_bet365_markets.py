"""Capture public Bet365 market protocol records with headed Playwright.

Research output only; no API database writes, login, or bet placement.
"""

import argparse
import asyncio
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from scripts.probe_bet365 import safe_text, safe_url


def records(payload):
    result = []
    for part in payload.split("|"):
        match = re.search(r"(?:^|[\x00-\x1f])([A-Z]{2});(.*)", part)
        if not match:
            continue
        kind, rest = match.groups()
        fields = {}
        for item in rest.split(";"):
            if "=" in item:
                key, value = item.split("=", 1)
                if not re.search(r"token|session|cookie|password|authorization", key, re.I):
                    fields[key] = value
        if fields:
            result.append({"type": kind, "fields": fields})
    return result


async def capture(args):
    from playwright.async_api import Error, async_playwright

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    messages = []
    pending = set()
    stage = "home"
    pages = []
    network = []
    page_errors = []
    prop_views = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chromium", headless=False)
        context = await browser.new_context(viewport={"width": 1440, "height": 1000})
        page = await context.new_page()

        async def received(response, captured_stage):
            if response.status != 200 or response.request.resource_type not in {"xhr", "fetch"}:
                return
            if not (response.url.startswith(f"https://www.{args.region}.bet365.com/")):
                return
            try:
                body = await asyncio.wait_for(response.body(), 8)
            except (Error, TimeoutError):
                return
            if len(body) > 3_000_000:
                return
            parsed = records(body.decode("utf-8", errors="replace"))
            if any(row["type"] in {"MA", "PA"} for row in parsed):
                messages.append(
                    {
                        "stage": captured_stage,
                        "received_at": datetime.now(UTC).isoformat(),
                        "source_url": safe_url(response.url),
                        "records": parsed,
                    }
                )

        def response_event(response):
            if response.request.resource_type in {"xhr", "fetch", "document", "other"}:
                network.append(
                    {
                        "stage": stage,
                        "status": response.status,
                        "url": safe_url(response.url),
                        "type": response.request.resource_type,
                    }
                )
            task = asyncio.create_task(received(response, stage))
            pending.add(task)
            task.add_done_callback(pending.discard)

        async def snapshot(label):
            await asyncio.sleep(args.wait_seconds)
            text = await page.locator("body").inner_text()
            await page.screenshot(path=str(output / f"{label}.png"), full_page=False)
            dom = await page.locator("[class]").evaluate_all(
                "els => els.filter(e => /Participant|Market|Fixture|Event|Team|Player/.test(e.className))"
                ".filter(e => e.innerText && e.innerText.length < 400)"
                ".slice(0, 250).map(e => ({tag:e.tagName, class:e.className, text:e.innerText}))"
            )
            controls = await page.get_by_text(
                re.compile(r"^(NBA|NFL|World Series|Points|Pass Yds|Receiving Yds|Rush Yds|Player Props)$")
            ).evaluate_all(
                "els => els.map((e, index) => ({index, text:e.innerText, tag:e.tagName, class:e.className, "
                "parents:[e.parentElement,e.parentElement?.parentElement,e.parentElement?.parentElement?.parentElement]"
                ".filter(Boolean).map(p => ({class:p.className,text:p.innerText.slice(0,250)})),"
                "rect:{x:e.getBoundingClientRect().x,y:e.getBoundingClientRect().y,w:e.getBoundingClientRect().width,h:e.getBoundingClientRect().height}}))"
            )
            item = {"stage": label, "url": page.url, "text": text, "dom": dom}
            item["controls"] = controls
            pages.append(item)
            (output / "pages.json").write_text(json.dumps(pages, indent=2) + "\n", encoding="utf-8")
            (output / "messages.json").write_text(json.dumps(messages, indent=2) + "\n", encoding="utf-8")
            (output / "network.json").write_text(json.dumps(network, indent=2) + "\n", encoding="utf-8")
            print(
                json.dumps(
                    {"stage": label, "url": page.url, "text_chars": len(text), "messages": len(messages)}
                ),
                flush=True,
            )

        page.on("response", response_event)
        page.on("pageerror", lambda error: page_errors.append(safe_text(str(error), 250)))
        try:
            response = await page.goto(
                f"https://www.{args.region}.bet365.com/", wait_until="domcontentloaded"
            )
            if response.status != 200:
                raise RuntimeError(f"Sportsbook returned HTTP {response.status}")
            await snapshot("home")
            cookies = page.get_by_text("Essential Only", exact=True)
            if await cookies.count():
                await cookies.first.click()
            for league, label in (
                [] if args.home_only else [("nba", "NBA"), ("nfl", "NFL"), ("mlb", "World Series")]
            ):
                if league not in args.leagues:
                    continue
                stage = league
                try:
                    await (
                        page.locator(".hsn-NavTab")
                        .filter(has_text=re.compile("^" + re.escape(label) + "$"))
                        .first.click(timeout=8000)
                    )
                    await snapshot(league)
                    if args.cycle_props:
                        containers = (
                            page.locator(".ss-HomepageSpotlight").filter(
                                has=page.locator(".ss-HomeSpotlightHeader_Title").filter(
                                    has_text=re.compile("^NBA$")
                                )
                            )
                            if league == "nba"
                            else page.locator(".prp-d").filter(has_text="MLB" if league == "mlb" else "NFL")
                        )
                        if await containers.count():
                            container = containers.first
                            labels = {
                                "nba": [
                                    "Points",
                                    "Assists",
                                    "Rebounds",
                                    "Threes Made",
                                    "Double Double",
                                    "Triple Double",
                                ],
                                "nfl": ["TD Scorer", "Quarterback", "Receiving", "Rushing"],
                                "mlb": ["Hits", "Strikeouts", "Bases", "RBIs", "HRs", "Hits, Runs & RBIs"],
                            }[league]
                            print(
                                json.dumps(
                                    {"league": league, "prop_container_count": await containers.count()}
                                ),
                                flush=True,
                            )
                            for prop in labels:
                                stage = league + "_" + re.sub(r"[^a-z0-9]+", "_", prop.lower()).strip("_")
                                matches = container.locator("span").filter(
                                    has_text=re.compile("^" + re.escape(prop) + "$")
                                )
                                if not await matches.count():
                                    matches = container.get_by_text(prop, exact=True)
                                if not await matches.count():
                                    continue
                                await matches.first.click(timeout=5000)
                                await snapshot(stage)
                                prop_views.append(
                                    {
                                        "league": league,
                                        "prop_tab": prop,
                                        "stage": stage,
                                        "text": await container.inner_text(),
                                    }
                                )
                                (output / "prop-views.json").write_text(
                                    json.dumps(prop_views, indent=2) + "\n", encoding="utf-8"
                                )
                except Error as error:
                    print(json.dumps({"stage": league, "error_type": type(error).__name__}), flush=True)
            if args.event_props:
                routes = {}
                for message in messages:
                    for row in message["records"]:
                        f = row["fields"]
                        league = f.get("L3", "").lower()
                        if row["type"] == "MG" and f.get("SY") == "ppg" and league in args.leagues:
                            routes.setdefault(league, f.get("PD"))
                for league, route in routes.items():
                    stage = league + "_props"
                    await page.goto(
                        f"https://www.{args.region}.bet365.com/#/" + route.strip("#").replace("#", "/") + "/"
                    )
                    await snapshot(stage)
        finally:
            page.remove_listener("response", response_event)
            if pending:
                await asyncio.gather(*list(pending), return_exceptions=True)
            (output / "messages.json").write_text(json.dumps(messages, indent=2) + "\n", encoding="utf-8")
            (output / "page-errors.json").write_text(
                json.dumps(page_errors, indent=2) + "\n", encoding="utf-8"
            )
            await context.close()
            await browser.close()
    from scripts.organize_bet365_dump import organize

    report = organize(messages, pages, prop_views, args.region)
    report["source_records_file"] = "messages.json"
    report["ui_views_file"] = "prop-views.json"
    (output / "odds.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for league in report["leagues"]:
        (output / (league["title"].lower() + ".json")).write_text(
            json.dumps(
                {"source": report["source"], "verification_only": True, "coverage_complete": False, **league},
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    (output / "summary.json").write_text(
        json.dumps(
            {
                "generated_at": report["generated_at"],
                "source": report["source"],
                "summary": report["summary"],
                "leagues": [{"title": league["title"], **league["summary"]} for league in report["leagues"]],
                "ui_tab_evidence": report["ui_tab_evidence"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output / "odds.json"), "summary": report["summary"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", choices=("va", "nj"), default="va")
    parser.add_argument("--leagues", nargs="+", choices=("nba", "nfl", "mlb"), default=["nba", "nfl", "mlb"])
    parser.add_argument("--wait-seconds", type=float, default=5)
    parser.add_argument("--home-only", action="store_true")
    parser.add_argument("--event-props", action="store_true")
    parser.add_argument("--cycle-props", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/bet365-markets"))
    args = parser.parse_args()
    os.environ.setdefault(
        "PLAYWRIGHT_BROWSERS_PATH", str(Path(__file__).resolve().parents[1] / ".cache/ms-playwright")
    )
    asyncio.run(capture(args))


if __name__ == "__main__":
    main()
