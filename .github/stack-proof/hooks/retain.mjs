import {readFile,writeFile,rename,access} from 'node:fs/promises';
export async function retain(tool) {
  const pid=process.pid;
  const stat=await readFile('/proc/self/stat','utf8');
  const ticks=stat.slice(stat.lastIndexOf(')')+1).trim().split(/\s+/)[19];
  const key=`${pid}-${process.hrtime.bigint()}`;
  const base='/proof-audit/'+key;
  await writeFile(base+'.tmp',JSON.stringify({tool,ownerPid:pid,startTicks:ticks,key}),{mode:0o644});
  await rename(base+'.tmp',base+'.ready.json');
  const deadline=performance.now()+20000;
  for (;;) {
    try {await access(base+'.release');return;}
    catch(error) {if(error.code!=='ENOENT')throw error;}
    if(performance.now()>deadline)throw new Error('Causal sandbox observation deadline');
    await new Promise(resolve=>setTimeout(resolve,10));
  }
}
