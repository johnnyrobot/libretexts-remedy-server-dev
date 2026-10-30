// Diagnostic comparison only. Never replaces the original producer HTTP proof.
import {chromium} from '/app/node_modules/playwright/index.mjs';
const results=[];
for(const channel of [undefined,'chromium']){
  let server,browser;
  const result={diagnosticOnly:true,channel:channel??'headless-shell',tlsValidation:true,sandbox:true};
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
console.log(JSON.stringify({diagnosticOnly:true,results}));
