import json
import unittest
from unittest.mock import patch
import test_core
from paperpilot import store

class MemoryHistory(unittest.TestCase):
    setUp = test_core.Core.setUp
    tearDown = test_core.Core.tearDown

    def test_memory_retains_old_evidence_when_summarizing_new_activity(self):
        from paperpilot import assistant_memory as memory
        memory.configure(True)
        memory.capture('科研对话', '只做模型，不做引擎', schedule=False)
        old = store.all_objects('memory_event')[0]
        observation = {'text': '主攻模型，不做引擎', 'evidence_ids': [old['id']]}
        with patch('paperpilot.providers.generate', return_value={'value': {'observations': [observation]}}):
            memory.summarize(store.settings(), memory.state()['epoch'], [old])
        for i in range(85):
            memory.capture('科研对话', f'工作进展 {i}', schedule=False)
        self.assertEqual(len(store.all_objects('memory_event')), 86)
        recent = sorted(store.all_objects('memory_event'), key=lambda e:e['at'])[-40:]
        with patch('paperpilot.providers.generate', return_value={'value': {'observations': [observation]}}) as generate:
            memory.summarize(store.settings(), memory.state()['epoch'], recent)
        payload = json.loads(generate.call_args.args[2][0]['content'])
        self.assertIn(old['id'], [e['id'] for e in payload['user_evidence']])
        self.assertIn('主攻模型', memory.context())
