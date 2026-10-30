// Diagnostic only after actual owned HTTP rendering failed. Uses the unchanged
// module and exact policy/environment; never counts as service acceptance.
import {scan} from '/app/scan.mjs';
import {chromium} from '/app/node_modules/playwright/index.mjs';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import {createHash} from 'node:crypto';
let browserVersion;
try{browserVersion=execFileSync(chromium.executablePath(),['--version'],{encoding:'utf8',timeout:5000}).trim();}
catch(error){browserVersion={error:error.code??error.name};}
const information={home:process.env.HOME,xdgDataHome:process.env.XDG_DATA_HOME??null,uid:process.getuid(),browser:browserVersion,databases:{}};
for(const directory of [process.env.HOME+'/.pki/nssdb',process.env.HOME+'/.local/share/pki/nssdb']){
 information.databases[directory]={};
 for(const file of ['cert9.db','key4.db','pkcs11.txt']){
  const path=directory+'/'+file;
  try {const value=fs.readFileSync(path),info=fs.statSync(path);information.databases[directory][file]={uid:info.uid,mode:info.mode&0o777,size:value.length,sha256:createHash('sha256').update(value).digest('hex')};}
  catch(error){information.databases[directory][file]={error:error.code};}
 }
}
try {
  const result=await scan('https://dev.libretexts.org/Sandboxes/johnnyphung/Stack/Synthetic');
  console.log(JSON.stringify({diagnosticOnly:true,information,state:result.state,error:result.error??null,blockedResources:result.blockedResources??[],failedResources:result.failedResources??[]}));
} catch(error) {
  console.log(JSON.stringify({diagnosticOnly:true,information,state:'threw-before-response',name:error.name,message:String(error.message).slice(0,5000)}));
}
