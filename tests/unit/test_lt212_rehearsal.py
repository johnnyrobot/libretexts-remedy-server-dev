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
    for name in dict.fromkeys((*module().OVERLAY_FILES, 'deploy/stack/bundle.json', 'deploy/stack/conductor-candidates.json',
                 'deploy/stack/preflight.py', '.github/stack-proof/conductor_artifacts.py',
                 '.github/stack-proof/seal_package.py', 'uv.lock',
                 'src/project_remedy/html_tools/package-lock.json')):
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
    assert policy['bridgeSource'] == policy['rendererSource'] == '95a54dd3af850ca8eb5b8bf8be0395f0543c049e'
    assert policy['conductorCandidateIndexSHA256'] == '2e1297e9c180af7dce1f2e6894c6afffd0aff20ed71c3434dbccd36f14dc6e29'
    assert receipt['status'] == 'UNACCEPTED' and receipt['securityGate'] == 'CLEAN_LOCKED_AUDITS_REQUIRED'
    assert policy['deploymentReady'] is False and policy['productionWritesEnabled'] is False
    assert (ROOT / 'deploy/stack/bundle.json').read_bytes() == before
    assert (target / '.github/stack-proof/seal_package.py').read_bytes() == sealer


@pytest.mark.parametrize('damage', ['accepted', 'index', 'lock', 'verifier', 'script'])
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
    elif damage == 'script':
        p = target / '.github/stack-proof/full_proof.py'
        p.write_text(p.read_text() + '\n# changed source\n')
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


def test_renderer_uses_selected_stack_filter_with_distinct_producer_profile(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / '.github/stack-proof'))
    import renderer_rehearsal
    producer = tmp_path / 'producer/browser-scanner'
    producer.mkdir(parents=True)
    (producer / 'seccomp_profile.json').write_text('{"syntheticDistinctProducer":true}')
    selected, provenance = renderer_rehearsal.renderer_policy(ROOT, producer.parent)
    assert selected == ROOT / 'deploy/stack/renderer-seccomp-amd64.json'
    assert provenance['selectedSHA256'] == 'fcecf1a0ae6f84effa439b44d5f0e51bc25b4a975a7025c71e6f9ee0490ca7b0'
    assert provenance['producerSHA256'] != provenance['selectedSHA256']


def test_renderer_policy_mismatch_refuses(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / '.github/stack-proof'))
    import renderer_rehearsal
    directory = tmp_path / 'deploy/stack'
    directory.mkdir(parents=True)
    shutil.copyfile(ROOT / 'deploy/stack/bundle.json', directory / 'bundle.json')
    (directory / 'renderer-seccomp-amd64.json').write_text('{}')
    with pytest.raises(ValueError, match='filter changed'):
        renderer_rehearsal.renderer_policy(tmp_path, tmp_path / 'absent-producer')


def test_renderer_public_compose_uses_job_local_public_pem_trust(tmp_path):
    import yaml
    target = stage(tmp_path)
    module().prepare(target)
    renderer = yaml.safe_load((target / 'deploy/stack/compose.integration.yml').read_text())['services']['remedy-renderer']
    assert renderer['environment']['RENDER_PUBLIC_CA_FILE'] == '/run/remedy-public-ca/roots.pem'
    assert renderer['entrypoint'] == ['node', '/opt/remedy-bundle/secret-env.mjs', 'renderer']
    assert [item['source'] for item in renderer['configs']] == ['credential-loader']
    ca = next(item for item in renderer['volumes'] if item['target'] == '/run/remedy-public-ca/roots.pem')
    assert ca['read_only'] is True and ca['bind']['create_host_path'] is False
    assert ca['source'].endswith('/renderer/ca.pem')
    assert not any('nss-seed' in str(item) for item in renderer['volumes'])


def test_public_package_copy_uses_frozen_inventory_without_git_checkout(tmp_path, monkeypatch):
    import hashlib
    monkeypatch.syspath_prepend(str(ROOT / '.github/stack-proof'))
    import integration_compose_proof
    source = tmp_path / 'archived-source'
    shutil.copytree(ROOT / 'deploy/stack', source / 'deploy/stack', ignore=shutil.ignore_patterns('*.env','__pycache__'))
    hashes = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (source/'deploy/stack').rglob('*') if p.is_file()}
    (source/'.stack-artifacts').mkdir()
    (source/'.stack-artifacts/candidate.json').write_text(json.dumps({'configurationSha256': hashes}))
    work = tmp_path / 'work'; work.mkdir()
    package, observed = integration_compose_proof.prepare_package(source, work)
    assert observed['compose.integration.yml'] == hashes['deploy/stack/compose.integration.yml']
    assert (package/'env/renderer.env').is_file()


@pytest.mark.parametrize('damage', ['corrupt','extra','symlink'])
def test_public_package_refuses_unfrozen_or_replaced_source(tmp_path, monkeypatch, damage):
    import hashlib
    monkeypatch.syspath_prepend(str(ROOT / '.github/stack-proof'))
    import integration_compose_proof
    source=tmp_path/'source';(source/'deploy/stack').mkdir(parents=True)
    file=source/'deploy/stack/README.md';file.write_text('frozen public file')
    (source/'.stack-artifacts').mkdir()
    (source/'.stack-artifacts/candidate.json').write_text(json.dumps({'configurationSha256':{'deploy/stack/README.md':hashlib.sha256(file.read_bytes()).hexdigest()}}))
    if damage=='corrupt': file.write_text('changed')
    elif damage=='extra': (source/'deploy/stack/extra.env').write_text('must not be copied')
    else:
        file.rename(source/'original-public.md');file.symlink_to(source/'original-public.md')
    work=tmp_path/'work';work.mkdir()
    with pytest.raises(ValueError,match='public package'):
        integration_compose_proof.prepare_package(source,work)


@pytest.mark.parametrize('name', ['.github/stack-proof/full_proof.py', '.github/stack-proof/synthetic_signed_proof.py',
    'deploy/stack/preflight.py', 'deploy/stack/compose.integration.yml', 'deploy/stack/env/renderer.env.example',
    'deploy/stack/integration-profile.md'])
def test_retained_canonical_renderer_paths_remain_byte_identical_to_base(name):
    import hashlib
    expected = module().inputs()['sourceOverlay']['files'][name]['before']
    assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == expected


def test_staged_trust_paths_match_exact_reviewed_recipe_bindings(tmp_path):
    import hashlib
    target=stage(tmp_path)
    driver=module();receipt=driver.prepare(target)
    for name,binding in driver.inputs()['sourceOverlay']['files'].items():
        assert hashlib.sha256((target/name).read_bytes()).hexdigest()==binding['stagedAfter']
        assert receipt['overlays'][name]['before']==binding['before']
        assert receipt['overlays'][name]['after']==binding['stagedAfter']


def test_changed_source_overlay_refuses_before_stage_mutation(tmp_path,monkeypatch):
    driver=module();inputs=tmp_path/'inputs'
    shutil.copytree(driver.INPUTS,inputs)
    with (inputs/'renderer-trust.patch').open('ab') as stream:stream.write(b'changed')
    monkeypatch.setattr(driver,'INPUTS',inputs)
    target=stage(tmp_path);before=(target/'deploy/stack/bundle.json').read_bytes()
    with pytest.raises(ValueError,match='source overlay changed'):driver.prepare(target)
    assert (target/'deploy/stack/bundle.json').read_bytes()==before
    assert not (target/'UNACCEPTED-LT212.json').exists()


def test_source_overlay_isolated_from_parent_git_repository(tmp_path):
    import subprocess
    parent=tmp_path/'checkout';parent.mkdir()
    subprocess.run(['git','init','--quiet',str(parent)],check=True,capture_output=True)
    target=stage(parent)
    receipt=module().prepare(target)
    assert receipt['sourceOverlay']['sha256']==module().OVERLAY_SHA256
    assert not (parent/'.github').exists()
    assert not (parent/'.git/index').exists()


def test_recorded_build_source_is_materialized_without_registry_lookup(tmp_path):
    import hashlib
    source='FROM fixture:base AS base\nFROM base AS runtime\n'
    resolved='FROM fixture:base@sha256:'+'a'*64+' AS base\nFROM base AS runtime\n'
    (tmp_path/'Dockerfile').write_text(source)
    record={'original_dockerfile_sha256':hashlib.sha256(source.encode()).hexdigest(),
            'input_sha256':{'Dockerfile':hashlib.sha256(resolved.encode()).hexdigest()},
            'bases':{'fixture:base':'sha256:'+'a'*64}}
    result=module().materialize_recorded_build(tmp_path,record)
    assert (tmp_path/'Dockerfile').read_text()==resolved
    assert result=={'before':record['original_dockerfile_sha256'],'after':record['input_sha256']['Dockerfile']}


@pytest.mark.parametrize('damage',['source','base','result'])
def test_unknown_recorded_build_source_refuses(tmp_path,damage):
    import hashlib
    source='FROM fixture:base\n';(tmp_path/'Dockerfile').write_text(source)
    record={'original_dockerfile_sha256':hashlib.sha256(source.encode()).hexdigest(),
            'input_sha256':{'Dockerfile':'b'*64},'bases':{'fixture:base':'sha256:'+'a'*64}}
    if damage=='source':record['original_dockerfile_sha256']='0'*64
    elif damage=='base':record['bases']={}
    with pytest.raises(ValueError):module().materialize_recorded_build(tmp_path,record)
    assert (tmp_path/'Dockerfile').read_text()==source
