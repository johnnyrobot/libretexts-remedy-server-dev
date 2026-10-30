// Diagnostic comparison only. Never replaces the original producer HTTP proof.
import {chromium} from '/app/node_modules/playwright/index.mjs';
import {execFileSync} from 'node:child_process';
import {X509Certificate} from 'node:crypto';
import fs from 'node:fs';
const results=[],nativeTrust={};
for(const stage of ['before-native-import','after-native-import']){
if(stage==='after-native-import'){
 try {
  const expected=new X509Certificate(fs.readFileSync('/fixture-ca/ca.pem')).fingerprint256;
  const exported=execFileSync('/proof/certutil',['-L','-d','sql:'+process.env.HOME+'/.pki/nssdb','-n','isolated-cxone-fixture','-a'],{encoding:'utf8',timeout:10000});
  nativeTrust.beforeMatchesCA=new X509Certificate(exported).fingerprint256===expected;
  execFileSync('/proof/certutil',['-A','-d','sql:'+process.env.HOME+'/.pki/nssdb','-n','isolated-cxone-fixture','-t','C,,','-i','/fixture-ca/ca.pem'],{timeout:10000});
  nativeTrust.imported=true;
 } catch(error){nativeTrust.error=String(error.message).slice(0,2500);break;}
}
for(const channel of [undefined,'chromium']){
  let server,browser;
  const result={diagnosticOnly:true,stage,channel:channel??'headless-shell',tlsValidation:true,sandbox:true};
  try {
    server=await chromium.launchServer({host:'127.0.0.1',chromiumSandbox:true,...(channel?{channel}:{}),args:['--force-webrtc-ip-handling-policy=disable_non_proxied_udp','--host-resolver-rules=MAP dev.libretexts.org 198.51.100.10,MAP * ~NOTFOUND']});
    browser=await chromium.connect(server.wsEndpoint());
    const context=await browser.newContext({serviceWorkers:'block',acceptDownloads:false});
    await context.route('**/*',route=>{
      const request=route.request(),url=new URL(request.url());
      return ['GET','HEAD'].includes(request.method())&&url.protocol==='https:'&&url.hostname==='dev.libretexts.org'&&(!url.port||url.port==='443')?route.continue():route.abort();
    });
    const page=await context.newPage();
    const response=await page.goto('https://dev.libretexts.org/Sandboxes/johnnyphung/Stack/Synthetic',{waitUntil:'load',timeout:20000});
    result.passed=response.status()===200&&(await page.locator('section.mt-content-container').innerText()).includes('Retained stack sentinel');
    result.version=browser.version();await context.close();
  } catch(error){result.passed=false;result.name=error.name;result.error=String(error.message).slice(0,2000);}
  finally {await browser?.close().catch(()=>{});await server?.close().catch(()=>{});}
  results.push(result);
}
}
console.log(JSON.stringify({diagnosticOnly:true,nativeTrust,results}));
