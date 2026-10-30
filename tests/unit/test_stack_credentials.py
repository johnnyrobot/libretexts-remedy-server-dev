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


def test_conductor_private_files_reach_unchanged_compiled_entrypoint(tmp_path):
    names=['SECRETKEY','MONGOOSEURI','REMEDY_API_KEY','OPENAI_API_KEY','STRIPE_SECRET_KEY','MAILGUN_API_KEY']
    env={'PATH':os.environ['PATH']}
    for name in names:
        path=tmp_path/name;path.write_text('synthetic-'+name+'\n');path.chmod(0o600)
        env[name+'_FILE']=str(path)
    result=subprocess.run(['node',str(SCRIPT),'conductor','node','-e',
        'process.exit('+json.dumps(names)+'.every(n=>process.env[n]===`synthetic-${n}`)?0:1)'],env=env,text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr
    assert result.stdout=='' and result.stderr==''


def bridge_env(tmp_path):
    env={'PATH':os.environ['PATH'],'RENDER_SCANNER_URL':'http://renderer.invalid:5180'}
    for name in ('SERVER_KEY','SERVER_SECRET','SERVER_USER'):
        path=tmp_path/name;path.write_text('synthetic-'+name);path.chmod(0o600);env[name+'_FILE']=str(path)
    return env


def test_configured_bridge_renderer_receives_protected_token_file(tmp_path):
    env=bridge_env(tmp_path)
    token=tmp_path/'renderer';token.write_text('synthetic-renderer-token');token.chmod(0o600)
    env['RENDER_SCANNER_TOKEN_FILE']=str(token)
    result=subprocess.run(['node',str(SCRIPT),'bridge','node','-e',
        "process.exit(process.env.RENDER_SCANNER_TOKEN==='synthetic-renderer-token'?0:1)"],env=env,capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
    assert 'synthetic-renderer-token' not in result.stdout+result.stderr


@pytest.mark.parametrize('damage',['missing','public','ambiguous'])
def test_bridge_renderer_credential_refusal_precedes_product_start(tmp_path,damage):
    env=bridge_env(tmp_path)
    token=tmp_path/'renderer';token.write_text('synthetic-renderer-token');token.chmod(0o600)
    if damage!='missing': env['RENDER_SCANNER_TOKEN_FILE']=str(token)
    if damage=='public': token.chmod(0o644)
    if damage=='ambiguous': env['RENDER_SCANNER_TOKEN']='synthetic-direct-token'
    marker=tmp_path/'started'
    result=subprocess.run(['node',str(SCRIPT),'bridge','node','-e',
        f"require('fs').writeFileSync({json.dumps(str(marker))},'started')"],env=env,capture_output=True,text=True,timeout=10)
    assert result.returncode!=0
    assert not marker.exists()
    assert result.stderr.strip()=='credential_configuration_invalid'
    assert 'synthetic-renderer-token' not in result.stdout+result.stderr


def test_bridge_wrapper_forwards_key_reload_without_terminating_product(tmp_path):
    import signal
    import time
    env=bridge_env(tmp_path);env.pop('RENDER_SCANNER_URL')
    ready=tmp_path/'ready';reloaded=tmp_path/'reloaded'
    code=("const fs=require('fs');process.on('SIGHUP',()=>fs.writeFileSync("+json.dumps(str(reloaded))+",'reloaded'));"
          "process.on('SIGTERM',()=>process.exit(0));fs.writeFileSync("+json.dumps(str(ready))+",'ready');"
          "setTimeout(()=>process.exit(0),2500);")
    product=subprocess.Popen(['node',str(SCRIPT),'bridge','node','-e',code],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        deadline=time.monotonic()+2
        while not ready.exists() and time.monotonic()<deadline:time.sleep(.01)
        assert ready.exists()
        product.send_signal(signal.SIGHUP)
        deadline=time.monotonic()+1
        while not reloaded.exists() and time.monotonic()<deadline:time.sleep(.01)
        assert reloaded.exists(),'configured Bridge key reload must reach the unchanged child'
        assert product.poll() is None
    finally:
        if product.poll() is None:product.terminate()
        product.communicate(timeout=4)
