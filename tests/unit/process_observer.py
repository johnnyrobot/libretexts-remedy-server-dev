"""Independent test-only process observation; never an ownership proof."""
from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    created: tuple[int, int]


@dataclass(frozen=True)
class ProcessInfo:
    identity: ProcessIdentity
    parent: int
    group: int
    zombie: bool = False


# Darwin's proc_bsdinfo layout is defined by sys/proc_info.h. In contrast to
# ps lstart's second-resolution display, these kernel birth fields retain usec.
class _BsdInfo(ctypes.Structure):
    _fields_ = ([(name, ctypes.c_uint32) for name in (
        "flags", "status", "xstatus", "pid", "ppid", "uid", "gid", "ruid",
        "rgid", "svuid", "svgid", "reserved",
    )] + [("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32)]
        + [(name, ctypes.c_uint32) for name in ("nfiles", "pgid", "jobc", "tdev", "tpgid")]
        + [("nice", ctypes.c_int32), ("start_sec", ctypes.c_uint64), ("start_usec", ctypes.c_uint64)])


@lru_cache(maxsize=1)
def _darwin_pidinfo():
    library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    function = library.proc_pidinfo
    function.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    function.restype = ctypes.c_int
    return function


def process_snapshot() -> dict[int, ProcessInfo]:
    """Read parent/group/creation metadata, without retaining any display names."""
    processes = {}
    if sys.platform.startswith("linux"):
        for entry in os.scandir("/proc"):
            if not entry.name.isdigit():
                continue
            try:
                with open(entry.path + "/stat") as stream:
                    tail = stream.read().rsplit(") ", 1)[1].split()
                pid = int(entry.name)
                # /proc/PID/stat field22 (starttime); state is field3/tail[0].
                processes[pid] = ProcessInfo(ProcessIdentity(pid, (int(tail[19]), 0)),
                                             int(tail[1]), int(tail[2]), tail[0] == "Z")
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
    else:
        # ps supplies the PID list only. Read all ownership fields atomically
        # from proc_pidinfo, so a reused PID cannot pair a new birth with an old PPID.
        result = subprocess.run(["/bin/ps", "-axo", "pid="], capture_output=True,
                                text=True, timeout=1, check=True)
        pidinfo = _darwin_pidinfo()
        for raw_pid in result.stdout.split():
            info = _BsdInfo()
            size = pidinfo(int(raw_pid), 3, 0, ctypes.byref(info), ctypes.sizeof(info))
            if size != ctypes.sizeof(info):
                continue  # disappeared or belongs to an unreadable process
            processes[info.pid] = ProcessInfo(ProcessIdentity(info.pid, (info.start_sec, info.start_usec)),
                                               info.ppid, info.pgid, info.status == 5)
    return processes
