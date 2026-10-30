"""Test-only navigation retention. Never replaces a product result or policy."""
import importlib.abc
import importlib.machinery
import sys

class ObserveHTML(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path,target=None):
        if fullname!='project_remedy.html_browser': return None
        spec=importlib.machinery.PathFinder.find_spec(fullname,path)
        if spec is None or spec.loader is None: return None
        original=spec.loader
        class Loader(importlib.abc.Loader):
            def create_module(self,spec): return original.create_module(spec)
            def exec_module(self,module):
                original.exec_module(module)
                annotate(module)
        spec.loader=Loader()
        return spec

def annotate(module):
    import asyncio
    from contextlib import asynccontextmanager
    import contextvars
    import json
    import os
    from pathlib import Path
    import time
    directory=Path('/proof-audit')
    tool_context=contextvars.ContextVar('proof_tool',default=None)
    original_page=module.offline_page
    @asynccontextmanager
    async def retained(*args,**kwargs):
        async with original_page(*args,**kwargs) as page:
            pid=os.getpid();ticks=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()[19]
            key=f'{pid}-{time.monotonic_ns()}'
            temporary=directory/(key+'.tmp')
            temporary.write_text(json.dumps({'tool':'server-render','ownerPid':pid,'startTicks':ticks,'key':key}))
            temporary.chmod(0o644);temporary.replace(directory/(key+'.ready.json'))
            async with asyncio.timeout(20):
                while not (directory/(key+'.release')).exists(): await asyncio.sleep(.01)
            yield page
    module.offline_page=retained
    original_checker=module.run_html_checker
    async def checker(tool,html):
        token=tool_context.set(tool)
        try: return await original_checker(tool,html)
        finally: tool_context.reset(token)
    module.run_html_checker=checker
    original_spawn=asyncio.create_subprocess_exec
    async def spawn(*args,**kwargs):
        if len(args)>1 and args[0]=='node' and str(args[1]).endswith('/html_tools/check.mjs'):
            kwargs['env']={**kwargs.get('env',{}),'PROOF_TOOL':'server-'+str(tool_context.get())}
            args=(args[0],'--import','file:///proof-hooks/checker.mjs',*args[1:])
        return await original_spawn(*args,**kwargs)
    asyncio.create_subprocess_exec=spawn

sys.meta_path.insert(0,ObserveHTML())
