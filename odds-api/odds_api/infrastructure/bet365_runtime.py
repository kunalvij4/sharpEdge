"""Shared capture diagnostics, subprocess cleanup, and artifact retention."""

import asyncio
import json
import re
import shutil
import signal
import sys
from urllib.parse import urlsplit, urlunsplit


def safe_url(value):
    """Omit credentials, queries, fragments, and long opaque path components."""
    parts = urlsplit(value)
    host = parts.hostname or ""
    if parts.port:
        host += f":{parts.port}"
    path = "/".join("[opaque]" if len(p) > 64 else p for p in parts.path.split("/"))
    return urlunsplit((parts.scheme, host, path, "", ""))


def safe_text(value, limit=2000):
    value = re.sub(r"https?://\S+", "[URL]", value)
    value = re.sub(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", "[email]", value)
    value = re.sub(r"\b[A-Za-z0-9_+=/-]{32,}\b", "[opaque]", value)
    return value[:limit]


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def prune_runs(output, keep):
    root = output / "runs"
    if not root.exists():
        return
    if root.is_symlink() or root.resolve().parent != output.resolve():
        raise RuntimeError("Run directory must be a direct directory under the artifact output")
    directories = sorted(
        (
            path
            for path in root.iterdir()
            if re.fullmatch(r"\d{8}T\d{6}\.\d{6}Z", path.name) and path.is_dir() and not path.is_symlink()
        ),
        reverse=True,
    )
    for path in directories[keep:]:
        resolved = path.resolve()
        if resolved.parent == root.resolve():
            shutil.rmtree(resolved)


async def command(arguments, timeout, *, environment=None):
    options = {"env": environment} if environment is not None else {}
    child = await asyncio.create_subprocess_exec(sys.executable, "-m", *arguments, **options)
    try:
        code = await asyncio.wait_for(child.wait(), timeout)
        if code:
            raise RuntimeError(f"{arguments[0]} exited with code {code}")
    finally:
        if child.returncode is None:
            try:
                child.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(child.wait(), 15)
            except TimeoutError:
                child.kill()
                await child.wait()
