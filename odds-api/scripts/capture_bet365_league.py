"""Inspect headed sportsbook league tabs, including explicit over/under props."""

import argparse
import asyncio
import json
import os
import re
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

from scripts.capture_bet365_markets import records
from scripts.probe_bet365 import safe_text, safe_url


async def capture(args):
    from playwright.async_api import Error, async_playwright

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    messages, network, snapshots, errors, tasks = [], [], [], [], set()
    stage = "home"
    sockets = []
    public_params = {}
    route_manifest = []
    homepage_request = {}
    league_request = {}

    async with async_playwright() as playwright:
        cdp_process = None
        if args.cdp:
            executable = (
                Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
                / "Microsoft/Edge/Application/msedge.exe"
                if args.channel == "msedge"
                else Path(playwright.chromium.executable_path)
            )
            profile = args.profile_dir or Path(".cache") / ("bet365-cdp-" + output.name)
            profile.resolve().mkdir(parents=True, exist_ok=True)
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            cdp_process = subprocess.Popen(
                [
                    str(executable),
                    f"--remote-debugging-port={port}",
                    "--remote-debugging-address=127.0.0.1",
                    f"--user-data-dir={profile.resolve()}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "about:blank",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for attempt in range(40):
                try:
                    browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
                    break
                except Error:
                    if attempt == 39:
                        cdp_process.terminate()
                        raise
                    await asyncio.sleep(0.25)
            context = browser.contexts[0]
        elif args.profile_dir:
            context = await playwright.chromium.launch_persistent_context(
                str(args.profile_dir.resolve()),
                headless=False,
                channel=args.channel,
                viewport={"width": 1600, "height": 1100},
            )
            browser = context.browser
        else:
            browser = await playwright.chromium.launch(headless=False, channel=args.channel)
            context = await browser.new_context(viewport={"width": 1600, "height": 1100})
        page = await context.new_page()

        def socket_opened(socket):
            item = {"url": safe_url(socket.url), "frames": 0, "bytes": 0}
            sockets.append(item)

            def frame(payload):
                item["frames"] += 1
                item["bytes"] += len(payload)
                text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
                parsed = records(text)
                if parsed:
                    messages.append(
                        {
                            "stage": stage,
                            "received_at": datetime.now(UTC).isoformat(),
                            "source_url": safe_url(socket.url),
                            "records": parsed,
                            "transport": "websocket",
                        }
                    )

            socket.on("framereceived", frame)
            socket.on(
                "socketerror",
                lambda error: errors.append(
                    {"stage": stage, "socket_url": safe_url(socket.url), "error": safe_text(str(error), 150)}
                ),
            )

        async def response_body(response, source_stage):
            item = {
                "stage": source_stage,
                "url": safe_url(response.url),
                "status": response.status,
                "type": response.request.resource_type,
            }
            params = {
                key: value
                for key, value in parse_qsl(urlsplit(response.url).query)
                if key.lower() in {"pd", "lid", "zid", "cid", "cg", "ct", "ot", "wg", "cgid", "ctid", "csid"}
            }
            item["query_parameter_names"] = sorted(key for key, _ in parse_qsl(urlsplit(response.url).query))
            item["public_route_params"] = params
            if "/pullpodapi/gethomepagepods" in response.url:
                public_params.update(params)
                homepage_request.update(
                    {
                        "url": response.url,
                        "headers": {
                            key: value
                            for key, value in response.request.headers.items()
                            if key in {"boot", "x-net-sync-term"}
                        },
                    }
                )
            item["method"] = response.request.method
            item["request_header_names"] = sorted(response.request.headers)
            network.append(item)
            if response.status != 200 or response.request.resource_type not in {"xhr", "fetch", "other"}:
                return
            if not (response.url.split("/", 3)[2].endswith(".bet365.com")):
                return
            try:
                body = await asyncio.wait_for(response.body(), 10)
                item["bytes"] = len(body)
                if body and "/contentdata/matchmarketscontentapi/markets" in response.url:
                    league_request["url"] = response.url
                item["content_type"] = response.headers.get("content-type")
                if args.diagnostics and "/Api/1/Blob" in response.url:
                    (output / f"blob-{len(network)}.js").write_text(
                        body.decode("utf-8", errors="replace"), encoding="utf-8"
                    )
                if "routingdata" in response.url:
                    item["route_api_names"] = sorted(
                        set(
                            re.findall(
                                r"[A-Za-z0-9/_-]*[Aa]pi[A-Za-z0-9/_-]*",
                                body.decode("utf-8", errors="replace"),
                            )
                        )
                    )[:150]
                    (output / "routing-config.json").write_text(
                        body.decode("utf-8", errors="replace"), encoding="utf-8"
                    )
                    route_manifest.extend(json.loads(body).get("manifest", []))
                if len(body) > 4_000_000:
                    return
                parsed = records(body.decode("utf-8", errors="replace"))
                if parsed:
                    messages.append(
                        {
                            "stage": source_stage,
                            "received_at": datetime.now(UTC).isoformat(),
                            "source_url": safe_url(response.url),
                            "records": parsed,
                        }
                    )
            except (Error, TimeoutError):
                item["body_unavailable"] = True

        def received(response):
            task = asyncio.create_task(response_body(response, stage))
            tasks.add(task)
            task.add_done_callback(tasks.discard)

        async def save(label):
            await asyncio.sleep(args.wait_seconds)
            text = await page.locator("body").inner_text()
            controls = await page.get_by_text(
                re.compile(
                    r"^(Game Lines|Points O/U|Points|Rebounds|Assists|Threes Made|Points, Assists & Rebounds|Lines|Props|NBA|NFL|World Series)$"
                )
            ).evaluate_all(
                "els => els.map(e => ({text:e.innerText,tag:e.tagName,class:e.className,"
                "parents:[e.parentElement,e.parentElement?.parentElement].filter(Boolean).map(p=>({class:p.className,text:p.innerText.slice(0,400)})),"
                "rect:{x:e.getBoundingClientRect().x,y:e.getBoundingClientRect().y,w:e.getBoundingClientRect().width,h:e.getBoundingClientRect().height}}))"
            )
            snapshots.append(
                {
                    "stage": label,
                    "url": page.url,
                    "captured_at": datetime.now(UTC).isoformat(),
                    "text": text,
                    "controls": controls,
                }
            )
            await page.screenshot(path=str(output / f"{label}.png"))
            for name, data in [
                ("messages", messages),
                ("network", network),
                ("pages", snapshots),
                ("errors", errors),
                ("sockets", sockets),
            ]:
                (output / f"{name}.json").write_text(
                    json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )
            print(
                json.dumps(
                    {"stage": label, "url": page.url, "text_chars": len(text), "messages": len(messages)}
                ),
                flush=True,
            )

        async def market_loaded(route, start_index, timeout=25):
            identifier = re.search(r"#E([^#]+)#", route).group(1)
            deadline = asyncio.get_running_loop().time() + timeout
            while asyncio.get_running_loop().time() < deadline:
                if any(
                    any(row["type"] == "PA" and row["fields"].get("OD") for row in message["records"])
                    and any(
                        row["type"] == "MG"
                        and row["fields"].get("SY") == "cmx"
                        and row["fields"].get("ID") == identifier
                        for row in message["records"]
                    )
                    for message in messages[start_index:]
                ):
                    return True
                await asyncio.sleep(0.2)
            return False

        page.on("response", received)
        page.on("websocket", socket_opened)
        page.on(
            "console",
            lambda message: errors.append(
                {"stage": stage, "console_type": message.type, "text": safe_text(message.text, 300)}
            )
            if message.type in {"warning", "error"} and len(errors) < 100
            else None,
        )
        page.on(
            "pageerror", lambda error: errors.append({"stage": stage, "error": safe_text(str(error), 250)})
        )
        page.on(
            "requestfailed",
            lambda request: errors.append(
                {
                    "stage": stage,
                    "url": safe_url(request.url),
                    "failure": safe_text(request.failure or "", 150),
                }
            ),
        )
        try:
            response = await page.goto(
                f"https://www.{args.region}.bet365.com/", wait_until="domcontentloaded"
            )
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}")
            await save("home")
            consent = page.get_by_text("Essential Only", exact=True)
            if await consent.count():
                await consent.first.click()
                await asyncio.sleep(2)
            source_routes = {}
            for message in messages:
                for row in message["records"]:
                    fields = row["fields"]
                    if fields.get("L3", "").lower() != args.league or not fields.get("PD"):
                        continue
                    if row["type"] == "PA" and fields.get("FD") and "#D19#" in fields["PD"]:
                        source_routes.setdefault("event", fields["PD"])
                    if row["type"] == "MG" and fields.get("SY") == "ppg":
                        source_routes.setdefault("player-props", fields["PD"])
            stage = args.league + "_lines"
            title = {"nba": "NBA", "nfl": "NFL", "mlb": "World Series"}[args.league]
            if args.entry == "classification":
                title = {"nba": "Basketball", "nfl": "Football", "mlb": "Baseball"}[args.league]
            if args.entry in {"event", "player-props", "league"}:
                route = source_routes.get("event" if args.entry == "league" else args.entry)
                if not route:
                    raise RuntimeError("Requested source route was not found in homepage data")
                await page.goto(
                    f"https://www.{args.region}.bet365.com/#/" + route.strip("#").replace("#", "/") + "/"
                )
                if args.entry == "league":
                    await save(args.league + "_event")
                    routes = [
                        route
                        for message in messages
                        for row in message["records"]
                        if row["type"] == "EV"
                        for route in re.findall(
                            r"#AC#(?:[A-Z][A-Za-z0-9^_-]*#)+", row["fields"].get("TB", "")
                        )
                        if "#D48#" in route
                    ]
                    if not routes:
                        raise RuntimeError("No source league breadcrumb found on event page")
                    await page.goto(
                        f"https://www.{args.region}.bet365.com/#/"
                        + routes[-1].strip("#").replace("#", "/")
                        + "/"
                    )
            elif args.entry == "view-all":
                section = page.locator(".ss-HomepageSpotlight").filter(
                    has=page.locator(".ss-HomeSpotlightHeader_Title").filter(
                        has_text=re.compile("^" + re.escape(title) + "$")
                    )
                )
                await section.get_by_text("View All", exact=True).first.click(timeout=10000)
            else:
                await (
                    page.locator(".lhs-fa")
                    .filter(has_text=re.compile("^" + re.escape(title) + "$"))
                    .first.click(timeout=10000)
                )
            await save(stage)
            if args.reload_league:
                stage = args.league + "_lines_reload"
                await page.reload(wait_until="domcontentloaded")
                await save(stage)
            if not await page.get_by_text("Game Lines", exact=True).count():
                errors.append({"stage": stage, "error_type": "league_content_unavailable"})
                if args.fetch_coupon:
                    stage = args.league + "_coupon_request"
                    fragment = unquote(urlsplit(page.url).fragment)
                    params = {**public_params, "pd": "#" + fragment.strip("/").replace("/", "#") + "#"}
                    tokens = fragment.strip("/").split("/")

                    def matches(rule):
                        if rule.get("t") != tokens[0]:
                            return False
                        for condition in rule.get("m", "").split("~"):
                            if not condition:
                                continue
                            prefix, values = condition.split(":", 1)
                            if not any(prefix + value in tokens for value in values.split(",")):
                                return False
                        return True

                    routes = sorted(
                        [row for row in route_manifest if matches(row)], key=lambda r: int(r.get("o", 0))
                    )
                    endpoint = routes[0]["e"] if routes else None
                    if not endpoint:
                        raise RuntimeError("No matching published content route")
                    result = await page.evaluate(
                        """async ({params,endpoint,homepage,diagnostics}) => {
                        const get=async (url,headers={},xhr=false) => {
                            if(xhr) return await new Promise(resolve => {
                                const req=new XMLHttpRequest();req.open('GET',url);
                                for(const [k,v] of Object.entries(headers))req.setRequestHeader(k,v);
                                req.onload=()=>resolve({status:req.status,bytes:req.responseText.length});
                                req.onerror=()=>resolve({error:'xhr_failed'});req.send();
                            });
                            const response=await fetch(url,{headers});
                            const text=await response.text();
                            return {status:response.status,bytes:text.length};
                        };
                        const url=endpoint+'?'+new URLSearchParams(params);
                        const results={plain:await get(url)};
                        if(diagnostics){
                            results.homepage_control=await get(homepage.url);
                            results.observed_headers=await get(url,homepage.headers);
                            results.xhr=await get(url,homepage.headers,true);
                            const source=new URL(homepage.url);
                            source.pathname=endpoint;
                            source.searchParams.set('pd',params.pd);
                            if(window.Locator?.config?.removeStateId)source.searchParams.delete('csid');
                            results.original_query=await get(source.href,homepage.headers);
                            if(window.ns_gen5_net?.Loader){
                                results.site_loader=await new Promise(resolve=>{
                                    const loader=new window.ns_gen5_net.Loader();
                                    const timer=setTimeout(()=>{loader.abort();resolve({error:'timeout'});},15000);
                                    loader.completeHandler=(text,status)=>{clearTimeout(timer);resolve({status,bytes:text.length});};
                                    loader.errorHandler=status=>{clearTimeout(timer);resolve({status,error:'site_loader_failed'});};
                                    loader.load(source.href);
                                });
                            }
                        }
                        return results;
                    }""",
                        {
                            "params": params,
                            "endpoint": endpoint,
                            "homepage": homepage_request,
                            "diagnostics": args.diagnostics,
                        },
                    )
                    print(json.dumps({"stage": stage, "endpoint": endpoint, **result}), flush=True)
                    await save(stage)
                return
            if args.discover_ou:
                stage = args.league + "_all_markets"
                await page.get_by_text("All", exact=True).filter(visible=True).first.click(timeout=8000)
                await page.get_by_text("All Markets", exact=True).wait_for(state="visible", timeout=8000)
                await (
                    page.get_by_text("A-Z", exact=True)
                    .and_(page.locator(":not(.lhs-5)"))
                    .filter(visible=True)
                    .click(timeout=8000)
                )
                deadline = asyncio.get_running_loop().time() + 20
                while not any(
                    message["stage"] == stage
                    and any(row["fields"].get("NA", "").endswith(" O/U") for row in message["records"])
                    for message in messages
                ):
                    if asyncio.get_running_loop().time() > deadline:
                        break
                    await asyncio.sleep(0.2)
                await save(stage)
                discovered = {}
                route_messages = messages
                if args.routes_file:
                    route_messages = json.loads(args.routes_file.read_text(encoding="utf-8"))
                for message in route_messages:
                    if not args.routes_file and message["stage"] != stage:
                        continue
                    for row in message["records"]:
                        fields = row["fields"]
                        label, route = fields.get("NA", ""), fields.get("PD", "")
                        if (
                            label.endswith(" O/U")
                            and route.startswith("#AC#")
                            and not re.search(r"quarter|half|inning", label, re.I)
                        ):
                            discovered[label] = route
                if not discovered:
                    raise RuntimeError("No explicit O/U routes found in the complete market menu")
                for tab, route in discovered.items():
                    if args.market_filter and not re.search(args.market_filter, tab, re.I):
                        continue
                    stage = args.league + "_" + re.sub(r"[^a-z0-9]+", "_", tab.lower()).strip("_")
                    start_index = len(messages)
                    if args.content_fetch:
                        if not any(
                            "/contentdata/matchmarketscontentapi/markets" in row["url"] for row in network
                        ):
                            raise RuntimeError(
                                "Content-data endpoint was not observed in this browser session"
                            )
                        result = await page.evaluate(
                            """route => {
                            const manager=window.Locator.subscriptionManager;
                            const service=manager.pullServiceLocator.getUrlForTopic(route);
                            if(!service)return {error:'service_not_found'};
                            manager.pullDataProcessor.loadPageData(route,service.qsParams,service.url,service.flags);
                            return {endpoint:service.url.split('?')[0],flags:service.flags,query_keys:Object.keys(service.qsParams||{})};
                        }""",
                            route,
                        )
                        result["expected_market_received"] = await market_loaded(
                            route, start_index, timeout=15
                        )
                        if not result["expected_market_received"]:
                            errors.append(
                                {
                                    "stage": stage,
                                    "error_type": "expected_market_response_missing",
                                    "route": route,
                                }
                            )
                        print(json.dumps({"stage": stage, "browser_content_request": result}), flush=True)
                        await save(stage)
                        continue
                    await page.bring_to_front()
                    # A real market-menu click also closes the popup and invokes the site's router.
                    if not await page.get_by_text("All Markets", exact=True).is_visible():
                        await (
                            page.get_by_text("All", exact=True).filter(visible=True).first.click(timeout=8000)
                        )
                        await page.get_by_text("All Markets", exact=True).wait_for(
                            state="visible", timeout=8000
                        )
                        await (
                            page.get_by_text("A-Z", exact=True)
                            .and_(page.locator(":not(.lhs-5)"))
                            .filter(visible=True)
                            .click(timeout=8000)
                        )
                    await page.get_by_text(tab, exact=True).filter(visible=True).first.click(timeout=15000)
                    ready = await market_loaded(route, start_index)
                    if not ready:
                        errors.append(
                            {"stage": stage, "error_type": "expected_market_response_missing", "route": route}
                        )
                    await save(stage)
                return
            for tab in args.tabs:
                stage = args.league + "_" + re.sub(r"[^a-z0-9]+", "_", tab.lower()).strip("_")
                try:
                    start_index = len(messages)
                    routes = [
                        row["fields"]["PD"]
                        for message in messages
                        for row in message["records"]
                        if row["type"] == "MA"
                        and row["fields"].get("NA") == tab
                        and re.search(r"#D(?:43|47)#", row["fields"].get("PD", ""))
                    ]
                    candidates = page.get_by_text(tab, exact=True).filter(visible=True)
                    target = candidates.last if tab in {"A-Z", "Player", "Main Props"} else candidates.first
                    await target.click(timeout=8000)
                    if routes and args.entry not in {"event", "player-props"}:
                        if not await market_loaded(routes[-1], start_index, timeout=15):
                            errors.append(
                                {
                                    "stage": stage,
                                    "error_type": "expected_market_response_missing",
                                    "route": routes[-1],
                                }
                            )
                    await save(stage)
                except Error as error:
                    errors.append({"stage": stage, "error_type": type(error).__name__})
                    print(json.dumps(errors[-1]), flush=True)
        finally:
            unexpected_failure = sys.exc_info()[0] is not None
            page.remove_listener("response", received)
            if tasks:
                await asyncio.gather(*list(tasks), return_exceptions=True)
            for name, data in [
                ("messages", messages),
                ("network", network),
                ("pages", snapshots),
                ("errors", errors),
                ("sockets", sockets),
            ]:
                (output / f"{name}.json").write_text(
                    json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )
            failed = unexpected_failure or any(
                item.get("error_type")
                in {"league_content_unavailable", "expected_market_response_missing", "TimeoutError", "Error"}
                for item in errors
            )
            (output / "capture-status.json").write_text(
                json.dumps(
                    {
                        "requested_navigation_succeeded": not failed,
                        "coverage_complete": False,
                        "browser_mode": "headed_cdp" if args.cdp else "headed_playwright",
                        "region": args.region,
                        "league": args.league,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            if cdp_process:
                try:
                    session = await browser.new_browser_cdp_session()
                    await session.send("Browser.close")
                except Error:
                    pass
            await browser.close()
            if cdp_process and cdp_process.poll() is None:
                cdp_process.terminate()
            if failed and not unexpected_failure:
                raise RuntimeError(
                    "Requested navigation or market response was incomplete; see capture-status.json and errors.json"
                )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", choices=("va", "nj"), default="va")
    parser.add_argument("--league", choices=("nba", "nfl", "mlb"), default="nba")
    parser.add_argument("--channel", choices=("chromium", "msedge"), default="chromium")
    parser.add_argument("--reload-league", action="store_true")
    parser.add_argument("--profile-dir", type=Path)
    parser.add_argument("--cdp", action="store_true")
    parser.add_argument(
        "--entry",
        choices=("sidebar", "view-all", "classification", "event", "player-props", "league"),
        default="sidebar",
    )
    parser.add_argument("--fetch-coupon", action="store_true")
    parser.add_argument("--diagnostics", action="store_true")
    parser.add_argument("--discover-ou", action="store_true")
    parser.add_argument("--content-fetch", action="store_true")
    parser.add_argument("--market-filter")
    parser.add_argument("--routes-file", type=Path)
    parser.add_argument(
        "--tabs",
        nargs="*",
        default=["Points O/U", "Points", "Rebounds", "Assists", "Threes Made", "Points, Assists & Rebounds"],
    )
    parser.add_argument("--wait-seconds", type=float, default=6)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/bet365-league-discovery"))
    args = parser.parse_args()
    os.environ.setdefault(
        "PLAYWRIGHT_BROWSERS_PATH", str(Path(__file__).resolve().parents[1] / ".cache/ms-playwright")
    )
    asyncio.run(capture(args))


if __name__ == "__main__":
    main()
