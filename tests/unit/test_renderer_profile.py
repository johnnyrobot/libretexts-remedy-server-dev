"""The renderer's deployment filter keeps zero capabilities and known policy."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_renderer_chroot_filter_supports_the_nested_chromium_sandbox():
    renderer = json.loads((ROOT / 'deploy/stack/renderer-seccomp-amd64.json').read_text())
    scanner = json.loads((ROOT / 'deploy/stack/scanner-seccomp-amd64.json').read_text())
    renderer_rules = [rule for rule in renderer['syscalls'] if 'chroot' in rule['names']]
    scanner_rules = [rule for rule in scanner['syscalls'] if 'chroot' in rule['names']]
    assert renderer_rules == scanner_rules
    assert renderer_rules[0]['action'] == 'SCMP_ACT_ALLOW'
    assert not renderer_rules[0].get('includes')


def test_renderer_profile_preserves_every_other_reviewed_rule():
    import hashlib
    renderer_path = ROOT / 'deploy/stack/renderer-seccomp-amd64.json'
    renderer = json.loads(renderer_path.read_text())
    provenance = json.loads((ROOT / 'deploy/stack/renderer-profile-source.json').read_text())
    other_policy = {**renderer, 'syscalls': [r for r in renderer['syscalls'] if 'chroot' not in r['names']]}
    digest = hashlib.sha256(json.dumps(other_policy, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert digest == provenance['unchangedPolicySHA256']
    assert hashlib.sha256(renderer_path.read_bytes()).hexdigest() == provenance['profileSHA256']
    bundle = json.loads((ROOT / 'deploy/stack/bundle.json').read_text())
    assert bundle['rendererSeccompSHA256'] == provenance['profileSHA256']
