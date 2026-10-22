"""Launch an ordinary headed browser and attach Playwright through loopback CDP."""

import asyncio
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path


def browser_executable(playwright, channel):
    if channel != "msedge":
        return playwright.chromium.executable_path
    if sys.platform == "win32":
        return str(
            Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
            / "Microsoft/Edge/Application/msedge.exe"
        )
    executable = shutil.which("microsoft-edge") or shutil.which("microsoft-edge-stable")
    if not executable:
        raise RuntimeError("Microsoft Edge is not installed; run playwright install msedge")
    return executable


async def launch_native_browser(playwright, channel, profile, log_path, *, no_sandbox=False):
    from playwright.async_api import Error

    profile = profile.resolve()
    profile.mkdir(parents=True, exist_ok=True)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    command = [
        browser_executable(playwright, channel),
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if no_sandbox:
        command.append("--no-sandbox")
    command.append("about:blank")
    with log_path.open("wb") as log:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=log)
    try:
        for attempt in range(60):
            if process.poll() is not None:
                raise RuntimeError(f"Headed browser exited with code {process.returncode}; see {log_path}")
            try:
                browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=3000)
                return browser, process
            except Error:
                if attempt == 59:
                    raise RuntimeError(f"Headed browser did not expose CDP; see {log_path}") from None
                await asyncio.sleep(0.25)
    except BaseException:
        if process.poll() is None:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait)
        raise


async def close_native_browser(browser, process):
    from playwright.async_api import Error

    try:
        session = await browser.new_browser_cdp_session()
        await session.send("Browser.close")
    except Error:
        pass
    await browser.close()
    if process.poll() is None:
        try:
            await asyncio.to_thread(process.wait, timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait)
