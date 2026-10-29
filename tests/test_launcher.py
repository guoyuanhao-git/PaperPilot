import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from paperpilot import launcher, store


class Launcher(unittest.TestCase):
    def test_reuses_same_project_but_refuses_other_project(self):
        with patch.object(launcher,'health',return_value={'instance':launcher.identity()}), patch.object(launcher,'show') as show, patch.object(launcher.subprocess,'Popen') as spawn:
            launcher.start();show.assert_called_once();spawn.assert_not_called()
        with patch.object(launcher,'health',return_value={'instance':'another project'}), patch.object(launcher,'show') as show:
            with self.assertRaisesRegex(ValueError,'另一个'):launcher.start()
            show.assert_not_called()

    def test_stop_checks_instance_nonce_pid_and_active_work(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(store,'DATA',Path(tmp)):
            directory=Path(tmp)/'desktop';directory.mkdir()
            path=directory/'process.json';path.write_text(json.dumps({'pid':1234,'port':8765,'nonce':'owned'}))
            valid={'instance':launcher.identity(),'desktop_nonce':'owned','pid':1234,'busy':False}
            for overrides in ({'pid':999},{'desktop_nonce':'wrong'},{'instance':'wrong'},{'busy':True}):
                with patch.object(launcher,'health',return_value={**valid,**overrides}),patch.object(launcher.os,'kill') as kill:
                    with self.assertRaises(ValueError):launcher.stop()
                    kill.assert_not_called()
            with patch.object(launcher,'health',side_effect=[valid,None]),patch.object(launcher.os,'kill') as kill:
                launcher.stop();kill.assert_called_once_with(1234,launcher.signal.SIGTERM)
            self.assertFalse(path.exists())

    def test_records_health_pid_instead_of_wrapper_pid(self):
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as tmp, patch.object(store, 'DATA', Path(tmp)):
            process = MagicMock(pid=111)
            def healthy(port):
                nonce = spawn.call_args.kwargs['env']['PAPERPILOT_DESKTOP_NONCE']
                return {'instance': launcher.identity(), 'desktop_nonce': nonce, 'pid': 222}
            with patch.object(launcher, 'health', side_effect=[None, None]), patch.object(launcher, 'show'), patch.object(launcher.subprocess, 'Popen', return_value=process) as spawn:
                launcher.health.side_effect = lambda port: healthy(port) if spawn.called else None
                launcher.start(8766)
            state = json.loads((Path(tmp) / 'desktop/process.json').read_text(encoding='utf-8'))
            self.assertEqual(state['pid'], 222)
