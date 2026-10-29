"""Resolve Windows npm launchers without invoking a command shell."""
from pathlib import Path
import shutil


def command(binary):
    path = Path(binary)
    if path.suffix.lower() not in ('.cmd', '.bat'):
        return [binary]
    native = path.with_suffix('.exe')
    if native.is_file():
        return [str(native)]
    entry = path.parent / 'node_modules' / '@openai' / 'codex' / 'bin' / 'codex.js'
    node = path.parent / 'node.exe'
    node = str(node) if node.is_file() else shutil.which('node')
    if node and entry.is_file():
        return [node, str(entry)]
    raise ValueError('Codex CMD 包装器未找到对应的官方 Node 入口或原生可执行文件；请检查 CLI 安装。')


def process_job(process):
    """Own a Windows process tree; closing the handle reaps its descendants."""
    import os
    if os.name != 'nt':
        return None
    import ctypes
    from ctypes import wintypes as w
    class Basic(ctypes.Structure):
        _fields_ = [('ProcessTime', ctypes.c_longlong), ('JobTime', ctypes.c_longlong),
                    ('Flags', w.DWORD), ('MinWorkingSet', ctypes.c_size_t),
                    ('MaxWorkingSet', ctypes.c_size_t), ('ActiveProcesses', w.DWORD),
                    ('Affinity', ctypes.c_size_t), ('Priority', w.DWORD), ('Scheduling', w.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ('ReadOps','WriteOps','OtherOps','ReadBytes','WriteBytes','OtherBytes')]
    class Limits(ctypes.Structure):
        _fields_ = [('Basic',Basic),('IO',IO),('ProcessMemory',ctypes.c_size_t),
                    ('JobMemory',ctypes.c_size_t),('PeakProcessMemory',ctypes.c_size_t),('PeakJobMemory',ctypes.c_size_t)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
    kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.SetInformationJobObject.argtypes = [w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
    kernel.SetInformationJobObject.restype = w.BOOL
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE,w.HANDLE]
    kernel.AssignProcessToJobObject.restype = w.BOOL
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    handle = kernel.CreateJobObjectW(None,None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = Limits(); limits.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(handle,9,ctypes.byref(limits),ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(handle,w.HANDLE(int(process._handle))):
        error=ctypes.get_last_error(); kernel.CloseHandle(handle)
        raise ctypes.WinError(error)
    return lambda: kernel.CloseHandle(handle)
