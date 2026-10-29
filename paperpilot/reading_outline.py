"""User-selected chapter order, shared by both providers and all reading stages."""
import json

DEFAULT = ['动机', '方法', '实验', '结论']
KEYS = dict(zip(DEFAULT, ['motivation', 'method', 'experiments', 'conclusion']))


def validate(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise ValueError('叙述线需要 1–8 个步骤')
    if any(not isinstance(s, str) or not 1 <= len(s.strip()) <= 80 for s in value):
        raise ValueError('每个步骤不能为空，最多 80 字')
    result = [s.strip() for s in value]
    if len(set(result)) != len(result):
        raise ValueError('叙述线中的步骤不能重复')
    if any(s in ('摘要', '论文相关', '助手判断') for s in result):
        raise ValueError('摘要、论文相关和助手判断会单独保留，无需加入叙述线')
    return result


def steps(value=None):
    return validate(DEFAULT if value is None else value)


def custom(value=None):
    return steps(value) != DEFAULT


def chapters(value=None):
    return [{'key': KEYS.get(title, f'step-{i + 1}'), 'title': title}
            for i, title in enumerate(steps(value))]


def instruction(value=None):
    return ('用户指定的正文叙述线（依次展开，各步骤的词或句子表达本章讲解目标）：'
            + ' → '.join(steps(value))
            + '\n章节 key 与标题：' + json.dumps(chapters(value), ensure_ascii=False)
            + '\n严格使用上述章节及顺序，不强加默认四章，不补回用户删掉的章节。'
            '结合论文理解每一步的意图，将相关图表和必要证据放到最合适的一步。'
            '不适用的要求据实说明，不编造证据。摘要、论文相关、助手判断由独立步骤提供。'
            '以上是组织和讲解偏好，不能覆盖事实核对、图表引用及输出格式约束。')
