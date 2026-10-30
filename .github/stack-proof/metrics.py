"""Read-only cgroup-v2 measurements for exact owned product containers."""
from pathlib import Path
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
        with self.lock: self.items[info['Id']]={'name':name,'path':base,'limits':limits,'samples':0,'memoryPeakBytes':0,'pidPeak':0,'cpuUsageUsec':0}
    def collect(self):
        while not self.stop.is_set():
            with self.lock:
                for item in self.items.values():
                    base=item['path']
                    try:
                        memory=int((base/'memory.max').read_text());pids=int((base/'pids.max').read_text())
                        quota,period=map(int,(base/'cpu.max').read_text().split())
                        assert memory==item['limits']['memoryBytes'] and pids==item['limits']['pids']
                        assert quota/period==item['limits']['cpus']
                        item['memoryPeakBytes']=max(item['memoryPeakBytes'],int((base/'memory.peak').read_text()))
                        item['pidPeak']=max(item['pidPeak'],int((base/'pids.peak').read_text()))
                        cpu=dict(line.split() for line in (base/'cpu.stat').read_text().splitlines())
                        item['cpuUsageUsec']=max(item['cpuUsageUsec'],int(cpu['usage_usec']))
                        item['samples']+=1
                    except FileNotFoundError:
                        # The exact cgroup can disappear after its owned task exits.
                        if base.exists() and 'required cgroup peak counters unavailable' not in self.errors: self.errors.append('required cgroup peak counters unavailable')
                    except Exception as error:
                        message=type(error).__name__+': '+str(error)
                        if message not in self.errors: self.errors.append(message)
            self.stop.wait(.02)
    def close(self):
        self.stop.set();self.thread.join(5)
        with self.lock:
            values={key:{k:v for k,v in item.items() if k!='path'} for key,item in self.items.items()}
        for item in values.values():
            if not item['samples']: self.errors.append('no actual resource measurements:'+item['name'])
            if item['memoryPeakBytes']>item['limits']['memoryBytes'] or item['pidPeak']>item['limits']['pids']: self.errors.append('resource bound exceeded')
        return values
