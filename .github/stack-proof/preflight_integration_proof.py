"""Run the public startup preflight on private resolved commissioning configs."""
import json
from pathlib import Path
import subprocess


def verify(root, work, evidence, contexts, conductor_imports, full_proof, sensitive_values):
    from evidence import write_product_log
    full_path=evidence/'full-result.json'
    full_path.write_text(json.dumps(full_proof,indent=2)+'\n')
    results=[]
    def each(items):
        for item in items:
            yield item
            yield from each(item.get('operational_contexts',[]))
    for number,context in enumerate(each(contexts)):
        config_path=Path(context['config_path'])
        config=json.loads(config_path.read_text())
        services=config['services'];bridge=services['remedy-bridge']['environment']
        consumer_env=services['conductor']['environment']
        actual_image=services['conductor']['image']
        selected=[target for target,pin in conductor_imports['targets'].items() if pin['loadedDockerImageID']==actual_image]
        assert len(selected)==1,'public config must select an original verified target'
        target=selected[0];mode=bridge['REMEDY_BRIDGE_PROFILE']
        assert mode in {'review-only','full-write'}
        arguments=['python3',str(root/'deploy/stack/preflight.py'),'--profile','integration',
            '--integration-mode',mode,'--artifacts',str(root/'.stack-artifacts'),
            '--proof',str(evidence/'result.json'),'--integration-proof',str(full_path),
            '--conductor-target',target,'--conductor-artifacts',str(root/'.stack-conductor'/target),
            '--compose-config',str(config_path),'--state-root',str(context['state_root']),
            '--secret-root',str(context['secret_root']),'--tls-root',str(context['tls_root']),
            '--nss-seed-root',str(context['nss_seed_root']),'--mongo-state-root',str(context['mongo_state_root']),
            '--renderer-seccomp',str(context['renderer_seccomp'])]
        if 'REMEDY_CLAIM_DB' in bridge:
            arguments+=['--history','--bridge-state-root',str(context['bridge_state_root']),
                '--fence-root',str(context['fence_root']),'--trust-epoch',bridge['REMEDY_REVIEWER_TRUST_EPOCH'],
                '--status-issuer',bridge['REMEDY_OPERATION_STATUS_ISSUER']]
        if 'REMEDY_REVIEWER_SIGNING_KEY_FILE' in consumer_env:
            names={'REMEDY_REVIEWER_SIGNING_KEY_FILE','REMEDY_REVIEWER_KEY_ID','REMEDY_REVIEWER_ISSUER',
                'REMEDY_REVIEWER_AUDIENCE','REMEDY_REVIEWER_KEY_ENABLED','REMEDY_REVIEWER_KEY_NOT_BEFORE','REMEDY_REVIEWER_KEY_NOT_AFTER'}
            private=work/('signing-preflight-'+str(number)+'.json')
            private.write_text(json.dumps({name:consumer_env[name] for name in names}));private.chmod(0o600)
            def source(role,destination):
                matches=[mount['source'] for mount in services[role]['volumes'] if mount['target']==destination]
                assert len(matches)==1
                return matches[0]
            arguments+=['--signing-config',str(private),'--keyring',source('remedy-bridge','/run/reviewer/keyring.json'),
                '--signing-key',source('conductor','/run/signing/private.pem')]
        process=subprocess.run(arguments,capture_output=True,text=True,timeout=900)
        name='public-preflight-'+target+'-'+str(number)
        write_product_log(evidence/(name+'.log'),process.stdout+process.stderr,sensitive_values)
        assert process.returncode==0,'public integration preflight failed: '+name
        result=json.loads(process.stdout)
        assert result['ok'] and result['startupCompatibility'] and result['writeReady'] is False and result['admission'] is False
        assert result['expectedBridgeReadyzStatus']==(503 if mode=='full-write' else 200)
        results.append({'target':target,'mode':mode,'checks':result})
    assert results,'actual public configuration preflight cases required'
    receipt={'verificationComplete':True,'cases':results,'deploymentReady':False,'productionWritesEnabled':False}
    (evidence/'public-integration-preflight-result.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt
