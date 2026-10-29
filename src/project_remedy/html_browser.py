"""Offline document transport shared by every HTML browser consumer.

No external allowlist or arbitrary filesystem asset mapping exists. Documents
remain unmodified; CSP refusals are incomplete work, never clean validation.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import tempfile
from contextlib import suppress

POLICY = json.loads((Path(__file__).with_name("html_tools") / "policy.json").read_text())


class HTMLResourceBlocked(RuntimeError):
    """The original document cannot be fully evaluated under the offline policy."""


class HTMLCheckerDependencyError(FileNotFoundError):
    """Required local checker tooling is unavailable."""


def document_bytes(html: str) -> bytes:
    content = html.encode("utf-8")
    if len(content) > POLICY["max_document_bytes"]:
        raise HTMLResourceBlocked("HTML exceeds the offline document byte limit.")
    return content


def browser_environment() -> dict[str, str]:
    # Chromium has no provider credentials, proxy settings, service keys or
    # inherited custom launch flags. Its fresh context has no stored cookies.
    return {key: os.environ[key] for key in ("PATH", "LANG", "TMPDIR") if key in os.environ}


async def launch_browser(playwright):
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise RuntimeError("HTML browsers require a non-root user and the Chromium sandbox.")
    return await playwright.chromium.launch(
        headless=True, chromium_sandbox=True, env=browser_environment(),
        args=["--host-resolver-rules=MAP * ~NOTFOUND", "--dns-prefetch-disable", "--disable-background-networking"],
    )


_POLICY_OBSERVER = """() => {
  window.__remedyPolicyBlocked = false;
  document.addEventListener('securitypolicyviolation', () => {
    window.__remedyPolicyBlocked = true;
  });
}"""


async def ensure_complete(page, blocked: list) -> None:
    if blocked or page.url != POLICY["document_url"] or await page.evaluate("selector => window.__remedyPolicyBlocked === true || !!document.querySelector(selector)", POLICY["incomplete_selector"]):
        raise HTMLResourceBlocked("HTML resources or active content are blocked by the offline policy; evaluation is incomplete.")


@asynccontextmanager
async def offline_page(browser, html: str, **context_options):
    content = document_bytes(html)
    context = await browser.new_context(
        service_workers="block", accept_downloads=False, **context_options,
    )
    blocked = []
    navigations = 0
    async def route_request(route):
        nonlocal navigations
        request = route.request
        if navigations == 0 and request.url == POLICY["document_url"] and request.is_navigation_request() and request.frame == page.main_frame:
            navigations += 1
            await route.fulfill(status=200, body=content, headers={
                "Content-Type": "text/html; charset=utf-8", "Content-Security-Policy": POLICY["csp"],
                "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            })
        else:
            blocked[:] = [True]
            await route.abort("blockedbyclient")
    try:
        async with asyncio.timeout(POLICY["timeout_seconds"]):
            await context.route("**/*", route_request)
            await context.add_init_script(f"({_POLICY_OBSERVER})()")
            page = await context.new_page()
            await page.goto(POLICY["document_url"], wait_until="networkidle", timeout=30000)
            await ensure_complete(page, blocked)
            yield page
            await ensure_complete(page, blocked)
    finally:
        await context.close()


async def run_html_checker(tool: str, html: str):
    """Run an actual locally pinned checker with bounded, credential-free IPC."""
    from playwright.async_api import async_playwright
    document_bytes(html)
    async with async_playwright() as playwright:
        executable = playwright.chromium.executable_path
    if not Path(executable).is_file():
        raise HTMLCheckerDependencyError("The pinned Chromium installation is unavailable.")
    request = json.dumps({"tool": tool, "html": html, "executablePath": executable}).encode()
    directory = Path(__file__).with_name("html_tools")
    with tempfile.TemporaryDirectory(prefix="remedy-checker-") as temporary:
        env = browser_environment() | {"HOME": temporary}
        if "REMEDY_HTML_TOOLS_ROOT" in os.environ:
            env["REMEDY_HTML_TOOLS_ROOT"] = os.environ["REMEDY_HTML_TOOLS_ROOT"]
        try:
            process = await asyncio.create_subprocess_exec(
                "node", str(directory / "check.mjs"), env=env,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            raise HTMLCheckerDependencyError("The local Node HTML checker runtime is unavailable.") from None
        try:
            stdout, _stderr = await asyncio.wait_for(process.communicate(request), POLICY["timeout_seconds"] + 10)
        except (TimeoutError, asyncio.CancelledError) as exc:
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.terminate()
            with suppress(TimeoutError):
                await asyncio.wait_for(process.wait(), 5)
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
            if isinstance(exc, TimeoutError):
                raise RuntimeError(f"{tool} timed out; HTML evaluation incomplete.") from None
            raise
        if process.returncode != 0 or not stdout or len(stdout) > 8 * 1024 * 1024:
            raise RuntimeError(f"{tool} unavailable or incomplete under the offline HTML resource policy.")
        try:
            return json.loads(stdout)
        except (ValueError, UnicodeError):
            raise RuntimeError(f"{tool} returned invalid JSON results.") from None
