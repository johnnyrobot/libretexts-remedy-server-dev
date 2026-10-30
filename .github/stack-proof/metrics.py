"""Read-only cgroup-v2 measurements for exact owned product containers."""
from pathlib import Path
import errno
import threading

class Metrics:
    def __init__(self):
        self.items={};self.lock=threading.Lock();self.stop=threading.Event();self.errors=[]
        self.thread=threading.Thread(target=self.collect,daemon=True);self.thread.start()
    def register(self,name,info,limits):
        pid=info['State']['Pid']
        if not pid: return
        lines=(Path('/proc')/str(pid)/'cgroup').read_text().splitlines()
        paths=[line[3:] for line in lines if line.startswith('0::')]
        if len(paths)!=1: raise ValueError('required cgroup-v2 observation unavailable')
        base=(Path('/sys/fs/cgroup')/paths[0].lstrip('/')).resolve()
        if not base.is_relative_to(Path('/sys/fs/cgroup')): raise ValueError('invalid cgroup observation')
        with self.lock: self.items[info['Id']]={'name':name,'path':base,'image':info['Image'],'limits':limits,'samples':0,'memoryPeakBytes':0,'pidPeak':0,'cpuUsageUsec':0,'stopping':False,'stopConfirmed':False}

    def _sample(self,item):
        base=item['path']
        memory=int((base/'memory.max').read_text());pids=int((base/'pids.max').read_text())
        quota,period=map(int,(base/'cpu.max').read_text().split())
        assert memory==item['limits']['memoryBytes'] and pids==item['limits']['pids']
        assert quota/period==item['limits']['cpus']
        item['memoryPeakBytes']=max(item['memoryPeakBytes'],int((base/'memory.peak').read_text()))
        item['pidPeak']=max(item['pidPeak'],int((base/'pids.peak').read_text()))
        cpu=dict(line.split() for line in (base/'cpu.stat').read_text().splitlines())
        item['cpuUsageUsec']=max(item['cpuUsageUsec'],int(cpu['usage_usec']))
        item['samples']+=1

    def begin_stop(self,identity):
        with self.lock:
            item=self.items[identity]
            if item['stopConfirmed']: return
            # A final LIVE read is mandatory. No missing-device or permission
            # error can be reclassified merely because stop is about to begin.
            self._sample(item)
            item['stopping']=True

    def finish_stop(self,info):
        with self.lock:
            item=self.items.get(info['Id'])
            if item is None or info.get('Image')!=item['image']:
                raise ValueError('stopped metric identity mismatch')
            state=info['State']
            if (state.get('Status')!='exited' or state.get('Running') is not False or state.get('Pid')!=0 or
                    any(state.get(key) for key in ('Paused','Restarting','Dead','OOMKilled','Error'))):
                raise ValueError('metric stop is not confirmed')
            if item['stopConfirmed']: return
            if not item['stopping']: raise ValueError('metric stop was not planned')
            try:
                self._sample(item)
                item['finalSampleAvailable']=True
            except OSError as error:
                if error.errno not in {errno.ENOENT,errno.ESRCH,errno.ENODEV}: raise
                # The exact owned container is now independently confirmed
                # stopped. Its cgroup can already be gone; retain prior actual
                # samples and report this limitation, never invent peak data.
                item['finalSampleAvailable']=False
                item['finalReadUnavailableErrno']=error.errno
            item['stopConfirmed']=True
            item['rawExitCode']=state['ExitCode']
    def collect(self):
        while not self.stop.is_set():
            with self.lock:
                for item in self.items.values():
                    if item['stopping'] or item['stopConfirmed']: continue
                    try:
                        self._sample(item)
                    except Exception as error:
                        message=type(error).__name__+': '+str(error)
                        if message not in self.errors: self.errors.append(message)
            self.stop.wait(.02)
    def close(self):
        self.stop.set();self.thread.join(5)
        if self.thread.is_alive():
            self.errors.append('metrics_collector_did_not_stop')
            return {}  # fail closed instead of waiting on a stuck reader's lock
        with self.lock:
            values={key:{k:v for k,v in item.items() if k!='path'} for key,item in self.items.items()}
        for item in values.values():
            if not item['stopConfirmed']: self.errors.append('metric stop unconfirmed:'+item['name'])
            if not item['samples']: self.errors.append('no actual resource measurements:'+item['name'])
            if item['memoryPeakBytes']>item['limits']['memoryBytes'] or item['pidPeak']>item['limits']['pids']: self.errors.append('resource bound exceeded')
        return values
