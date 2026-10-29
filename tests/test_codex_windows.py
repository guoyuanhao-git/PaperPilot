import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
from paperpilot import model_setup, store


class WindowsCodexSetup(unittest.TestCase):
    def test_powershell_uses_server_python_and_literal_project_path(self):
        with tempfile.TemporaryDirectory() as directory:
            with store.scope({'id':'a'*32,'directory':Path(directory),'codex_mode':'isolated'}):
                store.init()
                # Mock only the module's platform view. Patching os.name itself
                # changes pathlib globally and makes WindowsPath fail on macOS.
                platform = SimpleNamespace(name='nt', environ=model_setup.os.environ)
                with patch.object(model_setup.providers,'capabilities',return_value={'keys':{'deepseek':False}}), patch.object(model_setup,'os',platform), patch.object(store,'ROOT') as project:
                    project.resolve.return_value = "D:/中文 user's project"
                    result=model_setup.public(62328)
                command=result['commands']['codex']
                self.assertIn("Set-Location -LiteralPath 'D:", command)
                self.assertIn("user''s project", command)
                self.assertIn("; & '", command)
                self.assertIn("' -X utf8 -m paperpilot.model_setup codex", command)
                self.assertIn('--account '+ 'a'*32,command)
                self.assertIn('--port 62328',command)


    def test_checkpoint_uses_short_temporary_name(self):
        from paperpilot.reading_checkpoint import Checkpoints
        with tempfile.TemporaryDirectory() as tmp, patch.object(store, 'DATA', Path(tmp)):
            checkpoint=Checkpoints('a'*20)
            result={'value':'中文','usage':{},'model':'fixture','provider':'fixture'}
            checkpoint.stage('b'*64,result)
            checkpoint.advance()
            self.assertEqual(checkpoint.get('b'*64)['value'],'中文')
            self.assertFalse(list((Path(tmp)/'drafts').glob('*.tmp')))

    def test_npm_cmd_resolves_without_shell_and_preserves_arguments(self):
        import json, os
        from paperpilot import cancellation, codex_runtime
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"中文 & user's CLI";root.mkdir()
            wrapper=root/'codex.cmd';wrapper.write_text('@echo off',encoding='ascii')
            entry=root/'node_modules/@openai/codex/bin/codex.js';entry.parent.mkdir(parents=True)
            entry.write_text('console.log(JSON.stringify(process.argv.slice(2)))',encoding='utf-8')
            args=['中文 空格', 'a&b|c', '"quoted"', '%PATH%', '$literal']
            result=cancellation.run_process([*codex_runtime.command(str(wrapper)),*args],env=dict(os.environ),input='',timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout),args)
            entry.unlink()
            with self.assertRaises(ValueError):codex_runtime.command(str(wrapper))

    def test_windows_job_reaps_descendants_on_cancel_and_timeout(self):
        import ctypes, os, shutil, subprocess, threading
        from paperpilot import cancellation
        if os.name!='nt':self.skipTest('Windows Job Object')
        for cancel in (False,True):
            with self.subTest(cancel=cancel), tempfile.TemporaryDirectory() as tmp:
                pidfile=Path(tmp)/'child.pid'
                script="const cp=require('child_process'),fs=require('fs');setTimeout(()=>{let c=cp.spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'ignore'});fs.writeFileSync(process.argv[1],String(c.pid));},100);setInterval(()=>{},1000)"
                control=cancellation.Control();token=cancellation.CURRENT.set(control)
                timer=threading.Timer(1.5,control.cancel) if cancel else None
                if timer:timer.start()
                try:
                    with self.assertRaises(cancellation.Cancelled if cancel else subprocess.TimeoutExpired):
                        cancellation.run_process([shutil.which('node'),'-e',script,str(pidfile)],env=dict(os.environ),input='',timeout=8 if cancel else 1.5)
                finally:
                    cancellation.CURRENT.reset(token)
                    if timer:timer.cancel();timer.join()
                self.assertTrue(pidfile.exists())
                pid=int(pidfile.read_text())
                kernel=ctypes.WinDLL('kernel32',use_last_error=True)
                kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];kernel.OpenProcess.restype=ctypes.c_void_p
                kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
                kernel.CloseHandle.argtypes=[ctypes.c_void_p]
                handle=kernel.OpenProcess(0x100000,False,pid)
                if handle:
                    try:self.assertEqual(kernel.WaitForSingleObject(handle,3000),0)
                    finally:kernel.CloseHandle(handle)
