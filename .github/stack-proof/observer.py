"""Read-only host observations, limited to live identities in owned containers."""
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time

def flag(process,name):
    # Chromium can rewrite argv into a single process-title string. Match a
    # complete flag token in either representation; never infer identity from it.
    return re.search(r'(?:^|\s)'+re.escape(name)+r'(?:=|\s|$)',' '.join(process['commandLine'])) is not None

def is_renderer(process):
    return re.search(r'(?:^|\s)--type=renderer(?:\s|$)',' '.join(process['commandLine'])) is not None

class Observer:
    def __init__(self,directories):
        self.directories=directories;self.stop=threading.Event();self.records=[];self.errors=[]
        self.thread=threading.Thread(target=self.observe,daemon=True)
    def start(self): self.thread.start()
    def close(self):
        self.stop.set();self.thread.join(10)
        if self.thread.is_alive(): self.errors.append('observer_did_not_stop')
    def processes(self,container):
        value=subprocess.run(['docker','top',container,'-eo','pid'],text=True,capture_output=True)
        if value.returncode: return {}
        result={}
        for line in value.stdout.splitlines()[1:]:
            host=int(line.strip());proc=Path('/proc')/str(host)
            try:
                fields=dict(line.split(':',1) for line in (proc/'status').read_text().splitlines())
                ids=list(map(int,fields['NSpid'].split()))
                if len(ids)<2: raise ValueError('container namespace not found')
                stat=(proc/'stat').read_text().rsplit(')',1)[1].split()
                result[host]={'hostPid':host,'containerPid':ids[1],'namespacePids':ids,
                    'parent':int(stat[1]),'group':int(stat[2]),'startTicks':stat[19],
                    'userNamespace':os.readlink(proc/'ns/user'),'pidNamespace':os.readlink(proc/'ns/pid'),
                    'commandLine':(proc/'cmdline').read_bytes().decode().split('\0'),
                    'status':{k:fields[k].strip() for k in ('Uid','NoNewPrivs','CapEff','Seccomp','Seccomp_filters')}}
            except FileNotFoundError: continue
        return result
    def one(self,container,path):
        request=json.loads(path.read_text());key=request['key']
        if not re.fullmatch(r'\d+-\d+',key) or path.name!=key+'.ready.json': raise ValueError('invalid observation identity')
        if request['tool'] not in {'server-render','server-axe','server-pa11y','server-lighthouse','scanner-browser'}: raise ValueError('unknown actual tool')
        deadline=time.monotonic()+12
        diagnostic={'request':request,'lastCensus':[],'matchingOwners':[],'browserCandidates':[]}
        while time.monotonic()<deadline and not self.stop.is_set():
            census=self.processes(container)
            diagnostic['lastCensus']=list(census.values())
            owners=[p for p in census.values() if p['containerPid']==request['ownerPid'] and p['startTicks']==request['startTicks']]
            diagnostic['matchingOwners']=owners
            if not owners:
                path.with_name(key+'.census.json').write_text(json.dumps(diagnostic,indent=2)+'\n');time.sleep(.02);continue
            if len(owners)!=1: raise ValueError('ambiguous owner')
            owner=owners[0]
            def descends(process,ancestor):
                visited=set()
                while process['parent'] in census and process['parent'] not in visited:
                    if process['parent']==ancestor: return True
                    visited.add(process['parent']);process=census[process['parent']]
                return False
            browsers=[p for p in census.values() if descends(p,owner['hostPid']) and
                (flag(p,'--remote-debugging-pipe') or flag(p,'--remote-debugging-port')) and
                not flag(p,'--type')]
            diagnostic['browserCandidates']=browsers
            if len(browsers)!=1:
                path.with_name(key+'.census.json').write_text(json.dumps(diagnostic,indent=2)+'\n');time.sleep(.02);continue
            browser=browsers[0]
            renderers=[p for p in census.values() if is_renderer(p) and descends(p,browser['hostPid'])]
            diagnostic['rendererCandidates']=renderers
            if not renderers:
                path.with_name(key+'.census.json').write_text(json.dumps(diagnostic,indent=2)+'\n');time.sleep(.02);continue
            renderer=renderers[0]
            for record in (owner,browser,renderer):
                status=record['status'];assert int(status['Uid'].split()[0])!=0 and status['NoNewPrivs']=='1' and int(status['CapEff'],16)==0 and status['Seccomp']=='2'
                assert not any(flag(record,name) for name in ('--no-sandbox','--disable-namespace-sandbox','--disable-seccomp-filter-sandbox','--single-process'))
            assert renderer['userNamespace']!=browser['userNamespace'] and renderer['userNamespace']!=owner['userNamespace']
            assert renderer['pidNamespace']!=browser['pidNamespace'] and renderer['pidNamespace']!=owner['pidNamespace']
            assert len(renderer['namespacePids'])>len(browser['namespacePids'])
            assert int(renderer['status']['Seccomp_filters'])>int(browser['status']['Seccomp_filters'])
            worker=None
            if request['tool']=='scanner-browser':
                workers=[p for p in census.values() if descends(browser,p['hostPid']) and any(a.endswith('/browser-worker.js') for a in p['commandLine'])]
                assert len(workers)==1,'actual pre-owned Scanner worker unavailable'
                worker=workers[0]
                assert worker['group']==worker['hostPid'] and browser['group']==worker['group'] and renderer['group']==worker['group']
            value={'tool':request['tool'],'owner':owner,'browser':browser,'renderer':renderer,'retainedBeforeRelease':True,'scannerWorker':worker}
            target=path.with_name(key+'.observation.json');target.write_text(json.dumps(value,indent=2)+'\n');target.chmod(0o644)
            self.records.append(value);path.with_name(key+'.release').touch();return
        raise TimeoutError('actual navigated renderer observation unavailable')
    def observe(self):
        while not self.stop.is_set():
            for container,directory in self.directories.items():
                for path in directory.glob('*.ready.json'):
                    if path.with_name(path.name.replace('.ready.json','.release')).exists(): continue
                    try: self.one(container,path)
                    except Exception as error:
                        self.errors.append(type(error).__name__+': '+str(error))
                        # Release only this causal test barrier. Never publish a
                        # successful record or alter the product security flags.
                        path.with_name(path.name.replace('.ready.json','.release')).touch()
            self.stop.wait(.01)
