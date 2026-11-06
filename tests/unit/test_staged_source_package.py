"""Staged source integrity only; these fixtures are not product runtime evidence."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'.github/stack-proof'))
spec=importlib.util.spec_from_file_location('staged_source_sealer',ROOT/'.github/stack-proof/seal_package.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
sha=lambda data:hashlib.sha256(data).hexdigest()


def archive(entries):
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w') as tar:
        for name,data in entries.items():
            member=tarfile.TarInfo(name);member.size=len(data);member.mode=0o644
            tar.addfile(member,io.BytesIO(data))
    return stream.getvalue()


@pytest.fixture
def staged(tmp_path):
    original={'Dockerfile':b'FROM fixture:base\n','deploy/stack/public.json':b'{"profile":"retained"}\n','public.py':b'print("public")\n'}
    current={**original,'Dockerfile':b'FROM fixture:base@sha256:' + b'a'*64 + b'\n','deploy/stack/public.json':b'{"profile":"candidate"}\n'}
    for name,data in current.items():
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    overlays={'deploy/stack/public.json':{'before':sha(original['deploy/stack/public.json']),'after':sha(current['deploy/stack/public.json'])}}
    build={'original_dockerfile_sha256':sha(original['Dockerfile']),'input_sha256':{'Dockerfile':sha(current['Dockerfile'])}}
    return tmp_path,archive(original),overlays,build,original,current


def test_archive_keeps_actual_staged_bytes_and_explicit_overlay_provenance(staged):
    root,canonical,overlays,build,original,current=staged
    raw,hashes,provenance=module.staged_source_archive(canonical,root,overlays,build)
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        assert {m.name:tar.extractfile(m).read() for m in tar if m.isfile()}==current
    assert hashes=={name:sha(data) for name,data in current.items()}
    assert provenance['canonicalArchiveSHA256']==sha(canonical)
    assert provenance['fileOverlays']['Dockerfile']=={'before':sha(original['Dockerfile']),'after':sha(current['Dockerfile'])}
    assert provenance['fileOverlays']['deploy/stack/public.json']==overlays['deploy/stack/public.json']
    assert 'unmodified' not in provenance['layout']


@pytest.mark.parametrize('damage',['unrecorded','wrong-before','wrong-after','unknown-overlay','symlink','missing'])
def test_unknown_or_unbound_staged_source_refuses(staged,damage):
    root,canonical,overlays,build,original,current=staged
    if damage=='unrecorded':(root/'public.py').write_text('changed')
    elif damage=='wrong-before':overlays['deploy/stack/public.json']['before']='0'*64
    elif damage=='wrong-after':overlays['deploy/stack/public.json']['after']='0'*64
    elif damage=='unknown-overlay':overlays['outside.py']={'before':'0'*64,'after':'1'*64}
    elif damage=='symlink':
        p=root/'public.py';p.rename(root/'public-original.py');p.symlink_to(root/'public-original.py')
    else:(root/'public.py').rename(root/'retained-public.py')
    with pytest.raises((ValueError,OSError)):
        module.staged_source_archive(canonical,root,overlays,build)


@pytest.fixture
def audited(tmp_path):
    for name,data in [('uv.lock',b'python lock'),('src/project_remedy/html_tools/package-lock.json',b'node lock')]:
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    for role,node in [('node22','v22.20.0'),('node24','v24.12.0')]:
        d=tmp_path/'.stack-proof-evidence/locked-audits'/role;d.mkdir(parents=True)
        payload={'npm-audit.json':json.dumps({'metadata':{'vulnerabilities':dict.fromkeys(['info','low','moderate','high','critical','total'],0)}}).encode(),
          'installed.json':json.dumps({'name':'synthetic-installed-tree'}).encode(),
          'public-api.json':json.dumps({'node':node,**dict.fromkeys(['assetIntegrity','finiteWalk','ordinaryPatterns','abortedWalkRejected','subsequentWalk'],True)}).encode(),
          'requirements.txt':b'fixture==1\n','python-audit.txt':b'No known vulnerabilities found\n'}
        for name,raw in payload.items():(d/name).write_bytes(raw)
        status={'serverSource':'a'*40,'nodeVersion':node,'verificationComplete':True,'npmAuditExit':0,'pythonAuditExit':0,
            'nodeLockSHA256':sha(b'node lock'),'pythonLockSHA256':sha(b'python lock'),'files':{name:sha(raw) for name,raw in payload.items()}}
        (d/'status.json').write_text(json.dumps(status))
    return tmp_path


def test_staged_audits_require_both_actual_source_and_lock_bound_records(audited):
    records=module.verify_staged_audits(audited,'a'*40)
    assert set(records)=={'node22','node24'}
    assert all(r['verificationComplete'] for r in records.values())


@pytest.mark.parametrize('damage',['missing','source','lock','audit-exit','vulnerable','incomplete','api','payload'])
def test_staged_audit_failure_refuses(audited,damage):
    d=audited/'.stack-proof-evidence/locked-audits/node24';p=d/'status.json';v=json.loads(p.read_text())
    if damage=='missing':p.rename(d/'retained-status.json')
    elif damage=='source':v['serverSource']='b'*40
    elif damage=='lock':v['nodeLockSHA256']='0'*64
    elif damage=='audit-exit':v['npmAuditExit']=1
    elif damage=='incomplete':v['verificationComplete']=False
    else:
        name={'vulnerable':'npm-audit.json','api':'public-api.json','payload':'installed.json'}[damage]
        data=json.loads((d/name).read_text())
        if damage=='vulnerable':data['metadata']['vulnerabilities']['moderate']=data['metadata']['vulnerabilities']['total']=1
        elif damage=='api':data['abortedWalkRejected']=False
        else:data['changed']=True
        (d/name).write_text(json.dumps(data))
        if damage!='payload':v['files'][name]=sha((d/name).read_bytes())
    if damage!='missing':p.write_text(json.dumps(v))
    with pytest.raises((ValueError,OSError)):
        module.verify_staged_audits(audited,'a'*40)
