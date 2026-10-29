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


async def shipping_process_evidence(pid):
    directory = Path(os.environ["REMEDY_SANDBOX_AUDIT_DIR"])
    ticks = (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[19]
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
async def test_actual_tool_launch_preserves_shipping_linux_sandbox(tmp_path, tool):
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
    started = time.time()
    task = asyncio.create_task(execute())
    observed = {}
    try:
        async with asyncio.timeout(70):
            while not task.done() and not {"browser", "renderer"} <= observed.keys():
                for process in psutil.Process().children(recursive=True):
                    try:
                        if process.create_time() < started or "chrome" not in process.name().lower():
                            continue
                        args = process.cmdline()
                        kind = "renderer" if "--type=renderer" in args else (
                            "browser" if not any(arg.startswith("--type=") for arg in args) else None)
                        if kind is not None and kind not in observed:
                            observed[kind] = await shipping_process_evidence(process.pid)
                    except (psutil.NoSuchProcess, FileNotFoundError):
                        continue
                await asyncio.sleep(.01)
        await task
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
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await converter.close()
