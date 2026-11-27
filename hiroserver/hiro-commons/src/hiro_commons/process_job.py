"""A child process tree that ends with the process holding it: a Windows job object with "kill on close".

Windows keeps only a parent pid per process: once a launcher in the middle of a tree ends (``uv run``, a venv's
``python.exe``, an entry point's ``.exe``), its children can no longer be found from the process that started it, and
they keep running after it ends, however it ends (a forced kill included). A job holds the whole tree: a process
started by a process in the job is in it too, ``terminate()`` ends every process in it, and when the last handle to
the job closes (the holder ends, even killed) Windows ends them all.

Linux and macOS use a process group instead (``start_new_session=True``, then ``killpg``): there ``ProcessJob`` holds
nothing and ``terminate()`` does nothing.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from hiro_commons.log import Logger

log = Logger.get("PROCESS")

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001


class _BasicLimits(ctypes.Structure):
    _fields_ = [  # noqa: RUF012 — ctypes' own declaration
        ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (  # noqa: RUF012 — ctypes' own declaration
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [  # noqa: RUF012 — ctypes' own declaration
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _kernel32() -> ctypes.WinDLL:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    k32.SetInformationJobObject.restype = wintypes.BOOL
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.AssignProcessToJobObject.restype = wintypes.BOOL
    k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k32.TerminateJobObject.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    return k32


class ProcessJob:
    """One child's process tree, held so that it ends with this process (Windows); nothing elsewhere.

    ``hold(pid)`` right after starting the child: what the child starts afterwards joins the job by itself. A
    failure is a WARNING and the child runs unheld: the tree kill and the start's sweep still end it.
    """

    def __init__(self, what: str) -> None:
        self._what = what
        self._handle: int | None = None

    @property
    def holding(self) -> bool:
        return self._handle is not None

    def hold(self, pid: int) -> bool:
        if sys.platform != "win32":
            return False
        k32 = _kernel32()
        job = k32.CreateJobObjectW(None, None)  # no security attributes: the handle isn't inherited by children
        if not job:
            log.warning(f"⚠️ Could not make a job for {self._what}: it would outlive a forced stop", error=ctypes.get_last_error())
            return False
        info = _ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        proc = None
        try:
            if not k32.SetInformationJobObject(job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)):
                raise OSError(ctypes.get_last_error(), "SetInformationJobObject")
            proc = k32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
            if not proc:
                raise OSError(ctypes.get_last_error(), "OpenProcess")
            if not k32.AssignProcessToJobObject(job, proc):
                raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject")
        except OSError as exc:
            k32.CloseHandle(job)
            log.warning(f"⚠️ Could not hold {self._what} in a job: it would outlive a forced stop", pid=pid, error=str(exc))
            return False
        finally:
            if proc:
                k32.CloseHandle(proc)
        self._handle = job
        return True

    def terminate(self) -> None:
        """End every process in the job (the child and all it started), then let the job go."""
        if self._handle is None:
            return
        k32 = _kernel32()
        if not k32.TerminateJobObject(self._handle, 1):
            log.warning(f"⚠️ Could not end {self._what}'s processes through its job", error=ctypes.get_last_error())
        self.close()

    def close(self) -> None:
        """Let the job go: with kill on close, any process still in it ends now."""
        if self._handle is None:
            return
        _kernel32().CloseHandle(self._handle)
        self._handle = None
