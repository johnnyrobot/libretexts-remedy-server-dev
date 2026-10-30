"""Sealer integrity fixtures are not evidence of actual Linux stack acceptance."""
import importlib.util
import json
import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tarfile
import zipfile

import pytest


PROOF = Path(__file__).resolve().parents[2] / '.github/stack-proof'
sys.path.insert(0, str(PROOF))
SPEC = importlib.util.spec_from_file_location('seal_package', PROOF / 'seal_package.py')
sealer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sealer)


def test_missing_proofs_refused_without_creating_package(tmp_path):
    with pytest.raises(ValueError, match='missing required input'):
        sealer.seal(tmp_path)
    assert not (tmp_path / '.stack-package').exists()


def test_incomplete_receipt_refused_even_when_all_files_exist(tmp_path):
    evidence = tmp_path / '.stack-proof-evidence'
    evidence.mkdir()
    for name in sealer.RECEIPTS:
        (evidence / name).write_text(json.dumps({'verificationComplete': False}))
    with pytest.raises(ValueError, match='result.json: verificationComplete'):
        sealer.seal(tmp_path)
    assert not (tmp_path / '.stack-package').exists()


def put(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
    return path


def hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tar_bytes(entries):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as archive:
        for name, content in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return stream.getvalue()


def fake_image(root, name, revision, saved=False):
    layer = b'tiny fake fixture layer, never a runnable product'
    layer_digest = hashlib.sha256(layer).hexdigest()
    configuration = {'Labels': {'org.opencontainers.image.revision': revision}, 'User': '1000', 'Cmd': ['fixture']}
    config = {'architecture': 'amd64', 'os': 'linux', 'rootfs': {'type': 'layers', 'diff_ids': ['sha256:' + layer_digest]}, 'config': configuration}
    raw_config = json.dumps(config).encode()
    config_digest = hashlib.sha256(raw_config).hexdigest()
    descriptor = lambda raw, media: {'digest': 'sha256:' + hashlib.sha256(raw).hexdigest(), 'size': len(raw), 'mediaType': media}
    manifest = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                'config': descriptor(raw_config, 'application/vnd.oci.image.config.v1+json'),
                'layers': [descriptor(layer, 'application/vnd.oci.image.layer.v1.tar')]}
    raw_manifest = json.dumps(manifest).encode()
    manifest_digest = hashlib.sha256(raw_manifest).hexdigest()
    entries = {'oci-layout': b'{"imageLayoutVersion":"1.0.0"}',
               'index.json': json.dumps({'schemaVersion': 2, 'manifests': [descriptor(raw_manifest, manifest['mediaType'])]}).encode(),
               'blobs/sha256/' + config_digest: raw_config,
               'blobs/sha256/' + manifest_digest: raw_manifest,
               'blobs/sha256/' + layer_digest: layer}
    if saved:
        entries['manifest.json'] = json.dumps([{'Config': 'blobs/sha256/' + config_digest, 'Layers': ['blobs/sha256/' + layer_digest], 'RepoTags': ['fixture:' + revision]}]).encode()
    path = put(root, name, tar_bytes(entries))
    runtime_hash = hashlib.sha256(json.dumps(sealer.runtime_configuration(configuration), sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return path, {'sourceRevision': revision, 'OCIArchiveSHA256': hash_file(path),
                  'OCIConfigDigest': 'sha256:' + config_digest, 'loadedDockerImageID': 'sha256:' + config_digest,
                  'filesystemDiffIDs': ['sha256:' + layer_digest], 'runtimeConfigurationSHA256': runtime_hash,
                  'OCIBlobsVerified': 3}


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    """Tiny invented receipts test sealing only, never Linux acceptance."""
    root = tmp_path
    original = PROOF.parents[1]
    bundle = json.loads((original / 'deploy/stack/bundle.json').read_text())
    index = json.loads((original / 'deploy/stack/conductor-candidates.json').read_text())
    conductors = {}
    for pin in index['candidates']:
        target = pin['target']
        archive, image = fake_image(root, '.stack-conductor/' + target + '/fixture.tar', pin['sourceTree'], saved=True)
        zipped = root / '.stack-conductor' / target / 'original-artifact.zip'
        with zipfile.ZipFile(zipped, 'w') as stream:
            stream.write(archive, 'fixture.tar')
            stream.writestr('original-receipt.json', '{}')
        pin['validation'].update(archive='fixture.tar', archiveSHA256=hash_file(archive), imageID=image['OCIConfigDigest'], artifactDigest='sha256:' + hash_file(zipped))
        pin['validation']['artifactExpiresAt'] = '2099-11-12T00:00:00Z'
        source = sealer.verify_saved_image(archive, image['OCIConfigDigest'])
        loaded = {'Id': image['OCIConfigDigest'], 'Architecture': 'amd64', 'Os': 'linux', 'RootFS': {'Type': 'layers', 'Layers': image['filesystemDiffIDs']}, 'Config': source['runtimeConfiguration']}
        conductors[target] = {**source, **sealer.verify_loaded_image(source, loaded), 'baseCommit': pin['baseCommit'], 'sourceTree': pin['sourceTree'],
                              'artifactID': pin['validation']['artifactID'], 'ZIPDigest': pin['validation']['artifactDigest'], 'archiveSHA256': hash_file(archive)}
    index_path = put(root, 'deploy/stack/conductor-candidates.json', index)
    index_hash = hash_file(index_path)
    monkeypatch.setattr(sealer, 'INDEX_SHA256', index_hash)
    bundle['conductorCandidateIndexSHA256'] = index_hash
    put(root, 'deploy/stack/bundle.json', bundle)
    put(root, 'README.md', b'public fixture source')
    for name in ('verify_imports.py', 'conductor_artifacts.py'):
        put(root, '.github/stack-proof/' + name, (PROOF / name).read_bytes())
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    subprocess.run(['git', '-C', str(root), 'add', 'README.md', 'deploy', '.github'], check=True)
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'public fixture'], check=True)
    source = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    for name, value in {'GITHUB_SHA': source, 'GITHUB_RUN_ID': '12345', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_REPOSITORY': 'johnnyrobot/libretexts-remedy-server-dev'}.items():
        monkeypatch.setenv(name, value)
    images = {}
    for role in ('server', 'bridge', 'renderer'):
        _, images[role] = fake_image(root, '.stack-artifacts/' + role + '.oci.tar', source if role == 'server' else bundle['bridgeSource'])
    build = {role: {'bases': {'fixture:base': 'sha256:' + 'a' * 64}, 'input_sha256': {'Dockerfile': 'b' * 64, 'uv.lock' if role == 'server' else 'package-lock.json': 'd' * 64}, 'original_dockerfile_sha256': 'c' * 64} for role in images}
    put(root, '.stack-artifacts/build-inputs.json', build)
    configuration = {str(path.relative_to(root)): hash_file(path) for path in (root / 'deploy/stack').iterdir()}
    for name in ('verify_imports.py', 'conductor_artifacts.py'):
        configuration['.github/stack-proof/' + name] = hash_file(root / '.github/stack-proof' / name)
    metadata = {'serverSource': source, 'bridgeSource': bundle['bridgeSource'], 'deploymentReady': False, 'productionWritesEnabled': False, 'retentionDays': 30,
                'configurationSha256': configuration, 'sha256': {role + '.oci.tar': image['OCIArchiveSHA256'] for role, image in images.items()}}
    metadata['sha256']['build-inputs.json'] = hash_file(root / '.stack-artifacts/build-inputs.json')
    put(root, '.stack-artifacts/candidate.json', metadata)
    imports = {'serverSource': source, 'images': images, 'verificationComplete': True}
    receipts = {name: {'verificationComplete': True} for name in sealer.RECEIPTS}
    receipts['imports.json'] = imports
    receipts['conductor-imports.json'] = {'indexSHA256': index_hash, 'targets': conductors, 'verificationComplete': True}
    receipts['result.json'].update(serverSource=source, errors=[], importedArtifacts=imports, sections=['actual-service-bootstrap', 'private-isolation', 'sandbox-identities', 'limits-and-failures', 'bounded-storage', 'safe-shutdown', 'public-compose'],
                                  host={'kernel': 'fixture Linux', 'docker': 'fixture'}, resourceMeasurements={'fixture': True}, images={'scanner': {'repoDigests': [bundle['scannerImage']]}})
    receipts['compose-result.json']['profiles'] = {'engine-scanner': {'actualScan': True}, 'bridge-review': {'actualPreview': True, 'mutationDenied': True, 'externalMutations': 0}}
    receipts['preflight-result.json']['profiles'] = {profile: {'returncode': 0, 'result': {'ok': True}} for profile in ('engine', 'engine-scanner', 'bridge-review')}
    full = receipts['full-result.json']
    full.update(serverSource=source, conductorIndexSHA256=index_hash, externalMutations=0, targets={})
    public = receipts['public-integration-result.json']
    public.update(configurationHashes={str(path.relative_to(root / 'deploy/stack')): hash_file(path) for path in (root / 'deploy/stack').iterdir()}, targets={})
    synthetic = receipts['synthetic-signed-result.json']
    synthetic.update(serverSource=source, conductorIndexSHA256=index_hash, scenario='synthetic-test', targets={})
    preflight = receipts['public-integration-preflight-result.json']
    preflight['cases'] = []
    for target, pin in conductors.items():
        full['targets'][target] = {'artifact': pin, 'complete': True, 'phases': [
            *({'phase': phase, 'passed': True, 'compiledEntrypoint': True, 'realAuthenticationAndMongo': True, 'projectAuthorization': True, 'realScanPreview': True, 'realRenderedEvidence': True, 'productionMutationDenied': True} for phase in ('review', 'production-held')),
            {'passed': True, 'realCompiledUI': True, 'trustedTLS': True, 'browserManagedSecureCookie': True, 'productionMutationFalse': True},
            {'passed': True, 'actualBrowserSourceChange': True, 'changedSourceStalesManualEvidence': True, 'immutableReviewHistory': True, 'productionMutationFalse': True}]}
        operations = {'complete': True, 'originalsPreserved': True, 'currentClonedDataReusedForRollback': True, 'oldDataNeverRestoredAfterNewActivity': True, 'independentFenceNeverCopiedOrRestored': True,
                      'currentFenceMatchesReadonlySQLMeta': True, 'coldBackup': {'privateArchiveRetained': True}, 'coldClone': {'verifiedByActualCLI': True, 'admissionAuthorized': False, 'processCleanupCertified': False},
                      'negativeCases': {key: {'refusedBeforeWrites': True} for key in ('tamperedArchive', 'nonemptyTarget', 'newerOriginalState')},
                      'stages': [{'phase': phase, 'complete': True, 'externalMutations': 0, 'mutate': False, 'currentFenceUnchanged': True} for phase in ('restored-original', 'other-owned-binary', 'rollback-current-data')]}
        public['targets'][target] = {'complete': True, 'sourceTree': pin['sourceTree'], 'loadedDockerImageID': pin['loadedDockerImageID'], 'profiles': {
            mode: {'complete': True, 'externalMutations': 0, 'actualScannerAgainstTLSserver': True, 'consumer': {'passed': True}, **({'operations': operations} if mode == 'production-held' else {})} for mode in ('review', 'history', 'production-held')}}
        checkpoints = {
            'seed': ['synthetic_users_org_project_only'],
            'known': ['actual_signed_apply_rescan_history', 'actual_signed_restore_rescan_history', 'duplicate_local_confirmation_rejected_without_external_write'],
            'race': ['actual_pending_claim_blocks_concurrent_actions', 'actual_signed_apply_rescan_history', 'actual_signed_restore_rescan_history'],
            'terminal-lost-reply': ['actual_pending_unknown_or_lost_terminal_reply'],
            'unknown': ['actual_pending_unknown_or_lost_terminal_reply'],
            'status': ['readonly_historical_status_preserves_original_records'],
            'recover-refused': ['untrusted_or_unresolved_recovery_refused_claim_held'],
            'recover': ['actual_explicit_recovery_fresh_scan_immutable_history'],
        }
        phases = []
        recovered_unknown = False
        for phase, signed in [('seed', True), ('known', True), ('race', True), ('terminal-lost-reply', True), ('status', False), ('recover-refused', False), ('recover-refused', False), ('recover', False), ('status', False), ('unknown', True), ('recover-refused', True), ('status', False), ('recover', False), ('status', False)]:
            observed = [{'phase': phase, 'passed': True, 'checkpoint': name} for name in checkpoints[phase]]
            if phase in ('unknown', 'terminal-lost-reply'):
                observed[0].update(outcome='unknown_write' if phase == 'unknown' else 'known_success', externalWrites=1, auditRecorded=False, requiresReconciliation=phase == 'unknown')
            if phase == 'recover':
                observed[0].update(originalOutcome='unknown_write' if recovered_unknown else 'known_success', auditRecorded=False)
                recovered_unknown = True
            phases.append({'phase': phase, 'signerPresent': signed, 'checkpoints': observed})
        synthetic['targets'][target] = {'artifact': pin, 'complete': True, 'phases': phases,
            'offlineResolution': {'originalOutcome': 'unknown_write', 'reconciliation': 'resolved', 'exclusiveStoppedWriter': True, 'originalFieldsPreserved': True, 'remoteWrites': 0, 'currentIndependentFencePreserved': True, 'actualHelperImageID': images['bridge']['loadedDockerImageID']}}
        for mode in ('review-only', 'full-write'):
            preflight['cases'].append({'target': target, 'mode': mode, 'checks': {'ok': True, 'startupCompatibility': True, 'writeReady': False, 'admission': False}})
    full['publicIntegration'] = public
    full['publicIntegrationPreflight'] = preflight
    for name, receipt in receipts.items():
        put(root, '.stack-proof-evidence/' + name, receipt)
    return root


def test_seals_exact_bytes_and_source_with_readiness_held(candidate):
    package = sealer.seal(candidate, make_tar=True)
    manifest = json.loads((package / 'manifest.json').read_text())
    for flag in ('deploymentReady', 'productionWritesEnabled', 'liveProvidersVerified', 'productionSSOVerified', 'releaseOwnerAcceptance'):
        assert manifest[flag] is False
    assert manifest['source']['commit'] == subprocess.check_output(['git', '-C', str(candidate), 'rev-parse', 'HEAD'], text=True).strip()
    for name in ('server', 'bridge', 'renderer'):
        assert (package / 'images' / (name + '.oci.tar')).read_bytes() == (candidate / '.stack-artifacts' / (name + '.oci.tar')).read_bytes()
    with tarfile.open(package / 'package.tar') as archive:
        assert archive.extractfile('manifest.json').read() == (package / 'manifest.json').read_bytes()
        assert 'package.tar' not in archive.getnames()
    assert json.loads((package / 'seal-receipt.json').read_text())['manifestSHA256'] == hash_file(package / 'manifest.json')


def change_receipt(root, name, change):
    path = root / '.stack-proof-evidence' / name
    value = json.loads(path.read_bytes())
    change(value)
    put(root, '.stack-proof-evidence/' + name, value)
    aggregate_key = {'public-integration-result.json': 'publicIntegration', 'public-integration-preflight-result.json': 'publicIntegrationPreflight'}.get(name)
    if aggregate_key:
        change_receipt(root, 'full-result.json', lambda full: full.update({aggregate_key: value}))


@pytest.mark.parametrize(('receipt', 'change', 'reason'), [
    ('result.json', lambda value: value.update(verificationComplete=False), 'verificationComplete'),
    ('result.json', lambda value: value.update(errors=['actual failure']), 'errors'),
    ('result.json', lambda value: value.update(serverSource='0' * 40), 'serverSource mismatch'),
    ('conductor-imports.json', lambda value: value.update(indexSHA256='0' * 64), 'Conductor index mismatch'),
    ('full-result.json', lambda value: value.update(externalMutations=1), 'external mutation hold'),
    ('full-result.json', lambda value: next(iter(value['targets'].values()))['phases'].pop(), 'four actual full phases'),
    ('full-result.json', lambda value: next(iter(value['targets'].values()))['phases'][2].update(realCompiledUI=False), 'actual compiled UI missing'),
    ('public-integration-result.json', lambda value: next(iter(value['targets'].values()))['profiles']['production-held']['operations'].update(complete=False), 'actual operations'),
    ('public-integration-result.json', lambda value: next(iter(value['targets'].values()))['profiles']['production-held']['operations']['stages'].pop(), 'reopen/upgrade/rollback'),
    ('public-integration-preflight-result.json', lambda value: value.update(cases=[]), 'public preflight mode missing'),
    ('synthetic-signed-result.json', lambda value: value.update(scenario='production'), 'synthetic proof binding'),
    ('synthetic-signed-result.json', lambda value: next(iter(value['targets'].values()))['phases'].pop(), 'signer-free recovery order missing'),
    ('synthetic-signed-result.json', lambda value: next(iter(value['targets'].values()))['offlineResolution'].update(remoteWrites=1), 'offline unknown resolution'),
    ('synthetic-signed-result.json', lambda value: value.update(productionWritesEnabled=True), 'must remain false'),
])
def test_refuses_incomplete_mismatched_or_failed_gates(candidate, receipt, change, reason):
    change_receipt(candidate, receipt, change)
    with pytest.raises(ValueError, match=reason):
        sealer.seal(candidate)
    assert not (candidate / '.stack-package').exists()


@pytest.mark.parametrize('relative', ['.stack-artifacts/server.oci.tar', '.stack-artifacts/build-inputs.json', '.stack-conductor/release-2.156.2/fixture.tar', '.stack-conductor/release-2.156.2/original-artifact.zip'])
def test_refuses_tampered_original_bytes(candidate, relative):
    with (candidate / relative).open('ab') as stream:
        stream.write(b'tampered')
    with pytest.raises(ValueError, match='hash mismatch'):
        sealer.seal(candidate)
    assert not (candidate / '.stack-package').exists()


def test_refuses_wrong_candidate_source(candidate):
    metadata = json.loads((candidate / '.stack-artifacts/candidate.json').read_bytes())
    metadata['serverSource'] = '0' * 40
    put(candidate, '.stack-artifacts/candidate.json', metadata)
    with pytest.raises(ValueError, match='candidate source/policy: serverSource'):
        sealer.seal(candidate)


def test_refuses_changed_index_and_dirty_tracked_source(candidate):
    (candidate / 'deploy/stack/conductor-candidates.json').write_text('{}')
    with pytest.raises(ValueError, match='tracked source differs from HEAD'):
        sealer.seal(candidate)
    assert not (candidate / '.stack-package').exists()


def test_ignores_private_and_unknown_untracked_inputs(candidate):
    for name in ('.env', '.scratch/PRIVATE/key.pem', 'WORK/stores.sqlite', '.stack-proof-evidence/private.pem', '.stack-proof-evidence/raw-signed.log', '.stack-proof-evidence/unknown.json'):
        put(candidate, name, b'private fixture sentinel must never be copied')
    package = sealer.seal(candidate, make_tar=True)
    with tarfile.open(package / 'source.tar') as archive:
        assert set(archive.getnames()) == {'.github', '.github/stack-proof', '.github/stack-proof/conductor_artifacts.py', '.github/stack-proof/verify_imports.py', 'README.md', 'deploy', 'deploy/stack', 'deploy/stack/bundle.json', 'deploy/stack/conductor-candidates.json'}
    assert set(path.name for path in (package / 'evidence').iterdir()) == set(sealer.RECEIPTS)
    with tarfile.open(package / 'package.tar') as archive:
        assert all('private fixture sentinel' not in archive.extractfile(member).read().decode(errors='ignore') for member in archive if member.isfile())


def test_refuses_symlink_input_before_creating_package(candidate):
    path = candidate / '.stack-proof-evidence/imports.json'
    alternate = candidate / 'alternate.json'
    path.rename(alternate)
    path.symlink_to(alternate)
    with pytest.raises(ValueError, match='symlink input refused'):
        sealer.seal(candidate)
    assert not (candidate / '.stack-package').exists()


def test_refuses_existing_output_without_overwriting(candidate):
    output = candidate / '.stack-package'
    output.mkdir()
    witness = output / 'retained'
    witness.write_bytes(b'existing private work')
    with pytest.raises(ValueError, match='overwrite refused'):
        sealer.seal(candidate)
    assert witness.read_bytes() == b'existing private work'
    assert list(output.iterdir()) == [witness]


def test_refuses_git_sha_mismatch(candidate, monkeypatch):
    monkeypatch.setenv('GITHUB_SHA', '0' * 40)
    with pytest.raises(ValueError, match='GITHUB_SHA must match exact HEAD'):
        sealer.seal(candidate)


def test_refuses_synthetic_phase_shell_without_actual_checkpoint(candidate):
    change_receipt(candidate, 'synthetic-signed-result.json', lambda value: next(iter(value['targets'].values()))['phases'][1]['checkpoints'].clear())
    with pytest.raises(ValueError, match='actual synthetic checkpoints'):
        sealer.seal(candidate)


def test_refuses_synthetic_named_phases_with_only_generic_pass_markers(candidate):
    change_receipt(candidate, 'synthetic-signed-result.json', lambda value: next(iter(value['targets'].values()))['phases'][1].update(checkpoints=[{'phase': 'known', 'passed': True, 'checkpoint': 'phase_complete'}]))
    with pytest.raises(ValueError, match='synthetic checkpoint missing'):
        sealer.seal(candidate)


def test_refuses_recovery_without_observed_signer_absence(candidate):
    change_receipt(candidate, 'synthetic-signed-result.json', lambda value: next(iter(value['targets'].values()))['phases'][7].update(signerPresent=True))
    with pytest.raises(ValueError, match='signer-free recovery order missing'):
        sealer.seal(candidate)


def test_refuses_lost_reply_receipt_that_invents_audit_success(candidate):
    change_receipt(candidate, 'synthetic-signed-result.json', lambda value: next(iter(value['targets'].values()))['phases'][3]['checkpoints'][0].update(auditRecorded=True))
    with pytest.raises(ValueError, match='missing audit must remain false'):
        sealer.seal(candidate)


def test_refuses_unsafe_oci_paths_even_with_updated_outer_hash(candidate):
    archive = candidate / '.stack-artifacts/server.oci.tar'
    with tarfile.open(archive) as original:
        entries = {entry.name: original.extractfile(entry).read() for entry in original}
    entries['../private.pem'] = b'unsafe fixture'
    archive.write_bytes(tar_bytes(entries))
    metadata = json.loads((candidate / '.stack-artifacts/candidate.json').read_bytes())
    metadata['sha256']['server.oci.tar'] = hash_file(archive)
    put(candidate, '.stack-artifacts/candidate.json', metadata)
    with pytest.raises(ValueError, match='unsafe OCI archive entry'):
        sealer.seal(candidate)
    assert not (candidate / '.stack-package').exists()


def test_refuses_oci_descriptor_tampering_even_with_valid_outer_and_blob_hashes(candidate):
    archive = candidate / '.stack-artifacts/server.oci.tar'
    with tarfile.open(archive) as original:
        entries = {entry.name: original.extractfile(entry).read() for entry in original}
    index = json.loads(entries['index.json'])
    index['manifests'][0]['size'] += 1
    entries['index.json'] = json.dumps(index).encode()
    archive.write_bytes(tar_bytes(entries))
    metadata = json.loads((candidate / '.stack-artifacts/candidate.json').read_bytes())
    metadata['sha256']['server.oci.tar'] = hash_file(archive)
    put(candidate, '.stack-artifacts/candidate.json', metadata)
    with pytest.raises(ValueError, match='OCI descriptor size mismatch'):
        sealer.seal(candidate)


def test_refuses_missing_lock_pin(candidate):
    build = json.loads((candidate / '.stack-artifacts/build-inputs.json').read_bytes())
    del build['server']['input_sha256']['uv.lock']
    put(candidate, '.stack-artifacts/build-inputs.json', build)
    metadata = json.loads((candidate / '.stack-artifacts/candidate.json').read_bytes())
    metadata['sha256']['build-inputs.json'] = hash_file(candidate / '.stack-artifacts/build-inputs.json')
    put(candidate, '.stack-artifacts/candidate.json', metadata)
    with pytest.raises(ValueError, match='lock hashes missing'):
        sealer.seal(candidate)


def test_refuses_unreferenced_linux_config_that_cannot_be_loaded(candidate):
    archive = candidate / '.stack-artifacts/server.oci.tar'
    with tarfile.open(archive) as original:
        entries = {entry.name: original.extractfile(entry).read() for entry in original}
    index = json.loads(entries['index.json'])
    descriptor = index['manifests'][0]
    manifest = json.loads(entries['blobs/sha256/' + descriptor['digest'][7:]])
    replacement_config = b'{"architecture":"arm64","os":"linux"}'
    config_hash = hashlib.sha256(replacement_config).hexdigest()
    entries['blobs/sha256/' + config_hash] = replacement_config
    manifest['config'].update(digest='sha256:' + config_hash, size=len(replacement_config))
    raw_manifest = json.dumps(manifest).encode()
    manifest_hash = hashlib.sha256(raw_manifest).hexdigest()
    entries['blobs/sha256/' + manifest_hash] = raw_manifest
    descriptor.update(digest='sha256:' + manifest_hash, size=len(raw_manifest))
    entries['index.json'] = json.dumps(index).encode()
    archive.write_bytes(tar_bytes(entries))
    metadata = json.loads((candidate / '.stack-artifacts/candidate.json').read_bytes())
    metadata['sha256']['server.oci.tar'] = hash_file(archive)
    put(candidate, '.stack-artifacts/candidate.json', metadata)
    with pytest.raises(ValueError, match='selected OCI image config is not reachable'):
        sealer.seal(candidate)
