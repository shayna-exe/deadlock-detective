"""A fake ``psutil`` for tests: no real process is ever read, suspended or killed."""
from __future__ import annotations

from collections import namedtuple
from typing import Dict, List, Optional

CpuTimes = namedtuple("CpuTimes", "user system")
MemInfo = namedtuple("MemInfo", "rss vms")
VMem = namedtuple("VMem", "total available percent")

GB = 1024 ** 3
MB = 1024 ** 2


class FakeProc:
    """Behaves like psutil.Process for the attributes the monitor reads."""

    def __init__(self, ps, pid, name="app.exe", create_time=1000.0, ppid=100, exe="C:/Apps/app.exe",
                 cpu=(0.0, 0.0), rss=300 * MB, user=1.0, system=0.5, status="running", nice=0,
                 deny=(), gone=False):
        self._ps, self.pid = ps, pid
        self.name_, self.create_time_, self.ppid_, self.exe_ = name, create_time, ppid, exe
        self.cpu_seq = list(cpu)
        self.rss_, self.user_, self.system_ = rss, user, system
        self.status_, self.nice_ = status, nice
        self.deny, self.gone = set(deny), gone
        self.calls: List[str] = []
        self.alive = True
        self.wait_times_out = False

    # --- readers ---------------------------------------------------------
    def _read(self, attr, value):
        if self.gone:
            raise self._ps.NoSuchProcess(self.pid)
        if attr in self.deny:
            raise self._ps.AccessDenied(self.pid)
        return value

    def oneshot(self):
        import contextlib
        return contextlib.nullcontext()

    def name(self): return self._read("name", self.name_)
    def create_time(self): return self._read("create_time", self.create_time_)
    def ppid(self): return self._read("ppid", self.ppid_)
    def exe(self): return self._read("exe", self.exe_)
    def status(self): return self._read("status", self.status_)
    def cpu_times(self): return self._read("cpu_times", CpuTimes(self.user_, self.system_))
    def memory_info(self): return self._read("memory", MemInfo(self.rss_, self.rss_ * 2))
    def num_threads(self): return self._read("num_threads", 4)

    def cpu_percent(self, interval=None):
        self._read("cpu_percent", 0)
        return self.cpu_seq.pop(0) if len(self.cpu_seq) > 1 else self.cpu_seq[0]

    def nice(self, value=None):
        if value is None:               # reading is not an action
            return self.nice_
        self.calls.append(f"nice({value})")
        self.nice_ = value

    # --- actions (recorded, never real) ------------------------------------
    def terminate(self): self.calls.append("terminate"); self.alive = self.wait_times_out
    def kill(self): self.calls.append("kill"); self.alive = False; self.wait_times_out = False
    def suspend(self): self.calls.append("suspend"); self.status_ = "stopped"
    def resume(self): self.calls.append("resume"); self.status_ = "running"
    def is_running(self): return self.alive

    def wait(self, timeout=None):
        self.calls.append("wait")
        if self.wait_times_out:
            raise self._ps.TimeoutExpired(timeout)


def make_fake_psutil(cpu_count=4, total=16 * GB):
    class NoSuchProcess(Exception): pass
    class AccessDenied(Exception): pass
    class ZombieProcess(NoSuchProcess): pass
    class TimeoutExpired(Exception): pass

    class FakePsutil:
        pass

    ps = FakePsutil()
    ps.NoSuchProcess, ps.AccessDenied, ps.ZombieProcess, ps.TimeoutExpired = (
        NoSuchProcess, AccessDenied, ZombieProcess, TimeoutExpired)
    ps.BELOW_NORMAL_PRIORITY_CLASS = 16384
    ps.registry: Dict[int, FakeProc] = {}
    ps.system_cpu = 12.0
    ps.fail_listing = False

    class Process:
        def __new__(cls, pid):
            proc = ps.registry.get(pid)
            if proc is None or proc.gone:
                raise NoSuchProcess(pid)
            return proc

        def suspend(self): ...   # makes hasattr(ps.Process, "suspend") true

    ps.Process = Process
    ps.add = lambda pid, **kw: ps.registry.setdefault(pid, FakeProc(ps, pid, **kw))

    def process_iter():
        if ps.fail_listing:
            raise RuntimeError("listing failed")
        return list(ps.registry.values())

    ps.process_iter = process_iter
    ps.cpu_count = lambda logical=True: cpu_count
    ps.cpu_percent = lambda interval=None: ps.system_cpu
    ps.virtual_memory = lambda: VMem(total, total // 2, 50.0)
    return ps
