"""Draft source staging never changes released inputs or grants acceptance."""
import importlib.util
import json
from pathlib import Path
import shutil
import pytest

ROOT = Path(__file__).resolve().parents[2]


def module():
    spec = importlib.util.spec_from_file_location('lt212_rehearsal', ROOT / '.github/stack-proof/lt212_rehearsal.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def stage(tmp_path):
    destination = tmp_path / '.stack-inputs/server'
    for name in ('deploy/stack/bundle.json', 'deploy/stack/conductor-candidates.json',
                 'deploy/stack/preflight.py', '.github/stack-proof/conductor_artifacts.py',
                 '.github/stack-proof/seal_package.py', 'uv.lock',
                 'src/project_remedy/html_tools/package-lock.json'):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    return destination


def test_draft_stage_binds_reviewed_producers_without_changing_release_files(tmp_path):
    before = (ROOT / 'deploy/stack/bundle.json').read_bytes()
    target = stage(tmp_path)
    sealer = (target / '.github/stack-proof/seal_package.py').read_bytes()
    receipt = module().prepare(target)
    policy = json.loads((target / 'deploy/stack/bundle.json').read_text())
    assert policy['bridgeSource'] == policy['rendererSource'] == '98edbdcd63b76d0bc90ef864841fb39073ea7b6f'
    assert policy['conductorCandidateIndexSHA256'] == '8e85b978fe3c196756c4ca20c059c1a2bf64863e8162f065a3e935de912b1ed8'
    assert receipt['status'] == 'UNACCEPTED' and receipt['securityGate'] == 'LT227_UNMET'
    assert policy['deploymentReady'] is False and policy['productionWritesEnabled'] is False
    assert (ROOT / 'deploy/stack/bundle.json').read_bytes() == before
    assert (target / '.github/stack-proof/seal_package.py').read_bytes() == sealer


@pytest.mark.parametrize('damage', ['accepted', 'index', 'lock', 'verifier'])
def test_unknown_or_accepted_stage_refuses_before_overlay(tmp_path, damage):
    target = stage(tmp_path)
    if damage == 'accepted':
        p = target / 'deploy/stack/bundle.json'
        value = json.loads(p.read_text()); value['deploymentReady'] = True
        p.write_text(json.dumps(value))
    elif damage == 'index':
        (target / 'deploy/stack/conductor-candidates.json').write_text('{}')
    elif damage == 'lock':
        (target / 'src/project_remedy/html_tools/package-lock.json').write_text('{}')
    else:
        p = target / 'deploy/stack/preflight.py'
        p.write_text(p.read_text().replace(module().OLD_INDEX, '0' * 64))
    before = (target / 'deploy/stack/bundle.json').read_bytes()
    with pytest.raises(ValueError):
        module().prepare(target)
    assert (target / 'deploy/stack/bundle.json').read_bytes() == before
    assert not (target / 'UNACCEPTED-LT212.json').exists()


def test_canonical_checkout_and_reused_stage_refuse(tmp_path):
    with pytest.raises(ValueError, match='isolated'):
        module().prepare(ROOT)
    target = stage(tmp_path)
    module().prepare(target)
    with pytest.raises(ValueError, match='existing'):
        module().prepare(target)
