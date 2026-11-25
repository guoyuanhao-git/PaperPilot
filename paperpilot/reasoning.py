"""Shared task policy; account settings customize reading and graph effort only."""
import copy

LEVELS = {'low': ('low', 'disabled'), 'medium': ('medium', 'low'), 'high': ('high', 'high')}
GROUPS = {'overview': 'medium', 'study': 'high', 'knowledge': 'medium', 'translation': 'medium'}
TASK_GROUPS = {'overview': 'overview', 'detailed': 'study', 'deep': 'study',
               'knowledge': 'knowledge', 'translation': 'translation'}
FIXED = {'lookup': 'low', 'hotspots': 'low', 'metadata': 'low', 'memory': 'medium',
         'chat': 'medium', 'recommendation': 'medium', 'research': 'medium'}
DEFAULTS = {**{task: GROUPS[group] for task, group in TASK_GROUPS.items()}, **FIXED}


def default_policy():
    return {'custom_enabled': False, 'overrides': {}}


def validate_policy(value):
    if not isinstance(value, dict) or set(value) != {'custom_enabled', 'overrides'}:
        raise ValueError('请提供完整的思考配置')
    if type(value['custom_enabled']) is not bool or not isinstance(value['overrides'], dict):
        raise ValueError('自定义配置应包含启用开关和场景档位')
    if set(value['overrides']) - set(GROUPS):
        raise ValueError('该场景由工具自动管理，不能调整档位')
    if any(not isinstance(level, str) or level not in LEVELS for level in value['overrides'].values()):
        raise ValueError('思考档位应为 low、medium 或 high')
    return copy.deepcopy(value)


def migrate(saved):
    """Preserve intentional old overrides; never migrate tuning of managed tasks."""
    if 'reasoning_policy' in saved:
        policy = copy.deepcopy(saved['reasoning_policy'])
        # The former assist group is now a managed core feature.
        if isinstance(policy, dict) and isinstance(policy.get('overrides'), dict):
            policy['overrides'].pop('assist', None)
        return validate_policy(policy)
    old_defaults = {**DEFAULTS, 'research': 'high', 'memory': 'low'}
    old = saved.get('reasoning') or {}
    overrides = {}
    for task, group in TASK_GROUPS.items():
        level = old.get(task)
        if isinstance(level, str) and level in LEVELS and level != old_defaults[task]:
            # Merged groups use the strongest of conflicting intentional overrides.
            prior = overrides.get(group)
            if prior is None or list(LEVELS).index(level) > list(LEVELS).index(prior):
                overrides[group] = level
    if saved.get('knowledge_deep_thinking'):
        overrides['knowledge'] = 'high'
    return {'custom_enabled': bool(overrides), 'overrides': overrides}


def group_levels(config):
    policy = migrate(config)
    return {**GROUPS, **(policy['overrides'] if policy['custom_enabled'] else {})}


def effective(config):
    groups = group_levels(config)
    return {**{task: groups[group] for task, group in TASK_GROUPS.items()}, **FIXED}


def for_level(config, level):
    codex, deepseek = LEVELS[level]
    result = copy.deepcopy(config)
    result['codex_reasoning_effort'] = codex
    result['deepseek']['thinking'] = deepseek
    return result


def for_task(config, scene):
    if scene not in DEFAULTS:
        raise ValueError('未知的思考场景')
    return for_level(config, effective(config)[scene])
