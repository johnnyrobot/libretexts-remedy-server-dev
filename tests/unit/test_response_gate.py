"""TLS transport oracle only; no product server, signer or stack acceptance."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def tls(tmp_path):
    if not shutil.which("node") or not shutil.which("openssl"):
        pytest.skip("Node and OpenSSL required for the pure TLS transport seam")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
                    "-addext", "basicConstraints=critical,CA:TRUE", "-keyout", str(tmp_path / "key.pem"),
                    "-out", str(tmp_path / "cert.pem")], check=True, capture_output=True, timeout=15)
    return tmp_path


def test_transport_forwards_exact_bytes_once_and_only_drops_completed_success(tls):
    # The oracle deliberately returns literal bytes, never owned-service shapes
    # beyond the minimal marker needed to select the transport fault.
    program = r"""
import https from 'node:https';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {createResponseGate} from './.github/stack-proof/response_gate.mjs';
const dir=process.argv[1],key=fs.readFileSync(dir+'/key.pem'),cert=fs.readFileSync(dir+'/cert.pem');
const servers=[],received=[];
const listen=server=>new Promise(resolve=>server.listen(0,'localhost',()=>{servers.push(server);resolve(server.address().port);}));
const upstream=https.createServer({key,cert},async(req,res)=>{
  const chunks=[];for await(const chunk of req)chunks.push(chunk);
  received.push({method:req.method,path:req.url,headers:req.headers,body:Buffer.concat(chunks)});
  if(req.url==='/redirect'){res.writeHead(307,{Location:'/must-not-follow'});res.end('literal redirect');return;}
  if(req.url==='/large'){res.end('x'.repeat(65));return;}
  const data=req.headers['x-oracle-outcome']==='unknown'?Buffer.from('{"outcome":"unknown_write"}'):
    req.url==='/v1/cxone/page/apply-fix'?Buffer.from('{"outcome":"known_success", "opaque":"π"}\n'):Buffer.from([0,255,13,10,7]);
  res.writeHead(200,{'Content-Type':'application/octet-stream','X-Opaque-Header':'value','Content-Length':data.length});
  // An early dropped downstream would violate the completed-reply condition.
  res.write(data.subarray(0,2));setTimeout(()=>res.end(data.subarray(2)),20);
});
let gate;
try{
  const port=await listen(upstream);
  gate=createResponseGate({key,cert,ca:cert,target:'https://localhost:'+port,controlToken:'fixture-control',requestBytes:64,responseBytes:64,deadlineMS:1000});
  const gatePort=await listen(gate);
  const request=(method,path,body=Buffer.alloc(0),headers={})=>new Promise((resolve,reject)=>{
    const req=https.request({hostname:'localhost',port:gatePort,ca:cert,method,path,headers:{'Content-Length':body.length,...headers},agent:false},res=>{
      const chunks=[];res.on('data',chunk=>chunks.push(chunk));res.on('end',()=>resolve({status:res.statusCode,headers:res.headers,body:Buffer.concat(chunks)}));res.on('error',reject);
    });req.on('error',reject);req.end(body);
  });
  const opaque=Buffer.from([0,255,10,65]);
  const first=await request('POST','/opaque?exact=%2F',opaque,{'X-API-Key':'fake-opaque-key','X-Other':'retain'});
  assert.equal(first.status,200);assert.deepEqual(first.body,Buffer.from([0,255,13,10,7]));assert.equal(first.headers['x-opaque-header'],'value');
  assert.equal(received[0].path,'/opaque?exact=%2F');assert.deepEqual(received[0].body,opaque);assert.equal(received[0].headers['x-api-key'],'fake-opaque-key');
  const redirected=await request('GET','/redirect');assert.equal(redirected.status,307);assert.equal(redirected.headers.location,'/must-not-follow');
  assert.equal(received.length,2);
  assert.equal((await request('POST','/control/drop-next-apply-reply')).status,401);
  assert.equal((await request('POST','/control/drop-next-apply-reply',Buffer.from('{}'),{'X-Fixture-Control':'fixture-control'})).status,200);
  const unknown=await request('POST','/v1/cxone/page/apply-fix',opaque,{'X-Oracle-Outcome':'unknown'});
  assert.equal(unknown.status,200);assert.equal(JSON.parse(unknown.body).outcome,'unknown_write');
  const before=received.length;
  await assert.rejects(request('POST','/v1/cxone/page/apply-fix',opaque));
  assert.equal(received.length,before+1,'the lost response never causes a retry');
  const meta=JSON.parse((await request('GET','/control/status',undefined,{'X-Fixture-Control':'fixture-control'})).body);
  assert.equal(meta.dropped,1);assert.equal(meta.armed,false);assert.equal(meta.completed,4);
  assert.equal(JSON.stringify(meta).includes('fake-opaque-key'),false);
  assert.equal((await request('POST','/too-large',Buffer.alloc(65))).status,413);
  const count=received.length;assert.equal(count,4);
  await assert.rejects(request('GET','/large'));assert.equal(received.length,count+1);
}finally{for(const server of servers.reverse()){server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}}
console.log('transport-oracle-passed');
"""
    result = subprocess.run(["node", "--input-type=module", "-e", program, str(tls)], cwd=ROOT,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "transport-oracle-passed"


def test_gate_refuses_untrusted_upstream_tls_without_retry(tls):
    program = r"""
import https from 'node:https';import fs from 'node:fs';import assert from 'node:assert/strict';
import {createResponseGate} from './.github/stack-proof/response_gate.mjs';
const dir=process.argv[1],key=fs.readFileSync(dir+'/key.pem'),cert=fs.readFileSync(dir+'/cert.pem');
let requests=0;
const oracle=https.createServer({key,cert},(req,res)=>{requests++;res.end('must remain untrusted');});
const listen=server=>new Promise(resolve=>server.listen(0,'localhost',()=>resolve(server.address().port)));
const port=await listen(oracle);
const gate=createResponseGate({key,cert,ca:[],target:'https://localhost:'+port,controlToken:'fixture-control',deadlineMS:1000});
const gatePort=await listen(gate);
try{
await assert.rejects(new Promise((resolve,reject)=>{const req=https.get({hostname:'localhost',port:gatePort,ca:cert,agent:false},resolve);req.on('error',reject);}));
assert.equal(requests,0,'untrusted certificate never reaches the upstream HTTP handler');
}finally{for(const server of [gate,oracle]){server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}}
console.log('tls-rejection-passed');
"""
    result = subprocess.run(["node", "--input-type=module", "-e", program, str(tls)], cwd=ROOT,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "tls-rejection-passed"
