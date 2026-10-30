"""Bind OCI archive bytes to the filesystem/runtime config actually imported."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

RUNTIME_FIELDS = ('User','ExposedPorts','Env','Entrypoint','Cmd','Volumes','WorkingDir',
                  'Labels','StopSignal','Healthcheck','ArgsEscaped','Shell','OnBuild')


# Docker inspect can expose legacy container defaults absent from OCI configs.
# Only these explicit empty/false defaults are inert; future settings fail closed.
DOCKER_DEFAULTS = {'Hostname':'', 'Domainname':'', 'AttachStdin':False,
                   'AttachStdout':False, 'AttachStderr':False, 'Tty':False,
                   'OpenStdin':False, 'StdinOnce':False, 'Image':'',
                   'NetworkDisabled':False, 'MacAddress':'', 'StopTimeout':None}


def validate_runtime_fields(value):
    for key, field in value.items():
        if key not in RUNTIME_FIELDS and (key not in DOCKER_DEFAULTS or field != DOCKER_DEFAULTS[key]):
            raise ValueError('unsupported runtime configuration field: ' + key)
    health = value.get('Healthcheck')
    if health and set(health) - {'Test','Interval','Timeout','StartPeriod','StartInterval','Retries'}:
        raise ValueError('unsupported healthcheck configuration field')


def runtime_configuration(value):
    validate_runtime_fields(value)
    result={}
    for key in RUNTIME_FIELDS:
        field=value.get(key)
        if key=='Healthcheck' and field:
            field={name:field.get(name,[] if name=='Test' else 0)
                for name in ('Test','Interval','Timeout','StartPeriod','StartInterval','Retries')}
        elif key=='ArgsEscaped': field=bool(field)
        elif field in (None,'',[],{}): field=None
        result[key]=field
    return result


def read_oci(path):
    configurations=[];blob_count=0
    with tarfile.open(path,mode='r') as archive:
        for member in archive:
            if not member.isfile(): continue
            stream=archive.extractfile(member)
            digest=hashlib.file_digest(stream,'sha256').hexdigest()
            if member.name.startswith('blobs/sha256/'):
                assert member.name.split('/')[-1]==digest,'OCI blob digest mismatch'
                blob_count+=1
            if member.size<=2*1024*1024:
                raw=archive.extractfile(member).read()
                try: value=json.loads(raw)
                except (ValueError,UnicodeDecodeError): continue
                if isinstance(value,dict) and value.get('architecture')=='amd64' and value.get('os')=='linux' and value.get('rootfs',{}).get('type')=='layers':
                    configurations.append((digest,value))
    assert len(configurations)==1,'exactly one Linux amd64 image config required'
    digest,config=configurations[0]
    return digest,config,blob_count


def main():
    root=Path.cwd();artifacts=root/'.stack-artifacts';evidence=root/'.stack-proof-evidence'
    candidate=json.loads((artifacts/'candidate.json').read_text())
    assert candidate['serverSource']==os.environ['GITHUB_SHA']
    report={'serverSource':candidate['serverSource'],'images':{},'verificationComplete':False}
    for role in ('server','bridge','renderer'):
        path=artifacts/(role+'.oci.tar')
        with path.open('rb') as stream: assert hashlib.file_digest(stream,'sha256').hexdigest()==candidate['sha256'][path.name]
        digest,source,blobs=read_oci(path)
        assert set(source['config'])<=set(RUNTIME_FIELDS),'unsupported OCI runtime configuration fields'
        source_revision=candidate['serverSource'] if role=='server' else candidate['bridgeSource']
        assert source['config']['Labels']['org.opencontainers.image.revision']==source_revision
        loaded=json.loads(subprocess.check_output(['docker','image','inspect','remedy-'+role+':stack-candidate'],text=True))[0]
        assert loaded['Architecture']=='amd64' and loaded['Os']=='linux'
        assert loaded['RootFS']['Layers']==source['rootfs']['diff_ids'],'import changed filesystem layers'
        expected=runtime_configuration(source['config']);actual=runtime_configuration(loaded['Config'])
        assert expected==actual,'import changed runtime configuration: '+','.join(key for key in RUNTIME_FIELDS if expected[key]!=actual[key])
        runtime_hash=hashlib.sha256(json.dumps(actual,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        report['images'][role]={'sourceRevision':source_revision,'OCIArchiveSHA256':candidate['sha256'][path.name],
            'OCIConfigDigest':'sha256:'+digest,'loadedDockerImageID':loaded['Id'],
            'filesystemDiffIDs':loaded['RootFS']['Layers'],'runtimeConfigurationSHA256':runtime_hash,'OCIBlobsVerified':blobs}
    report['verificationComplete']=True
    (evidence/'imports.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__': main()
