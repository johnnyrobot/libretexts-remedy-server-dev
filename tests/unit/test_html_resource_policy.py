"""Actual offline browser/tool checks with synthetic listeners, never live targets."""
import asyncio
import os
from pathlib import Path
import base64
import io
import time
import json
import sys

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("REMEDY_HTML_BROWSER_TESTS") != "1" and os.environ.get("REMEDY_FULL_RUNTIME_TESTS") != "1",
    reason="explicit real-browser runtime suite",
)


async def test_renderer_refuses_external_resource_without_contact_or_partial_pdf(tmp_path):
    from project_remedy.html_to_pdf import HTMLToPDFConverter
    contacts = []
    async def serve(reader, writer):
        contacts.append(await reader.read(4096))
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()
    listener = await asyncio.start_server(serve, "127.0.0.1", 0)
    converter = HTMLToPDFConverter()
    output = tmp_path / "unavailable.pdf"
    try:
        await converter.start()
        port = listener.sockets[0].getsockname()[1]
        result = await converter.convert(
            f'<html><head><title>Probe</title></head><body><img alt="probe" src="http://127.0.0.1:{port}/metadata"></body></html>',
            output,
        )
        assert contacts == []
        assert result.success is False
        assert result.output_path is None
        assert not output.exists()
    finally:
        await converter.close()
        listener.close()
        await listener.wait_closed()


@pytest.mark.parametrize("tool", ["axe", "pa11y", "lighthouse"])
async def test_real_local_checker_evaluates_embedded_document_without_network(tmp_path, tool):
    from project_remedy.validator import AccessibilityValidator
    from project_remedy.config import PipelineConfig
    from project_remedy.database import DatabaseManager
    html = tmp_path / "input.html"
    from PIL import Image
    image = io.BytesIO()
    Image.new("RGB", (16, 16), "blue").save(image, format="PNG")
    encoded = base64.b64encode(image.getvalue()).decode()
    html.write_text('<!doctype html><html lang="en"><head><title>Offline fixture</title></head>'
                    '<body><main><h1>Retained sentinel</h1><p>Parser-valid synthetic document.</p>'
                    f'<img alt="Synthetic blue square" src="data:image/png;base64,{encoded}"></main></body></html>')
    validator = AccessibilityValidator(PipelineConfig(), None, DatabaseManager())
    result = await getattr(validator, "validate_with_" + tool)(html)
    assert result.tool == tool
    assert result.passed is True


@pytest.mark.parametrize("tool", ["axe", "pa11y", "lighthouse"])
async def test_actual_checkers_find_accessibility_defects(tmp_path, tool):
    from project_remedy.validator import AccessibilityValidator
    from project_remedy.config import PipelineConfig
    from project_remedy.database import DatabaseManager
    path = tmp_path / "missing-label.html"
    path.write_text('<!doctype html><html lang="en"><title>Missing label</title><body><main><h1>Form</h1><input type="text"></main></body></html>')
    result = await getattr(AccessibilityValidator(PipelineConfig(), None, DatabaseManager()), "validate_with_" + tool)(path)
    assert result.passed is False
    assert result.violations
    assert any("label" in (finding.get("id", "") + finding.get("description", "")).lower() for finding in result.violations)


async def test_unicode_document_transport_retains_original_bytes(monkeypatch):
    from project_remedy.html_browser import run_html_checker
    from playwright.async_api import async_playwright
    payloads = []
    class Process:
        returncode = 0
        async def communicate(self, request):
            payloads.append(request)
            return b'{"violations":[]}', b''
    async def spawn(*args, **kwargs):
        return Process()
    # Resolve the actual browser first, then replace only the external Node IPC.
    async with async_playwright() as playwright:
        executable = playwright.chromium.executable_path
    import playwright.async_api
    from types import SimpleNamespace
    class Driver:
        async def __aenter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(executable_path=executable))
        async def __aexit__(self, *args):
            return None
    monkeypatch.setattr(playwright.async_api, "async_playwright", Driver)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    html = '<html><body>' + '\U0001f9ed' * 750000 + '</body></html>'
    await run_html_checker("axe", html)
    assert json.loads(payloads[0])["html"] == html
    assert len(payloads[0]) < 4 * 1024 * 1024


@pytest.mark.parametrize("tool", ["axe", "pa11y", "lighthouse"])
@pytest.mark.parametrize("probe", ["image", "redirect", "script", "file", "metadata"])
async def test_actual_checkers_refuse_prohibited_resources_without_contact(tmp_path, tool, probe):
    from project_remedy.html_browser import run_html_checker
    from project_remedy.config import PipelineConfig
    from project_remedy.database import DatabaseManager
    from project_remedy.validator import AccessibilityValidator
    contacts = []
    async def serve(reader, writer):
        contacts.append(await reader.read(4096))
        writer.write(b"HTTP/1.1 302 Found\r\nLocation: file:///etc/passwd\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()
    listener = await asyncio.start_server(serve, "127.0.0.1", 0)
    url = f"http://127.0.0.1:{listener.sockets[0].getsockname()[1]}/prohibited"
    secret = tmp_path / "synthetic-private.txt"
    secret.write_text("Synthetic private file sentinel")
    probes = {
        "image": f'<img src="{url}" alt="probe">',
        "redirect": f'<meta http-equiv="refresh" content="0;url={url}">',
        "script": f'<script>fetch("{url}");new WebSocket("{url.replace("http:", "ws:")}")</script>',
        "file": f'<iframe src="{secret.as_uri()}"></iframe>',
        "metadata": '<img src="http://169.254.169.254/latest/meta-data/" alt="probe">',
    }
    source = tmp_path / "probe.html"
    source.write_text(f'<!doctype html><html lang="en"><title>Probe</title><body><main><h1>Probe</h1>{probes[probe]}</main></body></html>')
    try:
        validator = AccessibilityValidator(PipelineConfig(), None, DatabaseManager())
        with pytest.raises(RuntimeError, match="incomplete|offline"):
            await getattr(validator, "validate_with_" + tool)(source)
        assert contacts == []
    finally:
        listener.close()
        await listener.wait_closed()


def kernel_start_ticks(pid):
    return (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[19]


async def shipping_process_evidence(pid):
    directory = Path(os.environ["REMEDY_SANDBOX_AUDIT_DIR"])
    ticks = kernel_start_ticks(pid)
    request_id = f"{os.getpid()}-{pid}-{time.monotonic_ns()}"
    temporary = directory / f"{request_id}.request.tmp"
    temporary.write_text(json.dumps({"pid": pid, "requestId": request_id, "startTicks": ticks}))
    temporary.replace(directory / f"{request_id}.request.json")
    response = directory / f"{request_id}.response.json"
    async with asyncio.timeout(5):
        while not response.exists():
            await asyncio.sleep(.01)
    data = json.loads(response.read_text())
    assert data["containerPid"] == pid and data["startTicks"] == ticks
    return data


@pytest.mark.parametrize("tool", ["render", "axe", "pa11y", "lighthouse"])
async def test_actual_tool_launch_preserves_shipping_linux_sandbox(tmp_path, tool, monkeypatch):
    if os.environ.get("REMEDY_FULL_RUNTIME_TESTS") != "1":
        pytest.skip("shipping Linux namespace proof requires the isolated image and host observer")
    import platform
    import psutil
    from project_remedy.html_to_pdf import HTMLToPDFConverter
    from project_remedy.html_browser import run_html_checker
    assert sys.platform == "linux" and platform.machine() == "x86_64" and os.geteuid() != 0
    assert "REMEDY_SANDBOX_AUDIT_DIR" in os.environ
    parent = await shipping_process_evidence(os.getpid())
    assert parent["status"]["NoNewPrivs"] == "1"
    assert int(parent["status"]["CapEff"], 16) == 0
    import subprocess
    chroot = subprocess.run(["chroot", "/", "/bin/true"], capture_output=True, timeout=5)
    assert chroot.returncode != 0 and b"Operation not permitted" in chroot.stderr
    source = '<!doctype html><html lang="en"><title>Sandbox fixture</title><body><main><h1>Retained sentinel</h1></main></body></html>'
    converter = HTMLToPDFConverter()
    async def execute():
        if tool == "render":
            await converter.start()
            result = await converter.convert(source, tmp_path / "sandbox.pdf")
            assert result.success, result.error_message
        else:
            await run_html_checker(tool, source)
    # Hold the actual navigated context until both host observations return.
    # This is test-only instrumentation; the shipping adapter is unmodified.
    from contextlib import asynccontextmanager
    from project_remedy import html_to_pdf
    ready, release = tmp_path / "observation-ready", tmp_path / "observation-release"
    original_page = html_to_pdf.offline_page
    @asynccontextmanager
    async def retained_page(*args, **kwargs):
        async with original_page(*args, **kwargs) as page:
            ready.touch()
            async with asyncio.timeout(15):
                while not release.exists():
                    await asyncio.sleep(.01)
            yield page
    monkeypatch.setattr(html_to_pdf, "offline_page", retained_page)
    preload = tmp_path / "retain-context.mjs"
    preload.write_text("""
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {access, writeFile} from 'node:fs/promises';
import path from 'node:path';
const require = createRequire(path.join(process.env.REMEDY_HTML_TOOLS_ROOT, 'package.json'));
const pa11yRequire = createRequire(require.resolve('pa11y/package.json'));
const puppeteer = (await import(pathToFileURL(pa11yRequire.resolve('puppeteer')).href)).default;
const launch = puppeteer.launch.bind(puppeteer);
puppeteer.launch = async (...args) => {
  const browser = await launch(...args);
  const newPage = browser.newPage.bind(browser);
  browser.newPage = async (...options) => {
    const page = await newPage(...options);
    const goto = page.goto.bind(page);
    page.goto = async (...navigation) => {
      const result = await goto(...navigation);
      await writeFile(READY_PATH, 'navigated');
      const deadline = performance.now() + 15000;
      for (;;) {
        try { await access(RELEASE_PATH); break; }
        catch (error) { if (error.code !== 'ENOENT') throw error; }
        if (performance.now() >= deadline) throw new Error('Observation barrier expired');
        await new Promise(resolve => setTimeout(resolve, 10));
      }
      return result;
    };
    return page;
  };
  return browser;
};
""".replace('READY_PATH', json.dumps(str(ready))).replace('RELEASE_PATH', json.dumps(str(release))))
    spawn = asyncio.create_subprocess_exec
    async def instrumented_spawn(*args, **kwargs):
        if len(args) > 1 and args[0] == "node" and str(args[1]).endswith("/html_tools/check.mjs"):
            args = (args[0], "--import", preload.as_uri(), *args[1:])
        return await spawn(*args, **kwargs)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", instrumented_spawn)
    # Linux /proc birth times and time.time() have different precision/origins:
    # the retained census in CI 40930595751 rejects every real browser on that
    # comparison. Exclude identities already owned before launch instead.
    initial_children = set()
    for process in psutil.Process().children(recursive=True):
        try:
            ticks = kernel_start_ticks(process.pid)
            initial_children.add((process.pid, ticks))
        except (psutil.NoSuchProcess, FileNotFoundError):
            continue
    started = time.time()  # diagnostics only; never a process identity predicate
    task = asyncio.create_task(execute())
    observed = {}
    candidates = {}
    candidate_ticks = {}
    census = []
    try:
        async with asyncio.timeout(45):  # startup watchdog, separate from observation
            while not ready.exists():
                if task.done():
                    await task  # retain the real tool exception
                    pytest.fail("tool completed without entering its observation barrier")
                await asyncio.sleep(.01)
        assert not task.done() and not release.exists()
        for process in psutil.Process().children(recursive=True):
            try:
                created = process.create_time()
                name = process.name()
                args = process.cmdline()
                ticks = kernel_start_ticks(process.pid)
                kind = "renderer" if "--type=renderer" in args else (
                    "browser" if any(arg == "--remote-debugging-pipe" or arg.startswith("--remote-debugging-port=") for arg in args)
                    and not any(arg.startswith("--type=") for arg in args) else None)
                rejected = []
                if (process.pid, ticks) in initial_children:
                    rejected.append("preexisting_owned_identity")
                if "chrome" not in name.lower():
                    rejected.append("name_without_chrome")
                if kind is None:
                    rejected.append("unclassified_argv")
                try:
                    executable = process.exe()
                except psutil.AccessDenied:
                    executable = "<access denied>"
                census.append({"pid": process.pid, "ppid": process.ppid(),
                               "ancestry": [ancestor.pid for ancestor in process.parents()],
                               "startTicks": ticks,
                               "name": name, "executable": executable,
                               "status": process.status(), "argv": args, "createTime": created,
                               "started": started, "previousCutoffWouldReject": created < started,
                               "kind": kind, "rejectedBy": rejected})
                if rejected:
                    continue
                if kind is not None and kind not in candidates:
                    candidates[kind] = process.pid
                    candidate_ticks[kind] = ticks
            except (psutil.NoSuchProcess, FileNotFoundError):
                continue
        assert {"browser", "renderer"} <= candidates.keys(), candidates
        records = await asyncio.gather(*(shipping_process_evidence(candidates[kind]) for kind in ("browser", "renderer")))
        observed = dict(zip(("browser", "renderer"), records))
        for kind, record in observed.items():
            assert record["startTicks"] == candidate_ticks[kind], "observed process identity changed"
        assert not task.done(), "tool lifetime ended during the observation barrier"
        release.touch()
        await asyncio.wait_for(task, 70)
        assert {"browser", "renderer"} <= observed.keys(), observed
        browser, renderer = observed["browser"], observed["renderer"]
        for record in (browser, renderer):
            args = record["commandLine"]
            assert not any(arg in args for arg in ("--no-sandbox", "--disable-namespace-sandbox", "--disable-seccomp-filter-sandbox", "--single-process"))
            assert int(record["status"]["Uid"].split()[0]) != 0
            assert record["status"]["NoNewPrivs"] == "1"
            assert int(record["status"]["CapEff"], 16) == 0
        assert renderer["status"]["Seccomp"] == "2"
        assert int(renderer["status"]["Seccomp_filters"]) > int(browser["status"]["Seccomp_filters"])
        assert renderer["userNamespace"] != browser["userNamespace"]
        assert renderer["pidNamespace"] != browser["pidNamespace"]
        assert len(renderer["hostNamespacePids"]) > len(browser["hostNamespacePids"])
        (Path(os.environ["REMEDY_SANDBOX_AUDIT_DIR"]) / f"sandbox-{tool}.json").write_text(json.dumps(observed, indent=2))
    finally:
        release.touch()  # also release on observer failure/cancellation
        (Path(os.environ["REMEDY_SANDBOX_AUDIT_DIR"]) / f"sandbox-{tool}-diagnostic.json").write_text(
            json.dumps({"entered": ready.exists(), "taskDone": task.done(), "candidates": candidates, "observed": observed, "census": census,
                        "initialChildren": sorted(initial_children)}, indent=2))
        try:
            await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 15)
        finally:
            await asyncio.wait_for(converter.close(), 15)
