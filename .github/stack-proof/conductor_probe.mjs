// Actual compiled consumer, Mongo, fallback sessions and HTTP calls; no engine fake.
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {createPrivateKey,createPublicKey,randomBytes,sign,verify} from 'node:crypto';
import {MongoClient,ObjectId} from '/usr/src/conductor/server/node_modules/mongodb/lib/index.js';
import bcrypt from '/usr/src/conductor/server/node_modules/bcryptjs/index.js';
const phase=process.argv[2], config=JSON.parse(fs.readFileSync('/fixture/app.json'));
assert.match(process.version,/^v22\./);
assert.equal(process.env.NODE_ENV,'production');
const processes=fs.readdirSync('/proc').filter(p=>/^\d+$/.test(p)).flatMap(p=>{
  try{return [fs.readFileSync('/proc/'+p+'/cmdline','utf8').replaceAll('\0',' ').trim()];}catch{return [];}
});
assert.ok(processes.includes('node dist/server.js'),'actual compiled shipping entrypoint');
const client=new MongoClient(process.env.MONGOOSEURI);await client.connect();const db=client.db();
if(phase==='review'){
  for(const name of ['editor','auditor','outsider'])await db.collection('users').insertOne({
    uuid:config[name],centralID:'synthetic-'+name,email:name+'@candidate.example.invalid',firstName:'Synthetic',lastName:name,
    authType:'traditional',password:await bcrypt.hash(config.password,4),roles:[{org:'libretexts',role:'user'}],verifiedInstructor:true,uxAcknowledgments:{}});
  await db.collection('organizations').insertOne({orgID:'libretexts',active:true,name:'Synthetic candidate',subdomain:'candidate',domain:'https://conductor.invalid',commonsModules:{projects:{enabled:true,order:1}}});
  await db.collection('projects').insertOne({projectID:config.projectID,orgID:'libretexts',title:'Full owned stack synthetic',status:'open',classification:'construction',projectURL:'',libreLibrary:'',libreCoverID:'',contentArea:'Synthetic',visibility:'private',members:[config.editor],leads:[],liaisons:[],auditors:[config.auditor],tags:[],a11yReview:[{_id:new ObjectId(config.sectionID),sectionTitle:'Synthetic reader',sectionURL:config.pageURL,pageID:'42'}]});
}
const origin='http://127.0.0.1:5000',cookies={};
for(const name of ['editor','auditor','outsider']){
  const r=await fetch(origin+'/api/v1/auth/fallback-auth',{method:'POST',redirect:'manual',headers:{'Content-Type':'application/json',Origin:'https://conductor.invalid'},body:JSON.stringify({email:name+'@candidate.example.invalid',password:config.password})});
  assert.equal(r.status,302,'actual fallback authentication');
  const set=r.headers.getSetCookie();assert.ok(set.some(c=>/Secure/i.test(c)));assert.ok(set.some(c=>/Domain=conductor.invalid/i.test(c)));
  cookies[name]=set.map(c=>c.split(';')[0]).join('; ');
}
async function request(path,body,user='editor'){
  const r=await fetch(origin+'/api/v1'+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json',Origin:'https://conductor.invalid','X-Requested-With':'XMLHttpRequest',...(user?{Cookie:cookies[user]}:{})},...(body?{body:JSON.stringify(body)}:{})});
  return {status:r.status,data:await r.json()};
}
const matrix='/project/accessibility/remedy',base=`/project/${config.projectID}/accessibility/workqueue`,page=base+'/page/'+config.sectionID;
const input={projectID:config.projectID,sectionID:config.sectionID,fixMode:'deterministic'};
assert.equal((await request(matrix+'/health?projectID='+config.projectID,undefined,'')).status,401);
assert.equal((await request('/project?projectID='+config.projectID)).status,200);
assert.equal((await request(page+'/scan',input,'outsider')).status,403);
assert.equal((await request(page+'/scan',input,'auditor')).status,403);
const health=await request(matrix+'/health?projectID='+config.projectID);
assert.equal(health.status,200,JSON.stringify(health));
assert.equal(health.data.capabilities.scan,true,JSON.stringify(health));
assert.equal(health.data.capabilities.preview,true,JSON.stringify(health));
assert.equal(health.data.capabilities.mutate,false,JSON.stringify(health));
assert.equal(health.data.profile.name,phase==='review'?'review-only':'full-write');
const scan=await request(page+'/scan',input);assert.equal(scan.status,200,JSON.stringify(scan));
const rendered=await request(page+'/rendered-scan',input);assert.equal(rendered.status,200,JSON.stringify(rendered));
const project=await db.collection('projects').findOne({projectID:config.projectID}),evidence=project.a11yReview[0].wcagReview;
assert.ok(evidence.sourceHash,'real authored source hash');
assert.equal(evidence.rendered.state,'complete',JSON.stringify(evidence.rendered));
assert.match(evidence.rendered.renderedHash,/^[a-f0-9]{64}$/);assert.match(evidence.rendered.platformHash,/^[a-f0-9]{64}$/);
input.findingIDs=rendered.data.findings.filter(f=>f.fixable).map(f=>f.id);
assert.ok(input.findingIDs.length,'actual source scan supplies selected fixable finding IDs');
const preview=await request(matrix+'/preview',input);assert.equal(preview.status,200,JSON.stringify(preview));
assert.ok(preview.data.localReviewID&&preview.data.preview_hash&&preview.data.preview_token);
const before=await db.collection('projects').findOne({projectID:config.projectID});
for(const endpoint of [matrix+'/apply',page+'/apply',page+'/restore']){
  const denied=await request(endpoint,{...input,localReviewID:preview.data.localReviewID,previewToken:preview.data.preview_token,previewHash:preview.data.preview_hash,confirmed:true});
  assert.equal(denied.status,503,JSON.stringify(denied));
}
if(phase==='production-held'){
  const key=createPrivateKey(fs.readFileSync(process.env.REMEDY_REVIEWER_SIGNING_KEY_FILE));
  const now=Math.floor(Date.now()/1000);
  const header=Buffer.from(JSON.stringify({alg:'Ed25519',kid:process.env.REMEDY_REVIEWER_KEY_ID,typ:'remedy-review+jwt'})).toString('base64url');
  const claims=Buffer.from(JSON.stringify({v:1,iss:process.env.REMEDY_REVIEWER_ISSUER,aud:process.env.REMEDY_REVIEWER_AUDIENCE,sub:config.editor,iat:now,nbf:now,exp:Math.min(now+60,preview.data.review_expires_at),jti:randomBytes(32).toString('base64url'),binding:preview.data.review_binding})).toString('base64url');
  const payload=header+'.'+claims,signature=sign(null,Buffer.from(payload),key);
  assert.equal(verify(null,Buffer.from(payload),createPublicKey(key),signature),true,'synthetic assertion cryptographically valid');
  const response=await fetch(process.env.REMEDY_API_BASE_URL+'/v1/cxone/page/apply-fix',{method:'POST',headers:{'Content-Type':'application/json','X-API-Key':process.env.REMEDY_API_KEY},body:JSON.stringify({page_url:config.pageURL,preview_hash:preview.data.preview_hash,preview_token:preview.data.preview_token,reviewer_assertion:payload+'.'+signature.toString('base64url')})});
  const denied=await response.json();assert.equal(response.status,503,JSON.stringify(denied));
  assert.equal(denied.error,'conditional_write_unproven');assert.equal(denied.outcome,'not_attempted');assert.equal(denied.operation_id,null);
}
assert.deepEqual(await db.collection('projects').findOne({projectID:config.projectID}),before,'held writes never consume preview or page state');
assert.equal(await db.collection('remedyoperationrecords').countDocuments({projectID:config.projectID}),0,'held writes never append an intent');
const report=await request(base+'/conformance');assert.equal(report.status,200);assert.equal(report.data.report.verifiedCriteria,0);
await client.close();
console.log(JSON.stringify({phase,passed:true,node:process.version,compiledEntrypoint:true,realAuthenticationAndMongo:true,projectAuthorization:true,realScanPreview:true,realRenderedEvidence:true,renderedHash:evidence.rendered.renderedHash,platformHash:evidence.rendered.platformHash,productionMutationDenied:true,intents:0,verifiedCriteria:0}));
