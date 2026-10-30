"""Private file loader at its actual command interface; synthetic credentials only."""
import json
import os
from pathlib import Path
import subprocess

SCRIPT=Path(__file__).resolve().parents[2]/'deploy/stack/secret-env.mjs'

def run(tmp_path,damage=None,command=('--check',)):
    env={'PATH':os.environ['PATH']}
    for field,value in [('APP_API_KEY','synthetic-app-key'),('OLLAMA_API_KEY','synthetic-provider-key')]:
        path=tmp_path/field;path.write_text(value+'\n');path.chmod(0o600)
        env[field+'_FILE']=str(path)
    if damage=='public': (tmp_path/'APP_API_KEY').chmod(0o644)
    elif damage=='ambiguous': env['APP_API_KEY']='conflicting-synthetic-key'
    elif damage=='multiline': (tmp_path/'APP_API_KEY').write_text('line1\nline2')
    elif damage=='service-format':
        path=tmp_path/'bad-service';path.write_text('not-a-service-key');path.chmod(0o600);env['REMEDY_BRIDGE_SERVICE_KEY_FILE']=str(path)
    elif damage=='symlink':
        link=tmp_path/'linked';link.symlink_to(tmp_path/'APP_API_KEY');env['APP_API_KEY_FILE']=str(link)
    return subprocess.run(['node',str(SCRIPT),'server',*command],env=env,text=True,capture_output=True,timeout=10)

def test_private_file_configuration_is_accepted_without_printing_values(tmp_path):
    result=run(tmp_path)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['credentialNames']==['APP_API_KEY','OLLAMA_API_KEY']
    assert 'synthetic-app-key' not in result.stdout+result.stderr

import pytest
@pytest.mark.parametrize('damage',['public','ambiguous','multiline','symlink','service-format'])
def test_invalid_credentials_refuse_before_starting_product(tmp_path,damage):
    marker=tmp_path/'started'
    result=run(tmp_path,damage,('node','-e',f"require('node:fs').writeFileSync({json.dumps(str(marker))},'started')"))
    assert result.returncode!=0
    assert result.stderr.strip()=='credential_configuration_invalid'
    assert not marker.exists()
    assert 'synthetic-app-key' not in result.stdout+result.stderr

def test_product_receives_exact_values_through_environment_only(tmp_path):
    result=run(tmp_path,command=('node','-e',"process.exit(process.env.APP_API_KEY==='synthetic-app-key'&&process.env.OLLAMA_API_KEY==='synthetic-provider-key'?0:1)"))
    assert result.returncode==0 and result.stdout=='' and result.stderr==''


def test_unaccepted_bundle_refuses_production_before_host_or_secret_access(tmp_path):
    import sys
    script=SCRIPT.with_name('preflight.py')
    result=subprocess.run([sys.executable,str(script),'--profile','engine','--production',
        '--artifacts',str(tmp_path/'absent-artifacts'),'--proof',str(tmp_path/'absent-proof'),
        '--state-root',str(tmp_path/'absent-state'),'--secret-root',str(tmp_path/'absent-secrets')],
        env={'PATH':''},capture_output=True,text=True,timeout=10)
    assert result.returncode==1
    body=json.loads(result.stdout)
    assert body['error']=='deployment_not_accepted_by_release_owner'
    assert body['deploymentReady'] is False and body['productionWritesEnabled'] is False
