import copy
import unittest
from paperpilot import reasoning, providers, reading, store


class Reasoning(unittest.TestCase):
    def test_group_overrides_map_identically_for_both_providers(self):
        config = copy.deepcopy(store.DEFAULTS)
        before = copy.deepcopy(config)
        for group in reasoning.GROUPS:
            for level, pair in reasoning.LEVELS.items():
                source = copy.deepcopy(config)
                source['reasoning_policy'] = {'custom_enabled': True, 'overrides': {group: level}}
                for provider in ('codex', 'deepseek'):
                    source['provider'] = provider
                    for scene, target in reasoning.TASK_GROUPS.items():
                        if target != group:
                            continue
                        result = reasoning.for_task(source, scene)
                        self.assertEqual((result['codex_reasoning_effort'], result['deepseek']['thinking']), pair)
        self.assertEqual(config, before)

    def test_recommended_switch_preserves_custom_choices_but_uses_recommendation(self):
        config = copy.deepcopy(store.DEFAULTS)
        config['reasoning_policy'] = {'custom_enabled': True, 'overrides': {'overview': 'high', 'study': 'low'}}
        self.assertEqual(reasoning.effective(config)['overview'], 'high')
        self.assertEqual(reasoning.effective(config)['deep'], 'low')
        config['reasoning_policy']['custom_enabled'] = False
        self.assertEqual(reasoning.effective(config), reasoning.DEFAULTS)
        self.assertEqual(config['reasoning_policy']['overrides']['overview'], 'high')
        config['reasoning_policy']['custom_enabled'] = True
        self.assertEqual(reasoning.effective(config)['overview'], 'high')

    def test_fixed_tasks_cannot_be_overridden_and_memory_is_standard(self):
        config = copy.deepcopy(store.DEFAULTS)
        config['reasoning'] = {scene: 'high' for scene in reasoning.DEFAULTS}
        for task, level in reasoning.FIXED.items():
            self.assertEqual(reasoning.effective(config)[task], level)
            with self.assertRaises(ValueError):
                reasoning.validate_policy({'custom_enabled': True, 'overrides': {task: 'high'}})
        memory = reasoning.for_task(config, 'memory')
        self.assertEqual(memory['codex_reasoning_effort'], 'medium')
        self.assertEqual(memory['deepseek']['thinking'], 'low')

    def test_invalid_policy_is_rejected(self):
        for value in (None, [], {}, {'custom_enabled': 1, 'overrides': {}},
                      {'custom_enabled': True, 'overrides': {'study': []}},
                      {'custom_enabled': True, 'overrides': {'study': 'xhigh'}}):
            with self.assertRaises(ValueError):
                reasoning.validate_policy(value)

    def test_migration_preserves_intentional_preferences_only(self):
        old = {'reasoning': {**reasoning.DEFAULTS, 'research': 'high', 'memory': 'low'}}
        self.assertEqual(reasoning.migrate(old), reasoning.default_policy())
        old['reasoning'].update(overview='high', memory='high')
        self.assertEqual(reasoning.migrate(old), {'custom_enabled': True, 'overrides': {'overview': 'high'}})
        self.assertEqual(reasoning.migrate({'reasoning_policy': {'custom_enabled': True, 'overrides': {'assist': 'high', 'study': 'low'}}})['overrides'], {'study': 'low'})
        old['knowledge_deep_thinking'] = True
        self.assertEqual(reasoning.migrate(old)['overrides']['knowledge'], 'high')

    def test_reading_and_auxiliary_tasks_are_independent(self):
        config = copy.deepcopy(store.DEFAULTS)
        config['reasoning_policy'] = {'custom_enabled': True, 'overrides': {'overview': 'low', 'study': 'high'}}
        for provider in ('codex', 'deepseek'):
            config['provider'] = provider
            for mode, level in [('overview', 'low'), ('detailed', 'high'), ('deep', 'high')]:
                routed = providers.reading_config(config, mode)
                self.assertEqual((routed['codex_reasoning_effort'], routed['deepseek']['thinking']), reasoning.LEVELS[level])
            detailed = providers.reading_config(config, 'deep')
            for stage, level in [('翻译论文原始摘要','low'), ('修复 JSON 格式','low'), ('串联方法的图文论证 1/1','high')]:
                result = reading.stage_config(detailed, stage)
                self.assertEqual((result['codex_reasoning_effort'], result['deepseek']['thinking']), reasoning.LEVELS[level])
                if provider == 'deepseek' and stage.startswith('修复'):
                    self.assertEqual(providers.output_limit(result), providers.output_limit(detailed))
