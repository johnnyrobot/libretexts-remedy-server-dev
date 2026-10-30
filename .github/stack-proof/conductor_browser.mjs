// Real compiled UI, browser cookie jar and trusted private TLS. Synthetic login
// is the existing product fallback form; this makes no production SSO claim.
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {chromium} from '/app/node_modules/playwright/index.mjs';
const config=JSON.parse(fs.readFileSync('/fixture/app.json'));
const browser=await chromium.launch({headless:true,chromiumSandbox:true});
const context=await browser.newContext();
const errors=[],page=await context.newPage();
const safeMessage=error=>String(error?.message??error).replaceAll(config.password,'[synthetic credential redacted]').slice(0,1600);
page.on('pageerror',error=>errors.push({name:error.name,message:safeMessage(error)}));
await context.route('**/*',route=>{
  const url=new URL(route.request().url());
  return url.protocol==='https:'&&url.hostname==='conductor.invalid'&&url.port==='8443'?route.continue():route.abort();
});
try {
  await page.goto('https://conductor.invalid:8443/fallback-auth',{waitUntil:'domcontentloaded'});
  console.log(JSON.stringify({checkpoint:'compiled-login-page-over-trusted-TLS',passed:true}));
  await page.getByLabel(/^Email/).fill('editor@candidate.example.invalid');
  await page.getByLabel(/^Password/).fill(config.password);
  await page.getByRole('button',{name:'Login',exact:true}).click();
  await page.waitForURL('**/home',{timeout:30000});
  console.log(JSON.stringify({checkpoint:'real-browser-fallback-login',passed:true}));
  const cookies=await context.cookies();
  assert.ok(cookies.some(cookie=>cookie.secure&&cookie.domain.includes('conductor.invalid')),'browser accepted real Secure session cookie over trusted TLS');
  await page.goto('https://conductor.invalid:8443/projects/'+config.projectID+'/accessibility');
  const verification=page.getByRole('region',{name:'WCAG verification'});
  await verification.getByRole('heading',{name:'Remediation acceptance and WCAG verification',exact:true}).waitFor();
  await page.getByText('Automatic edits are unavailable.',{exact:false}).first().waitFor();
  const result=await page.evaluate(async projectID=>{
    const r=await fetch('/api/v1/project/accessibility/remedy/health?projectID='+projectID,{credentials:'same-origin'});
    return {status:r.status,body:await r.json()};
  },config.projectID);
  assert.equal(result.status,200);assert.equal(result.body.capabilities.mutate,false);
  // Save synthetic failure evidence, never invent a successful human review.
  const scopeSummary=verification.locator('summary').filter({hasText:/^Evaluation scope/});
  await scopeSummary.click();
  assert.notEqual(await scopeSummary.locator('..').getAttribute('open'),null,'native evaluation scope disclosure opened');
  await verification.getByLabel('Full-page boundaries and included content').fill('Isolated synthetic full reader page and its authored source.');
  await verification.getByLabel('Complete processes and interaction states to evaluate').fill('Synthetic login, page reading and remediation preview only.');
  await verification.getByLabel('Platform release and relevant configuration').fill('Exact pinned Linux candidate with trusted private TLS.');
  await verification.getByLabel('This scope covers full pages',{exact:false}).check();
  const [scopeResponse]=await Promise.all([
    page.waitForResponse(r=>r.url().endsWith('/conformance/scope')&&r.request().method()==='POST'),
    verification.getByRole('button',{name:'Save evaluation scope',exact:true}).click(),
  ]);
  assert.equal(scopeResponse.status(),200);assert.equal((await scopeResponse.json()).err,false);
  await verification.getByText('Review record saved.',{exact:true}).waitFor();
  await verification.getByLabel('Page to evaluate',{exact:true}).selectOption(config.sectionID);
  await verification.getByLabel('Review outcome',{exact:true}).selectOption('fail');
  await verification.getByLabel('Test environment:',{exact:false}).fill('Synthetic Chromium Linux candidate; no human conformance verification.');
  await verification.getByLabel('Evidence and results, including',{exact:false}).fill('Synthetic regression records an observed incomplete review and failure; this is not human WCAG approval.');
  const form=verification.locator('form').filter({has:page.getByLabel('Review outcome',{exact:true})});
  for(const box of await form.getByRole('checkbox').all())await box.check();
  const [reviewResponse]=await Promise.all([
    page.waitForResponse(r=>r.url().endsWith('/conformance/review')&&r.request().method()==='POST'),
    form.getByRole('button',{name:'Save reviewer evidence',exact:true}).click(),
  ]);
  assert.equal(reviewResponse.status(),200);assert.equal((await reviewResponse.json()).err,false);
  const history=await page.evaluate(async cfg=>{
    const path='/api/v1/project/'+cfg.projectID+'/accessibility/workqueue/conformance/history?sectionID='+cfg.sectionID+'&criterionID=1.1.1';
    const response=await fetch(path,{credentials:'same-origin',headers:{'X-Requested-With':'XMLHttpRequest'}});
    return {status:response.status,body:await response.json()};
  },config);
  assert.equal(history.status,200);
  assert.ok(history.body.records.some(record=>record.actor===config.editor&&record.data?.status==='fail'),'real UI submission persisted as synthetic failure evidence');
  console.log(JSON.stringify({checkpoint:'actual-scope-and-review-records-persisted',passed:true}));
  assert.equal(errors.length,0,'compiled UI must not throw');
  await page.screenshot({path:'/browser-evidence/synthetic-review.png',fullPage:true});
  console.log(JSON.stringify({passed:true,realCompiledUI:true,trustedTLS:true,browserManagedSecureCookie:true,syntheticFallbackLogin:true,manualFailureEvidenceSaved:true,productionMutationFalse:true,productionSSOVerified:false}));
} catch(error) {
  fs.writeFileSync('/browser-evidence/browser-error.json',JSON.stringify({name:error.name,message:safeMessage(error),pageErrors:errors},null,2));
  await page.screenshot({path:'/browser-evidence/synthetic-failure.png',fullPage:true}).catch(()=>{});
  throw Error('Actual compiled browser acceptance failed; see sanitized browser-error.json and screenshot.');
} finally {await browser.close();}
