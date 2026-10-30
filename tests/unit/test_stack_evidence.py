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
