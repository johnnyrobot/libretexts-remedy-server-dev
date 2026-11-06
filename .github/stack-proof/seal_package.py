"""Seal exact, already proved candidate bytes; never authorize deployment/writes.

No Docker, registry, credentials or network access. Trust comes from the reviewed
source and GitHub run, not from a hash pretending to be a signature. A failure
leaves any partial directory private and without an accepted manifest.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import zipfile

from conductor_artifacts import INDEX_SHA256, verify_saved_image, verify_loaded_image
from verify_imports import read_oci, runtime_configuration

RECEIPTS = ('result.json', 'compose-result.json', 'preflight-result.json',
            'imports.json', 'conductor-imports.json', 'full-result.json',
            'public-integration-result.json', 'public-integration-preflight-result.json',
            'synthetic-signed-result.json', 'conductor-imports-local.json')
FLAGS = ('deploymentReady', 'productionWritesEnabled', 'liveProvidersVerified',
         'productionSSOVerified', 'releaseOwnerAcceptance')
MONGO = 'mongo:7.0.14@sha256:0032d2ca20db5fa34926f196c8a43b74e34ed239a7f2453ff1505b6f12ba8ea6'
SCANNER = 'ghcr.io/johnnyrobot/adapt-a11y-scanner-dev-candidate@sha256:00ab363669ccc7ae50fe7fc79286508af5923d3326d397f87cff91ee76e379a6'
SECTIONS = {'actual-service-bootstrap', 'private-isolation', 'sandbox-identities',
            'limits-and-failures', 'bounded-storage', 'safe-shutdown', 'public-compose'}
HEX = re.compile(r'[a-f0-9]{64}')


def require(condition, gate):
    if not condition:
        raise ValueError(gate)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def safe_name(name):
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and '\\' not in name and all(part not in ('', '.', '..') for part in name.split('/'))


def input_file(root, name):
    require(safe_name(name), 'unsafe input path: ' + name)
    path = root / name
    require(not any(parent.is_symlink() for parent in (path, *path.parents) if parent != root.parent),
            'symlink input refused: ' + name)
    require(path.is_file(), 'missing required input: ' + name)
    return path


def get_json(root, name):
    value = json.loads(input_file(root, name).read_bytes())
    require(isinstance(value, dict), 'JSON object required: ' + name)
    return value


def matches(actual, expected, gate):
    for key, value in expected.items():
        valid = actual.get(key) is value if isinstance(value, bool) else actual.get(key) == value
        if isinstance(value, int) and not isinstance(value, bool):
            valid = valid and type(actual.get(key)) is int
        require(valid, gate + ': ' + key)


def verify_oci(path):
    """Verify every blob and reachable descriptor before shared config binding."""
    with tarfile.open(path, 'r') as archive:
        members = archive.getmembers()
        names = [member.name.rstrip('/') for member in members]
        require(len(names) == len(set(names)), 'duplicate OCI archive entry')
        require(all(safe_name(name) and (member.isfile() or member.isdir()) for name, member in zip(names, members)), 'unsafe OCI archive entry')
        by_name = {member.name: member for member in members}
        def load(name):
            require(name in by_name and by_name[name].isfile(), 'missing OCI blob: ' + name)
            require(by_name[name].size <= 16 * 1024 * 1024, 'oversized OCI metadata')
            return json.load(archive.extractfile(by_name[name]))
        require(load('oci-layout') == {'imageLayoutVersion': '1.0.0'}, 'unsupported OCI layout')
        visited = set()
        def walk(descriptor):
            identity = descriptor['digest']
            require(re.fullmatch(r'sha256:[a-f0-9]{64}', identity), 'unsupported OCI descriptor digest')
            name = 'blobs/sha256/' + identity[7:]
            require(name in by_name and by_name[name].size == descriptor['size'], 'OCI descriptor size mismatch')
            if name in visited:
                return
            visited.add(name)
            media = descriptor['mediaType']
            if media.endswith(('image.index.v1+json', 'manifest.list.v2+json')):
                value = load(name)
                require(value.get('schemaVersion') == 2, 'unsupported OCI index')
                for child in value['manifests']:
                    walk(child)
            elif media.endswith(('image.manifest.v1+json', 'manifest.v2+json')):
                value = load(name)
                require(value.get('schemaVersion') == 2, 'unsupported OCI manifest')
                walk(value['config'])
                for child in value['layers']:
                    walk(child)
        index = load('index.json')
        require(index.get('schemaVersion') == 2 and bool(index.get('manifests')), 'empty OCI index')
        for descriptor in index['manifests']:
            walk(descriptor)
    config_digest, config, count = read_oci(path)
    require('blobs/sha256/' + config_digest in visited, 'selected OCI image config is not reachable')
    return config_digest, config, count


def verify_signed_cold(cold, target, consumers, imports):
    """Require unresolved real signed history through the same cold clones."""
    require(isinstance(cold, dict), 'actual signed cold recovery proof required/' + target)
    matches(cold, {**{key: True for key in ('complete', 'publicColdCLI', 'unresolvedUnknownCaptured',
        'originalStoresRetained', 'currentFenceNeverRestored', 'unresolvedUnknownPreserved',
        'originalsRemainDisabled', 'currentFenceUnchanged', 'opaqueEpochUnchanged', 'explicitOfflineResolutionOnCurrentClone')},
        'fenceScope': 'capture-restore-and-read-only-binary-transitions',
        'remoteMutationRetries': 0, 'deploymentReady': False, 'productionWritesEnabled': False,
        'admissionAuthorized': False, 'processCleanupCertified': False}, 'actual signed cold/' + target)
    history, contents = cold['captureHistory'], cold['captureContents']
    office = cold.get('officeJob')
    require(isinstance(office, dict), 'actual Office job witness required/' + target)
    matches(office, {'postCount': 1, 'genuineDOCXParsed': True}, 'actual Office job/' + target)
    require(isinstance(office.get('jobID'), str) and re.fullmatch(r'[a-f0-9]{32}', office['jobID']) is not None and
        all(isinstance(office.get(key), str) and HEX.fullmatch(office[key]) for key in ('inputSHA256', 'outputSHA256')),
        'actual Office job identity and hashes required/' + target)
    require(isinstance(office.get('options'), dict) and set(office['options']) == {'allow_semantic_rebuild'} and
        office['options']['allow_semantic_rebuild'] is False, 'actual Office job original options required/' + target)
    require(type(contents.get('jobFiles')) is int and contents['jobFiles'] > 0, 'nonempty actual job bytes required/' + target)
    for field in ('operationRecords', 'intentRecords', 'knownOperations', 'unknownOperations', 'auditFalseOperations'):
        require(type(history.get(field)) is int and history[field] > 0, 'nonempty signed cold history/' + target + '/' + field)
    require(cold['operationRecords'] == history['operationRecords'], 'signed cold operation count/' + target)
    matches(history, {'passed': True, 'pendingUnknownHeld': True, 'refusedRecoveryStatus': 409,
        'authenticatedHistoryVerified': True, 'signerPresent': False, 'missingAuditPreserved': True,
        'verifiedCriteria': 0}, 'actual signed cold capture/' + target)
    for field in ('snapshotFiles', 'snapshotBytes', 'auditBytes'):
        require(type(contents.get(field)) is int and contents[field] > 0, 'nonempty signed cold content/' + target + '/' + field)
    digests = {**{key: cold[key] for key in ('archiveSHA256', 'manifestSHA256', 'currentFenceSHA256', 'opaqueEpochSHA256')},
        **{key: history[key] for key in ('journalSHA256', 'historySHA256', 'actorOutcomeSHA256', 'issuerNonceBindingsSHA256')},
        **{key: contents[key] for key in ('snapshotsSHA256', 'auditSHA256', 'jobTreeSHA256')}}
    require(all(isinstance(value, str) and HEX.fullmatch(value) for value in digests.values()), 'signed cold digests required/' + target)
    processes = cold['processes']
    require(set(processes) == {'server', 'bridge', 'renderer', 'scanner', 'mongo', 'conductor'}, 'six exact signed cold processes/' + target)
    for role, process in processes.items():
        require(re.fullmatch(r'[a-f0-9]{64}', process['id']) and re.fullmatch(r'sha256:[a-f0-9]{64}', process['image']), 'immutable signed cold process/' + role)
        if role in imports['images']:
            require(process['image'] == imports['images'][role]['loadedDockerImageID'], 'signed cold imported image/' + role)
    require(processes['conductor']['image'] == consumers[target]['loadedDockerImageID'], 'signed cold original consumer/' + target)
    require(set(cold['rawExitCodes']) == set(processes) and all(type(code) is int and code == (143 if role == 'server' else 0)
        for role, code in cold['rawExitCodes'].items()), 'signed cold graceful raw exits/' + target)
    stages = cold['stages']
    alternate = next(pin['loadedDockerImageID'] for name, pin in consumers.items() if name != target)
    require([(stage['stage'], stage['consumerImageID']) for stage in stages] == [
        ('cold-reopen', consumers[target]['loadedDockerImageID']), ('compatible-alternate-binary', alternate),
        ('rollback-on-current-data', consumers[target]['loadedDockerImageID'])], 'signed cold original binary transitions/' + target)
    for stage in stages:
        require(isinstance(stage.get('officeJobVerification'), dict), 'actual Office job restoration verification required/' + target)
        matches(stage['officeJobVerification'], {
            **{key: office[key] for key in ('jobID', 'inputSHA256', 'outputSHA256')},
            'genuineDOCXParsed': True, 'persistedOptionsUnchanged': True, 'postRepeated': False},
            'actual Office job restoration/' + target)
        matches(stage, {**{key: True for key in ('passed', 'reviewOnly', 'pendingUnknownHeld', 'authenticatedHistoryVerified',
            'actorOutcomeHashesUnchanged', 'issuerNonceBindingsUnchanged', 'originalsUnchanged', 'snapshotsUnchanged',
            'auditUnchanged', 'missingAuditPreserved', 'jobTreeUnchanged', 'currentFenceUnchanged', 'opaqueEpochUnchanged')},
            'signerPresent': False, 'remoteMutationRetries': 0, 'verifiedCriteria': 0,
            'operationRecords': history['operationRecords'], **{key: value for key, value in digests.items()
            if key in ('journalSHA256', 'historySHA256', 'actorOutcomeSHA256', 'snapshotsSHA256', 'auditSHA256', 'jobTreeSHA256', 'currentFenceSHA256')}},
            'actual signed cold stage/' + target)


def verify_receipts(receipts, source, index, imports):
    for name, value in receipts.items():
        require(value.get('verificationComplete') is True, name + ': verificationComplete is not true')
        for key in ('error', 'errors', 'shutdownErrors', 'counterError', 'integrationPreflightError', 'uiFailures'):
            require(not value.get(key), name + ': ' + key)
        if 'serverSource' in value:
            require(value['serverSource'] == source, name + ': serverSource mismatch')
        for flag in FLAGS:
            require(value.get(flag, False) is False, name + ': ' + flag + ' must remain false')
    old, full = receipts['result.json'], receipts['full-result.json']
    require(old.get('serverSource') == full.get('serverSource') == imports.get('serverSource') == source, 'all actual proof source bindings required')
    require(old['importedArtifacts'] == imports, 'private proof importedArtifacts mismatch')
    require(SECTIONS <= set(old['sections']), 'private proof missing required sections')
    require(bool(old.get('host')) and bool(old.get('resourceMeasurements')), 'host/runtime measurements required')
    require(SCANNER in old['images']['scanner']['repoDigests'], 'exact pulled Scanner digest required')
    require(full.get('conductorIndexSHA256') == index, 'full proof conductor index mismatch')
    require(full.get('externalMutations') == 0, 'full proof external mutation hold missing')
    for profile in ('engine', 'engine-scanner', 'bridge-review'):
        matches(receipts['preflight-result.json']['profiles'][profile], {'returncode': 0}, 'private preflight/' + profile)
        require(receipts['preflight-result.json']['profiles'][profile]['result'].get('ok') is True, 'private preflight failed/' + profile)
    compose = receipts['compose-result.json']['profiles']
    matches(compose['engine-scanner'], {'actualScan': True}, 'private compose scanner')
    matches(compose['bridge-review'], {'actualPreview': True, 'mutationDenied': True, 'externalMutations': 0}, 'private compose bridge')
    public = receipts['public-integration-result.json']
    preflight = receipts['public-integration-preflight-result.json']
    require(full.get('publicIntegration') == public, 'full publicIntegration receipt mismatch')
    require(full.get('publicIntegrationPreflight') == preflight, 'full publicIntegrationPreflight receipt mismatch')
    consumers = receipts['conductor-imports.json']['targets']
    require(receipts['conductor-imports-local.json'] == receipts['conductor-imports.json'], 'operator offline original import differs')
    require(set(full['targets']) == set(public['targets']) == set(consumers), 'both original target proofs required')
    for target, pin in consumers.items():
        actual = full['targets'][target]
        require(actual.get('complete') is True and actual.get('artifact') == pin, 'full original artifact binding/' + target)
        phases = actual['phases']
        require(len(phases) == 4 and all(item.get('passed') is True for item in phases), 'four actual full phases/' + target)
        for phase in ('review', 'production-held'):
            found = [item for item in phases if item.get('phase') == phase]
            require(len(found) == 1, 'full backend phase missing/' + target + '/' + phase)
            matches(found[0], {key: True for key in ('compiledEntrypoint', 'realAuthenticationAndMongo', 'projectAuthorization', 'realScanPreview', 'realRenderedEvidence', 'productionMutationDenied')}, 'full backend/' + target + '/' + phase)
        require(any(all(item.get(key) is True for key in ('realCompiledUI', 'trustedTLS', 'browserManagedSecureCookie', 'productionMutationFalse')) for item in phases), 'actual compiled UI missing/' + target)
        require(any(all(item.get(key) is True for key in ('actualBrowserSourceChange', 'changedSourceStalesManualEvidence', 'immutableReviewHistory', 'productionMutationFalse')) for item in phases), 'actual UI freshness missing/' + target)
        actual = public['targets'][target]
        matches(actual, {'complete': True, 'sourceTree': pin['sourceTree'], 'loadedDockerImageID': pin['loadedDockerImageID']}, 'public target/' + target)
        for mode in ('review', 'history', 'production-held'):
            profile = actual['profiles'][mode]
            matches(profile, {'complete': True, 'externalMutations': 0, 'actualScannerAgainstTLSserver': True}, 'public profile/' + target + '/' + mode)
            require(profile['consumer'].get('passed') is True, 'actual public compiled consumer/' + target + '/' + mode)
        operations = actual['profiles']['production-held']['operations']
        matches(operations, {key: True for key in ('complete', 'originalsPreserved', 'currentClonedDataReusedForRollback', 'oldDataNeverRestoredAfterNewActivity', 'independentFenceNeverCopiedOrRestored', 'currentFenceMatchesReadonlySQLMeta')}, 'actual operations/' + target)
        matches(operations['coldBackup'], {'privateArchiveRetained': True}, 'cold backup/' + target)
        matches(operations['coldClone'], {'verifiedByActualCLI': True, 'admissionAuthorized': False, 'processCleanupCertified': False}, 'cold clone/' + target)
        for negative in ('tamperedArchive', 'nonemptyTarget', 'newerOriginalState'):
            require(operations['negativeCases'][negative].get('refusedBeforeWrites') is True, 'cold refusal/' + target + '/' + negative)
        stages = operations['stages']
        require([stage.get('phase') for stage in stages] == ['restored-original', 'other-owned-binary', 'rollback-current-data'], 'cold reopen/upgrade/rollback stages/' + target)
        for stage in stages:
            matches(stage, {'complete': True, 'externalMutations': 0, 'mutate': False, 'currentFenceUnchanged': True}, 'actual operational stage/' + target)
        for mode in ('review-only', 'full-write'):
            cases = [case for case in preflight['cases'] if case.get('target') == target and case.get('mode') == mode]
            require(bool(cases), 'public preflight mode missing/' + target + '/' + mode)
            for case in cases:
                matches(case['checks'], {'ok': True, 'startupCompatibility': True, 'writeReady': False, 'admission': False}, 'public preflight/' + target + '/' + mode)
    signed = receipts['synthetic-signed-result.json']
    matches(signed, {'scenario': 'synthetic-test', 'serverSource': source, 'conductorIndexSHA256': index}, 'synthetic proof binding')
    require(set(signed['targets']) == set(consumers), 'both original synthetic target proofs required')
    for target, pin in consumers.items():
        actual = signed['targets'][target]
        require(actual.get('complete') is True and actual.get('artifact') == pin, 'synthetic original artifact binding/' + target)
        verify_signed_cold(actual.get('coldOperations'), target, consumers, imports)
        phases = actual['phases']
        require({'seed', 'known', 'race', 'terminal-lost-reply', 'status', 'recover-refused', 'recover', 'unknown'} <= {phase.get('phase') for phase in phases}, 'synthetic signed/recovery phases missing/' + target)
        sequence = [('seed', True), ('known', True), ('race', True), ('terminal-lost-reply', True),
                    ('status', False), ('recover-refused', False), ('recover-refused', False),
                    ('recover', False), ('status', False), ('unknown', True), ('recover-refused', True),
                    ('status', False), ('recover', False), ('status', False)]
        require(all(type(phase.get('signerPresent')) is bool for phase in phases) and
                [(phase.get('phase'), phase.get('signerPresent')) for phase in phases] == sequence,
                'actual signed/signer-free recovery order missing/' + target)
        required_checkpoints = {
            'seed': {'synthetic_users_org_project_only'},
            'known': {'actual_signed_apply_rescan_history', 'actual_signed_restore_rescan_history', 'duplicate_local_confirmation_rejected_without_external_write'},
            'race': {'actual_pending_claim_blocks_concurrent_actions', 'actual_signed_apply_rescan_history', 'actual_signed_restore_rescan_history'},
            'terminal-lost-reply': {'actual_pending_unknown_or_lost_terminal_reply'},
            'unknown': {'actual_pending_unknown_or_lost_terminal_reply'},
            'status': {'readonly_historical_status_preserves_original_records'},
            'recover-refused': {'untrusted_or_unresolved_recovery_refused_claim_held'},
            'recover': {'actual_explicit_recovery_fresh_scan_immutable_history'},
        }
        for phase in phases:
            require(bool(phase.get('checkpoints')) and all(check.get('passed') is True and check.get('phase') == phase['phase'] for check in phase['checkpoints']), 'actual synthetic checkpoints/' + target)
            names = {check.get('checkpoint') for check in phase['checkpoints']}
            require(required_checkpoints[phase['phase']] <= names, 'synthetic checkpoint missing/' + target + '/' + phase['phase'])
            if phase['phase'] in ('terminal-lost-reply', 'unknown'):
                checkpoint = next(check for check in phase['checkpoints'] if check['checkpoint'] == 'actual_pending_unknown_or_lost_terminal_reply')
                matches(checkpoint, {'outcome': 'known_success' if phase['phase'] == 'terminal-lost-reply' else 'unknown_write', 'externalWrites': 1}, 'actual lost-response outcome/' + target)
                if phase['phase'] == 'terminal-lost-reply':
                    require(checkpoint.get('auditRecorded') is False, 'actual missing audit must remain false/' + target)
                else:
                    require(checkpoint.get('requiresReconciliation') is True, 'unknown must require offline reconciliation/' + target)
        recoveries = [check for phase in phases if phase['phase'] == 'recover' for check in phase['checkpoints'] if check.get('checkpoint') == 'actual_explicit_recovery_fresh_scan_immutable_history']
        require({check.get('originalOutcome') for check in recoveries} == {'known_success', 'unknown_write'}, 'both actual explicit recovery outcomes required/' + target)
        require(any(check.get('originalOutcome') == 'known_success' and check.get('auditRecorded') is False for check in recoveries), 'recovery must preserve missing audit/' + target)
        matches(actual['offlineResolution'], {'originalOutcome': 'unknown_write', 'reconciliation': 'resolved', 'exclusiveStoppedWriter': True, 'originalFieldsPreserved': True, 'remoteWrites': 0, 'currentIndependentFencePreserved': True, 'actualHelperImageID': imports['images']['bridge']['loadedDockerImageID']}, 'actual offline unknown resolution/' + target)


def verify_staged_audits(root, source, *, evidence_prefix='.stack-proof-evidence/locked-audits/', lock_hashes=None):
    """Require both clean installed-graph audits bound to this source and lock."""
    records = {}
    if lock_hashes is None:
        lock_hashes = {'nodeLockSHA256':digest(input_file(root,'src/project_remedy/html_tools/package-lock.json')),
                       'pythonLockSHA256':digest(input_file(root,'uv.lock'))}
    names = {'npm-audit.json','installed.json','public-api.json','requirements.txt','python-audit.txt'}
    def bounded_json(name):
        path = input_file(root,name)
        require(0 < path.stat().st_size <= 16 * 1024**2, 'invalid audit metadata size')
        value = json.loads(path.read_bytes())
        require(isinstance(value,dict), 'audit metadata object required')
        return value
    for role, node in (('node22','v22.20.0'),('node24','v24.12.0')):
        prefix = evidence_prefix + role + '/'
        status = bounded_json(prefix + 'status.json')
        matches(status, {'serverSource':source,'nodeVersion':node,'verificationComplete':True,
                         'npmAuditExit':0,'pythonAuditExit':0,
                         **lock_hashes}, 'locked audits/' + role)
        require(set(status['files']) == names, 'exact audit evidence inventory required/' + role)
        for name, expected in status['files'].items():
            path = input_file(root,prefix + name)
            require(path.stat().st_size <= 16 * 1024**2 and isinstance(expected,str) and HEX.fullmatch(expected) and
                    digest(path) == expected, 'audit payload mismatch/' + role + '/' + name)
        audit = bounded_json(prefix + 'npm-audit.json')
        require('error' not in audit, 'npm audit unavailable/' + role)
        matches(audit['metadata']['vulnerabilities'], dict.fromkeys(('info','low','moderate','high','critical','total'),0),
                'npm audit must be clean/' + role)
        api = bounded_json(prefix + 'public-api.json')
        matches(api, {'node':node,**dict.fromkeys(('assetIntegrity','finiteWalk','ordinaryPatterns',
                     'abortedWalkRejected','subsequentWalk'),True)}, 'actual dependency API/' + role)
        records[role] = status
    return records


def staged_source_archive(canonical, root, overlays, server_build):
    """Archive the tested stage, binding every change to its canonical bytes."""
    require(len(canonical) <= 64 * 1024**2, 'canonical source archive too large')
    require(isinstance(overlays, dict), 'staged file overlays required')
    changes = dict(overlays)
    require('Dockerfile' not in changes, 'Dockerfile must use resolved build binding')
    changes['Dockerfile'] = {'before': server_build['original_dockerfile_sha256'],
                             'after': server_build['input_sha256']['Dockerfile']}
    for name, binding in changes.items():
        require(safe_name(name) and isinstance(binding, dict) and set(binding) == {'before','after'} and
                all(isinstance(value,str) and HEX.fullmatch(value) for value in binding.values()),
                'invalid staged source binding')
    stream, hashes, before, used = io.BytesIO(), {}, {}, set()
    with tarfile.open(fileobj=io.BytesIO(canonical), mode='r:') as original, tarfile.open(fileobj=stream, mode='w:') as result:
        names = set()
        for member in original:
            name = member.name.rstrip('/')
            require(safe_name(name) and name not in names and (member.isdir() or member.isfile()), 'unsafe canonical source member')
            names.add(name)
            if member.isdir():
                header = tarfile.TarInfo(name);header.type = tarfile.DIRTYPE;header.mode = member.mode
                result.addfile(header)
                continue
            require(member.size <= 16 * 1024**2, 'canonical source file too large')
            old = original.extractfile(member).read()
            old_hash = hashlib.sha256(old).hexdigest()
            path = input_file(root, name)
            require(path.stat().st_size <= 16 * 1024**2, 'staged source file too large')
            raw = path.read_bytes(); new_hash = hashlib.sha256(raw).hexdigest()
            if name in changes:
                require(changes[name] == {'before':old_hash,'after':new_hash}, 'staged source overlay mismatch: ' + name)
                used.add(name)
            else:
                require(new_hash == old_hash, 'unrecorded staged source change: ' + name)
            hashes[name], before[name] = new_hash, old_hash
            header = tarfile.TarInfo(name);header.mode = member.mode;header.size = len(raw)
            result.addfile(header, io.BytesIO(raw))
    require(used == set(changes), 'source overlay is not a canonical tracked file')
    raw = stream.getvalue()
    require(len(raw) <= 64 * 1024**2, 'staged source archive too large')
    return raw, hashes, {'layout':'canonical-git-archive-with-recorded-staging-overlays',
                         'canonicalArchiveSHA256':hashlib.sha256(canonical).hexdigest(),
                         'canonicalFileSHA256':before, 'fileOverlays':changes}


def seal(root, output=None, make_tar=False, *, staged_checkout=None):
    """Validate all inputs, then create one private, non-overwriting handoff."""
    try:
        return _seal(Path(root).resolve(), output, make_tar,
                     Path(staged_checkout).resolve() if staged_checkout is not None else None)
    except (KeyError, TypeError, AssertionError, json.JSONDecodeError, tarfile.TarError, zipfile.BadZipFile) as error:
        raise ValueError('invalid or missing candidate gate: ' + str(error)) from error


def _seal(root, output, make_tar, staged_checkout):
    receipts = {}
    files = {}
    def add(name, destination):
        path = input_file(root, name)
        files[destination] = (path, digest(path))
        return path
    for name in RECEIPTS:
        path = add('.stack-proof-evidence/' + name, 'evidence/' + name)
        receipts[name] = json.loads(path.read_bytes())
        require(receipts[name].get('verificationComplete') is True, name + ': verificationComplete is not true')
    output = Path(output) if output is not None else root / '.stack-package'
    if not output.is_absolute():
        output = root / output
    require(output.parent == root and output.name.startswith('.stack-package'), 'output must be a new .stack-package directory directly inside checkout')
    require(not output.exists() and not output.is_symlink(), 'output already exists; overwrite refused')
    checkout = staged_checkout if staged_checkout is not None else root
    def git(*args):
        return subprocess.check_output(['git', '-C', str(checkout), *args])
    source = git('rev-parse', 'HEAD').decode().strip()
    require(re.fullmatch(r'[a-f0-9]{40}', source) and os.environ.get('GITHUB_SHA') == source, 'GITHUB_SHA must match exact HEAD')
    require(not git('status', '--porcelain', '--untracked-files=no').strip(), 'tracked source differs from HEAD')
    repository = os.environ.get('GITHUB_REPOSITORY', '')
    run_id, attempt = os.environ.get('GITHUB_RUN_ID', ''), os.environ.get('GITHUB_RUN_ATTEMPT', '')
    require(repository == 'johnnyrobot/libretexts-remedy-server-dev' and run_id.isdigit() and attempt.isdigit(), 'reviewed repository/run binding required')
    candidate = get_json(root, '.stack-artifacts/candidate.json')
    bundle = get_json(root, 'deploy/stack/bundle.json')
    index_path = input_file(root, 'deploy/stack/conductor-candidates.json')
    index = get_json(root, 'deploy/stack/conductor-candidates.json')
    require(digest(index_path) == INDEX_SHA256 == bundle['conductorCandidateIndexSHA256'], 'authoritative current-candidates index changed')
    matches(candidate, {'serverSource': source, 'bridgeSource': bundle['bridgeSource'], 'retentionDays': 30, 'deploymentReady': False, 'productionWritesEnabled': False}, 'candidate source/policy')
    matches(bundle, {'deploymentReady': False, 'productionWritesEnabled': False, 'scannerImage': SCANNER, 'scannerSource': '1541bb8f3962553b65dab7bfd5aeb429354a8a4f'}, 'bundle fixed policy')
    tracked = git('ls-files', '-z').decode().rstrip('\0').split('\0')
    require(all(safe_name(name) and not any(part == '.git' or part == '.scratch' or part.startswith('.stack-') or part == '.env' for part in PurePosixPath(name).parts) for name in tracked), 'private/generated tracked source refused')
    config_names = {name for name in tracked if name.startswith('deploy/stack/') and Path(name).suffix in {'.py', '.mjs', '.json', '.yml', '.example', '.md', '.sh'}}
    config_names |= {'.github/stack-proof/verify_imports.py', '.github/stack-proof/conductor_artifacts.py'}
    require(config_names <= set(candidate['configurationSha256']), 'candidate configuration hash coverage incomplete')
    for name, expected in candidate['configurationSha256'].items():
        require(name in tracked and digest(input_file(root, name)) == expected, 'candidate configuration hash mismatch: ' + name)
    for name in ('candidate.json', 'build-inputs.json'):
        path = add('.stack-artifacts/' + name, 'metadata/' + name)
        if name != 'candidate.json':
            require(digest(path) == candidate['sha256'][name], 'build inputs hash mismatch')
    build = get_json(root, '.stack-artifacts/build-inputs.json')
    require(set(build) == {'server', 'bridge', 'renderer'}, 'all resolved build inputs required')
    for role, record in build.items():
        require(bool(record['bases']) and all(re.fullmatch(r'sha256:[a-f0-9]{64}', value) for value in record['bases'].values()), 'unpinned build base/' + role)
        require(bool(record['input_sha256']) and all(HEX.fullmatch(value) for value in record['input_sha256'].values()) and HEX.fullmatch(record['original_dockerfile_sha256']), 'invalid build input hashes/' + role)
        lock_name = 'uv.lock' if role == 'server' else 'package-lock.json'
        require(any(PurePosixPath(name).name == lock_name for name in record['input_sha256']), 'lock hashes missing/' + role)
    staging = None
    locked_audits = None
    if staged_checkout is not None:
        require(root == checkout / '.stack-inputs/server', 'explicit staged checkout layout required')
        require(INDEX_SHA256 == '2e1297e9c180af7dce1f2e6894c6afffd0aff20ed71c3434dbccd36f14dc6e29', 'reviewed 36-patch staged index required')
        matches(bundle, {'bridgeSource':'95a54dd3af850ca8eb5b8bf8be0395f0543c049e',
                         'rendererSource':'95a54dd3af850ca8eb5b8bf8be0395f0543c049e',
                         'conductorMetadataSource':'617187fd7993714ae4d6fb939b30268fb7be6eee'}, 'reviewed staged producer recipe')
        staging_path = add('UNACCEPTED-LT212.json', 'metadata/staging.json')
        staging = json.loads(staging_path.read_bytes())
        matches(staging, {'status':'UNACCEPTED','cleanSealPermitted':False,'canonicalInputsModified':False,
                          'indexSHA256':INDEX_SHA256,'bridgeSource':bundle['bridgeSource'],
                          'conductorSource':bundle['conductorMetadataSource']}, 'explicit staged source')
        flags = staging.get('globalFlags')
        require(isinstance(flags,dict) and set(flags) == set(FLAGS) and all(value is False for value in flags.values()),
                'staged release flags must remain false')
        recipe = get_json(checkout,'.github/stack-proof/lt212-inputs/inputs.json')
        require(staging.get('sourceOverlay') == recipe['sourceOverlay'], 'source overlay recipe differs from reviewed checkout')
        expected_names = set(recipe['sourceOverlay']['files']) | {'deploy/stack/bundle.json',
            'deploy/stack/conductor-candidates.json','.github/stack-proof/conductor_artifacts.py'}
        require(set(staging['overlays']) == expected_names, 'exact staged source overlay inventory required')
        for name, binding in recipe['sourceOverlay']['files'].items():
            require(staging['overlays'][name] == {'before':binding['before'],'after':binding['stagedAfter']},
                    'staged source recipe binding differs: ' + name)
        require(digest(staging_path) == candidate['sha256']['rehearsal-inputs.json'], 'staging receipt differs from built source')
        locked_audits = verify_staged_audits(root, source)
        for role, status in locked_audits.items():
            for name in ('status.json', *sorted(status['files'])):
                add('.stack-proof-evidence/locked-audits/' + role + '/' + name,
                    'evidence/locked-audits/' + role + '/' + name)
    imports = receipts['imports.json']
    require(set(imports['images']) == {'server', 'bridge', 'renderer'}, 'all imported owned images required')
    for role in ('server', 'bridge', 'renderer'):
        name = role + '.oci.tar'
        path = add('.stack-artifacts/' + name, 'images/' + name)
        require(digest(path) == candidate['sha256'][name], 'candidate OCI archive hash mismatch/' + role)
        config_digest, config, count = verify_oci(path)
        revision = source if role == 'server' else bundle['bridgeSource']
        require(config['config']['Labels']['org.opencontainers.image.revision'] == revision, 'OCI source revision mismatch/' + role)
        runtime_hash = hashlib.sha256(json.dumps(runtime_configuration(config['config']), sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        matches(imports['images'][role], {'sourceRevision': revision, 'OCIArchiveSHA256': digest(path), 'OCIConfigDigest': 'sha256:' + config_digest, 'filesystemDiffIDs': config['rootfs']['diff_ids'], 'runtimeConfigurationSHA256': runtime_hash, 'OCIBlobsVerified': count}, 'import identity/' + role)
        require(re.fullmatch(r'sha256:[a-f0-9]{64}', imports['images'][role]['loadedDockerImageID']), 'immutable imported image required/' + role)
    consumers = receipts['conductor-imports.json']
    require(consumers['indexSHA256'] == INDEX_SHA256, 'imported Conductor index mismatch')
    pins = {pin['target']: pin for pin in index['candidates']}
    require(len(pins) == 2 and set(pins) == set(consumers['targets']), 'both frozen Conductor targets required')
    for target, pin in pins.items():
        count = 36 if staging is not None else 32
        require(safe_name(target) and len(PurePosixPath(target).parts) == 1 and len(pin['patches']) == count, 'unsupported original Conductor patch count')
        validation = pin['validation']
        expiry = datetime.fromisoformat(validation['artifactExpiresAt'].replace('Z', '+00:00'))
        require(expiry.tzinfo is not None and expiry > datetime.now(timezone.utc), 'original Conductor artifact expired before sealing/' + target)
        archive = add('.stack-conductor/' + target + '/' + validation['archive'], 'conductor/' + target + '/' + validation['archive'])
        zipped = add('.stack-conductor/' + target + '/original-artifact.zip', 'conductor/' + target + '/original-artifact.zip')
        require(digest(archive) == validation['archiveSHA256'], 'original Conductor archive hash mismatch/' + target)
        require('sha256:' + digest(zipped) == validation['artifactDigest'], 'original Conductor ZIP hash mismatch/' + target)
        with zipfile.ZipFile(zipped) as original:
            entries = [entry for entry in original.infolist() if PurePosixPath(entry.filename).name == validation['archive']]
            require(len(entries) == 1, 'one original ZIP image payload required/' + target)
            with original.open(entries[0]) as stream:
                require(hashlib.file_digest(stream, 'sha256').hexdigest() == validation['archiveSHA256'], 'ZIP payload differs from original archive/' + target)
        original = verify_saved_image(archive, validation['imageID'])
        actual = consumers['targets'][target]
        require(original['runtimeConfiguration'].get('Labels', {}).get('org.opencontainers.image.revision') == pin['sourceTree'], 'original Conductor source label mismatch/' + target)
        loaded = {'Id': actual['loadedDockerImageID'], 'Architecture': 'amd64', 'Os': 'linux', 'RootFS': {'Type': 'layers', 'Layers': actual['filesystemDiffIDs']}, 'Config': actual['inspectConfiguration']}
        matches(actual, {**original, **verify_loaded_image(original, loaded), 'baseCommit': pin['baseCommit'], 'sourceTree': pin['sourceTree'], 'artifactID': validation['artifactID'], 'ZIPDigest': validation['artifactDigest'], 'archiveSHA256': validation['archiveSHA256']}, 'original Conductor import mapping/' + target)
    verify_receipts(receipts, source, INDEX_SHA256, imports)
    # Every copied public package config hash must still describe this source.
    for name, expected in receipts['public-integration-result.json']['configurationHashes'].items():
        require(digest(input_file(root, 'deploy/stack/' + name)) == expected, 'public configuration hash mismatch: ' + name)
    source_bytes = git('archive', '--format=tar', source)
    source_hashes = {}
    with tarfile.open(fileobj=io.BytesIO(source_bytes), mode='r:') as archive:
        for entry in archive:
            require(safe_name(entry.name.rstrip('/')) and (entry.isfile() or entry.isdir()), 'unsafe tracked source entry')
            if entry.isfile():
                source_hashes[entry.name] = hashlib.sha256(archive.extractfile(entry).read()).hexdigest()
    require(set(source_hashes) == set(tracked), 'git archive omitted tracked source')
    source_provenance = {}
    canonical_bytes = None
    if staging is not None:
        canonical_bytes = source_bytes
        source_bytes, source_hashes, source_provenance = staged_source_archive(
            canonical_bytes, root, staging['overlays'], build['server'])
    # Optional saved registry archives use explicit names only. Absence retains
    # digest references; presence must independently bind to those same refs.
    registry = {'scanner': {'reference': SCANNER, 'source': bundle['scannerSource']}, 'mongo': {'reference': MONGO}}
    for role, value in registry.items():
        name = '.stack-artifacts/' + role + '.oci.tar'
        if (root / name).exists() or (root / name).is_symlink():
            path = add(name, 'images/' + role + '.oci.tar')
            verify_oci(path)
            with tarfile.open(path, 'r') as archive:
                index_value = json.load(archive.extractfile('index.json'))
                require(any(item['digest'] == value['reference'].split('@')[1] for item in index_value['manifests']), 'saved registry archive digest mismatch/' + role)
            value['archive'] = 'images/' + role + '.oci.tar'
    now = datetime.now(timezone.utc)
    manifest = {'schema': 'remedy-stack-handoff-v1', **{flag: False for flag in FLAGS},
                'classification': 'implementation-candidate/tested-synthetic-Linux-profile',
                'scopeVerified': {'privateActualProfile': True, 'exactCompiledTargetsAndUIFreshness': True, 'publicComposeAndColdOperations': True, 'publicIntegrationPreflight': True, 'syntheticSignedTestAndExplicitRecovery': True},
                'unverified': ['vendor revision-atomic conditional writes', 'production SSO', 'live external providers', 'actual target host/storage/network', 'production rollout', 'release owner acceptance'],
                'trust': 'SHA256 checks integrity, not signatures or independent authenticity; trust the reviewed source and GitHub run.',
                'source': {'commit': source, 'archive': 'source.tar', 'fileSHA256': source_hashes, **source_provenance},
                'run': {'repository': repository, 'id': run_id, 'attempt': attempt, 'url': 'https://github.com/' + repository + '/actions/runs/' + run_id + '/attempts/' + attempt},
                'retention': {'newArtifactsDays': 30, 'sealedAt': now.isoformat(), 'newArtifactsExpireAt': (now + timedelta(days=30)).isoformat(), 'originalConductor': {target: pin['validation']['artifactExpiresAt'] for target, pin in pins.items()}, 'policy': 'Retain this complete package with its hashes before workflow artifact expiry; never rebuild/substitute missing original archives.'},
                'buildInputs': build, 'configurationSHA256': candidate['configurationSha256'],
                'conductorMetadataSource': bundle['conductorMetadataSource'], 'conductorIndexSHA256': INDEX_SHA256,
                'conductor': {target: {'index': pin, 'import': consumers['targets'][target]} for target, pin in pins.items()},
                'registryImages': registry, 'imports': imports, 'limits': bundle['limits'],
                'hostRuntimeMeasurementsReceipt': 'evidence/result.json',
                'fullRuntimeMeasurementsReceipt': 'evidence/full-result.json',
                'payloadSHA256': {name: expected for name, (_, expected) in files.items()}}
    manifest['payloadSHA256']['source.tar'] = hashlib.sha256(source_bytes).hexdigest()
    if canonical_bytes is not None:
        manifest.update(status='UNACCEPTED', stagedSource=True)
        manifest['lockedAudits'] = locked_audits
        manifest['source']['canonicalArchive'] = 'canonical-source.tar'
        manifest['payloadSHA256']['canonical-source.tar'] = hashlib.sha256(canonical_bytes).hexdigest()
    manifest_raw = json_bytes(manifest)
    output.mkdir(mode=0o700)
    for destination, (path, expected) in sorted(files.items()):
        target = output / destination
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open('rb') as incoming, target.open('xb') as outgoing:
            shutil.copyfileobj(incoming, outgoing)
        require(digest(target) == expected, 'input changed while sealing: ' + destination)
    (output / 'source.tar').write_bytes(source_bytes)
    if canonical_bytes is not None:
        (output / 'canonical-source.tar').write_bytes(canonical_bytes)
    checksum_raw = ''.join(value + '  ' + name + '\n' for name, value in sorted(manifest['payloadSHA256'].items())).encode()
    (output / 'checksums.sha256').write_bytes(checksum_raw)
    receipt = {'schema': 'remedy-stack-seal-receipt-v1', 'manifestSHA256': hashlib.sha256(manifest_raw).hexdigest(), 'checksumsSHA256': hashlib.sha256(checksum_raw).hexdigest()}
    if make_tar:
        with tarfile.open(output / 'package.tar', mode='x:') as archive:
            for name in sorted([*manifest['payloadSHA256'], 'checksums.sha256', 'manifest.json']):
                raw = manifest_raw if name == 'manifest.json' else None
                info = tarfile.TarInfo(name)
                info.mode, info.mtime, info.uid, info.gid = 0o600, 0, 0, 0
                info.size = len(raw) if raw is not None else (output / name).stat().st_size
                if raw is not None:
                    archive.addfile(info, io.BytesIO(raw))
                else:
                    with (output / name).open('rb') as stream:
                        archive.addfile(info, stream)
        receipt['packageTARSHA256'] = digest(output / 'package.tar')
    (output / 'seal-receipt.json').write_bytes(json_bytes(receipt))
    # This last exclusive create is the publication marker. Partial failures
    # cannot be confused with a completed, accepted candidate handoff.
    with (output / 'manifest.json').open('xb') as stream:
        stream.write(manifest_raw)
    return output


def verify_package(directory, expected_manifest_sha256):
    """Read-only candidate integrity verification; grants no runtime authority."""
    root = Path(directory).resolve()
    require(isinstance(expected_manifest_sha256,str) and HEX.fullmatch(expected_manifest_sha256), 'trusted manifest SHA256 required')
    manifest_path = input_file(root,'manifest.json')
    require(manifest_path.stat().st_size <= 16 * 1024**2 and digest(manifest_path) == expected_manifest_sha256,
            'manifest differs from trusted receipt')
    manifest = get_json(root,'manifest.json')
    require(manifest.get('schema') == 'remedy-stack-handoff-v1', 'unsupported package schema')
    matches(manifest, dict.fromkeys(FLAGS,False), 'unaccepted candidate flags')
    payloads = manifest['payloadSHA256']
    require(isinstance(payloads,dict) and 0 < len(payloads) <= 10000, 'bounded package inventory required')
    total = 0
    for name, expected in payloads.items():
        path = input_file(root,name)
        total += path.stat().st_size
        require(total <= 8 * 1024**3 and isinstance(expected,str) and HEX.fullmatch(expected) and digest(path) == expected,
                'package payload mismatch: ' + name)
    checksums = ''.join(value + '  ' + name + '\n' for name,value in sorted(payloads.items())).encode()
    require(input_file(root,'checksums.sha256').read_bytes() == checksums, 'package checksums inventory differs')
    seal_receipt = get_json(root,'seal-receipt.json')
    matches(seal_receipt, {'schema':'remedy-stack-seal-receipt-v1', 'manifestSHA256':expected_manifest_sha256,
                          'checksumsSHA256':hashlib.sha256(checksums).hexdigest()}, 'seal receipt')
    source = manifest['source']
    def source_hashes(name):
        path = input_file(root,name)
        require(path.stat().st_size <= 64 * 1024**2, 'source archive too large')
        hashes, names = {}, set()
        with tarfile.open(path,mode='r:') as tar:
            for member in tar:
                name = member.name.rstrip('/')
                require(safe_name(name) and name not in names and len(names) < 10000 and
                        (member.isfile() or member.isdir()), 'unsafe source member')
                require(not any(part in {'.git','.scratch','.env'} or part.startswith('.stack-') for part in PurePosixPath(name).parts),
                        'private source member refused')
                names.add(name)
                if member.isfile():
                    require(member.size <= 16 * 1024**2, 'source member too large')
                    hashes[name] = hashlib.file_digest(tar.extractfile(member),'sha256').hexdigest()
        return hashes
    actual_source = source_hashes(source['archive'])
    require(actual_source == source['fileSHA256'], 'source file inventory mismatch')
    if manifest.get('stagedSource') is True:
        matches(manifest, {'status':'UNACCEPTED'}, 'staged candidate status')
        require(source.get('layout') == 'canonical-git-archive-with-recorded-staging-overlays', 'explicit staged source layout required')
        before = source_hashes(source['canonicalArchive'])
        require(before == source['canonicalFileSHA256'] and set(before) == set(actual_source), 'canonical source inventory differs')
        require(digest(input_file(root,source['canonicalArchive'])) == source['canonicalArchiveSHA256'], 'canonical archive binding differs')
        changes = source['fileOverlays']
        require(isinstance(changes,dict) and set(changes) <= set(before), 'source overlay inventory invalid')
        for name in before:
            if name in changes:
                require(changes[name] == {'before':before[name],'after':actual_source[name]}, 'source overlay binding mismatch')
            else:
                require(before[name] == actual_source[name], 'unrecorded source overlay')
        audited = verify_staged_audits(root,source['commit'],evidence_prefix='evidence/locked-audits/',
            lock_hashes={'nodeLockSHA256':actual_source['src/project_remedy/html_tools/package-lock.json'],
                         'pythonLockSHA256':actual_source['uv.lock']})
        require(manifest.get('lockedAudits') == audited, 'packaged audit bindings differ')
    receipts = {name:get_json(root,'evidence/' + name) for name in RECEIPTS}
    imports = manifest['imports']
    verify_receipts(receipts,source['commit'],manifest['conductorIndexSHA256'],imports)
    for role in ('server','bridge','renderer'):
        path = input_file(root,'images/' + role + '.oci.tar')
        config_digest, config, count = verify_oci(path)
        runtime_hash = hashlib.sha256(json.dumps(runtime_configuration(config['config']),sort_keys=True,separators=(',',':')).encode()).hexdigest()
        binding = imports['images'][role]
        require(config['config']['Labels']['org.opencontainers.image.revision'] == binding['sourceRevision'], 'packaged image source mismatch')
        matches(binding, {'OCIArchiveSHA256':digest(path),'OCIConfigDigest':'sha256:' + config_digest,
                         'filesystemDiffIDs':config['rootfs']['diff_ids'],'runtimeConfigurationSHA256':runtime_hash,
                         'OCIBlobsVerified':count}, 'packaged OCI binding/' + role)
    for target, record in manifest['conductor'].items():
        pin = record['index'];validation = pin['validation']
        archive = input_file(root,'conductor/' + target + '/' + validation['archive'])
        zipped = input_file(root,'conductor/' + target + '/original-artifact.zip')
        require(digest(archive) == validation['archiveSHA256'] and 'sha256:' + digest(zipped) == validation['artifactDigest'], 'packaged original Conductor bytes differ')
        original = verify_saved_image(archive,validation['imageID'])
        actual = record['import']
        require(original['runtimeConfiguration']['Labels']['org.opencontainers.image.revision'] == pin['sourceTree'], 'packaged Conductor source differs')
        matches(actual, original, 'packaged Conductor import mapping')
    tar_verified = False
    if (root/'package.tar').exists() or (root/'package.tar').is_symlink():
        path = input_file(root,'package.tar')
        require(path.stat().st_size <= 8 * 1024**3 and digest(path) == seal_receipt.get('packageTARSHA256'), 'package TAR hash mismatch')
        expected = {**payloads,'manifest.json':expected_manifest_sha256,'checksums.sha256':hashlib.sha256(checksums).hexdigest()}
        seen = set()
        with tarfile.open(path,mode='r:') as tar:
            for member in tar:
                require(member.isfile() and member.name in expected and member.name not in seen and
                        member.size == input_file(root,member.name).stat().st_size, 'package TAR inventory differs')
                require(hashlib.file_digest(tar.extractfile(member),'sha256').hexdigest() == expected[member.name], 'package TAR payload differs')
                seen.add(member.name)
        require(seen == set(expected), 'package TAR incomplete')
        tar_verified = True
    return {'verificationComplete':True,'manifestSHA256':expected_manifest_sha256,'source':source['commit'],
            'packageTarVerified':tar_verified, **dict.fromkeys(FLAGS,False)}


def unpack_candidate(directory, destination, expected_manifest_sha256, expected_tar_sha256):
    """Verify the uploaded wrapper, then expand into a new private directory."""
    root, destination = Path(directory).resolve(), Path(destination).absolute()
    require(not destination.exists() and not destination.is_symlink(), 'unpack destination already exists')
    require(isinstance(expected_manifest_sha256,str) and HEX.fullmatch(expected_manifest_sha256) and
            isinstance(expected_tar_sha256,str) and HEX.fullmatch(expected_tar_sha256), 'trusted candidate digests required')
    manifest_path, archive = input_file(root,'manifest.json'), input_file(root,'package.tar')
    require(manifest_path.stat().st_size <= 16 * 1024**2 and digest(manifest_path) == expected_manifest_sha256,
            'unpack manifest binding differs')
    require(archive.stat().st_size <= 8 * 1024**3 and digest(archive) == expected_tar_sha256, 'unpack TAR binding differs')
    raw_manifest = manifest_path.read_bytes();manifest = json.loads(raw_manifest)
    require(manifest.get('schema') == 'remedy-stack-handoff-v1', 'unsupported unpack schema')
    matches(manifest,dict.fromkeys(FLAGS,False),'unaccepted unpack flags')
    payloads = manifest['payloadSHA256']
    require(isinstance(payloads,dict) and 0 < len(payloads) <= 10000 and
            all(safe_name(name) and isinstance(value,str) and HEX.fullmatch(value) for name,value in payloads.items()),
            'invalid unpack inventory')
    checksum = ''.join(value + '  ' + name + '\n' for name,value in sorted(payloads.items())).encode()
    wrapper_checksums = input_file(root,'checksums.sha256')
    require(wrapper_checksums.stat().st_size <= 16 * 1024**2 and wrapper_checksums.read_bytes() == checksum,
            'unpack wrapper checksums differ')
    expected = {**payloads,'manifest.json':expected_manifest_sha256,'checksums.sha256':hashlib.sha256(checksum).hexdigest()}
    receipt = get_json(root,'seal-receipt.json')
    matches(receipt,{'schema':'remedy-stack-seal-receipt-v1','manifestSHA256':expected_manifest_sha256,'packageTARSHA256':expected_tar_sha256,
                     'checksumsSHA256':hashlib.sha256(checksum).hexdigest()},'unpack receipt')
    seen, total = set(), 0
    with tarfile.open(archive,mode='r:') as tar:
        for member in tar:
            total += member.size
            require(member.isfile() and member.name in expected and member.name not in seen and total <= 8 * 1024**3,
                    'unsafe or oversized unpack member')
            require(hashlib.file_digest(tar.extractfile(member),'sha256').hexdigest() == expected[member.name], 'unpack payload digest differs')
            seen.add(member.name)
    require(seen == set(expected), 'unpack archive incomplete')
    destination.mkdir(mode=0o700)
    with tarfile.open(archive,mode='r:') as tar:
        for member in tar:
            if member.name == 'manifest.json':
                continue  # publication marker is last, after every copy is proved
            require(member.isfile() and member.name in expected and safe_name(member.name), 'unpack archive changed')
            target = destination/member.name
            target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            with target.open('xb') as outgoing:
                shutil.copyfileobj(tar.extractfile(member),outgoing)
            require(digest(target) == expected[member.name], 'unpack copy changed')
    require(digest(archive) == expected_tar_sha256, 'unpack archive changed during copy')
    (destination/'seal-receipt.json').write_bytes(json_bytes(receipt))
    with (destination/'manifest.json').open('xb') as outgoing:
        outgoing.write(raw_manifest)
    return {'verificationComplete':True,'packageTarVerified':True,'manifestSHA256':expected_manifest_sha256,
            'packageTARSHA256':expected_tar_sha256, **dict.fromkeys(FLAGS,False)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--output', type=Path)
    parser.add_argument('--tar', action='store_true', help='also create deterministic uncompressed package.tar')
    parser.add_argument('--staged-checkout', type=Path, help='explicit canonical checkout for a recorded, unaccepted LT212 stage')
    parser.add_argument('--verify', type=Path, help='read-only verification of an existing candidate directory')
    parser.add_argument('--expected-manifest-sha', help='manifest digest obtained from the trusted source/run receipt')
    parser.add_argument('--unpack', type=Path, help='verify a candidate wrapper and expand it to a new output directory')
    parser.add_argument('--expected-tar-sha', help='package TAR digest from the trusted source/run receipt')
    args = parser.parse_args()
    try:
        if args.unpack is not None:
            require(args.output is not None and args.verify is None and not args.tar and args.staged_checkout is None,
                    'unpack requires only a new output directory and trusted digests')
            print(json.dumps(unpack_candidate(args.unpack,args.output,args.expected_manifest_sha,args.expected_tar_sha)))
            return
        if args.verify is not None:
            require(args.output is None and not args.tar and args.staged_checkout is None and args.expected_tar_sha is None, 'verification cannot create a package')
            print(json.dumps(verify_package(args.verify,args.expected_manifest_sha)))
            return
        require(args.expected_manifest_sha is None and args.expected_tar_sha is None, 'expected digest requires verification mode')
        package = seal(args.root, args.output, args.tar, staged_checkout=args.staged_checkout)
    except (ValueError, OSError, KeyError, TypeError, tarfile.TarError, zipfile.BadZipFile) as error:
        parser.exit(1, 'Candidate sealing refused: ' + str(error) + '\n')
    print(json.dumps({'package': str(package), 'deploymentReady': False, 'productionWritesEnabled': False}))


if __name__ == '__main__':
    main()
