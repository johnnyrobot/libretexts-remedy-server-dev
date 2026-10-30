"""Only sanitized commissioning diagnostics may enter retained proof artifacts."""
import importlib.util
from pathlib import Path


def test_ephemeral_file_credentials_are_redacted_before_retention(tmp_path):
    path = Path(__file__).resolve().parents[2] / '.github/stack-proof/evidence.py'
    spec = importlib.util.spec_from_file_location('stack_evidence', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = tmp_path / 'product.log'
    module.write_product_log(output, 'uri=mongodb://conductor:ephemeral-password@mongo synthetic-server-key',
                             ['ephemeral-password'])
    assert output.read_text() == 'uri=mongodb://conductor:[synthetic credential redacted]@mongo [synthetic credential redacted]'


def test_browser_failure_collection_never_retains_login_fixtures(tmp_path):
    path = Path(__file__).resolve().parents[2] / '.github/stack-proof/evidence.py'
    spec = importlib.util.spec_from_file_location('stack_evidence', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    work = tmp_path / 'work'; work.mkdir()
    private = work / 'browser-config-release'; private.mkdir()
    (private / 'app.json').write_text('{"password":"ephemeral-private-value"}')
    browser = work / 'browser-release'; browser.mkdir()
    (browser / 'synthetic-failure.png').write_bytes(b'controlled screenshot')
    (browser / 'browser-error.json').write_text('{"error":"ephemeral-private-value"}')
    (browser / 'unapproved.json').write_text('ephemeral-private-value')
    out = tmp_path / 'out'; out.mkdir()
    module.collect_browser_evidence(work, out, ['release'], ['ephemeral-private-value'])
    assert sorted(p.name for p in out.iterdir()) == ['browser-release-browser-error.json', 'browser-release-synthetic-failure.png']
    assert 'ephemeral-private-value' not in (out / 'browser-release-browser-error.json').read_text()
