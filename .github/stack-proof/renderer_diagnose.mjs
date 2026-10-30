// Diagnostic only after actual owned HTTP rendering failed. Uses the unchanged
// module and exact policy/environment; never counts as service acceptance.
import {scan} from '/app/scan.mjs';
try {
  const result=await scan('https://dev.libretexts.org/Sandboxes/johnnyphung/Stack/Synthetic');
  console.log(JSON.stringify({diagnosticOnly:true,state:result.state,error:result.error??null,blockedResources:result.blockedResources??[],failedResources:result.failedResources??[]}));
} catch(error) {
  console.log(JSON.stringify({diagnosticOnly:true,state:'threw-before-response',name:error.name,message:String(error.message).slice(0,5000)}));
}
