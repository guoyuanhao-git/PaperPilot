"""User-authored profile. Never inferred or overwritten by the assistant."""
from . import store

FIELDS = {
    'display_name': ('称呼', 80), 'gender': ('性别', 2), 'institution': ('学校-院系-实验室', 500),
    'school': ('学校', 200), 'department': ('院系', 120), 'laboratory': ('实验室', 120),
    'stage': ('当前阶段 / 身份', 120), 'education': ('教育背景', 3000),
    'research_directions': ('研究方向', 4000), 'current_projects': ('当前课题与进展', 4000),
    'skills': ('知识基础与技能', 3000), 'paper_taste': ('论文品味', 4000),
    'reading_preferences': ('解读偏好', 3000), 'goals': ('近期目标与现实约束', 3000),
    'personal_statement': ('个人陈述', 8000), 'mainline': ('研究主线', 100),
    'mainline_detail': ('主线补充', 320),
}


LIST_FIELDS = {'research_directions': 'research_direction_items', 'current_projects': 'current_project_items'}
EXTRA_FIELDS = {'mainlines', *LIST_FIELDS.values()}

def validate(value):
    if not isinstance(value, dict) or set(value) - (set(FIELDS) | EXTRA_FIELDS):
        raise ValueError('研究档案字段无效')
    result = {}
    for key, (label, limit) in FIELDS.items():
        text = value.get(key, '')
        if not isinstance(text, str) or len(text) > limit:
            raise ValueError(f'{label}最多 {limit} 字符')
        result[key] = text.strip()
        if key == 'gender' and result[key] not in ('', '男', '女', '秘密'):
            raise ValueError('性别请选择男、女、秘密，或留空')
    if not any(k in value for k in ('school', 'department', 'laboratory')):
        result['school'] = result['institution']
    result['institution'] = '-'.join(result[k] for k in ('school', 'department', 'laboratory') if result[k])
    for field, item_field in LIST_FIELDS.items():
        items = value.get(item_field)
        if items is None:
            items = [result[field]] if result[field] else []
        if not isinstance(items, list) or len(items) > 5 or any(not isinstance(item, str) for item in items):
            raise ValueError(f'{FIELDS[field][0]}最多填写 5 条')
        items = [item.strip() for item in items if item.strip()]
        joined = '\n'.join(items)
        if field in value and result[field] != joined:
            # Preserve edits from older clients, without guessing how to split prose.
            items = [result[field]] if result[field] else []
            joined = result[field]
        if len(joined) > FIELDS[field][1]:
            raise ValueError(f'{FIELDS[field][0]}合计最多 {FIELDS[field][1]} 字符')
        result[field], result[item_field] = joined, items
    lines = value.get('mainlines')
    if lines is None:
        lines = [{'title': result['mainline'], 'detail': result['mainline_detail']}] if result['mainline'] or result['mainline_detail'] else []
    if not isinstance(lines, list) or len(lines) > 3:
        raise ValueError('最多同时填写三条研究主线')
    checked = []
    for i, line in enumerate(lines):
        if not isinstance(line, dict) or set(line) - {'title', 'detail'}:
            raise ValueError('研究主线格式无效')
        row = {}
        for key, label, limit in [('title', '主线标题', 100), ('detail', '主线补充', 320)]:
            text = line.get(key, '')
            if not isinstance(text, str) or len(text) > limit:
                raise ValueError(f'第 {i+1} 条{label}最多 {limit} 字符')
            row[key] = text.strip()
        checked.append(row)
    # Old clients can still edit the first line without losing subsequent lines.
    if checked:
        for legacy, key in [('mainline', 'title'), ('mainline_detail', 'detail')]:
            if legacy in value and result[legacy] != checked[0][key]:
                checked[0][key] = result[legacy]
    result['mainlines'] = [row for row in checked if row['title'] or row['detail']]
    first = result['mainlines'][0] if result['mainlines'] else {}
    result['mainline'], result['mainline_detail'] = first.get('title', ''), first.get('detail', '')
    return result


def get():
    try:
        return validate({k: v for k, v in store.get('user_profile', 'manual').items() if k in FIELDS or k in EXTRA_FIELDS})
    except ValueError:
        return {**{key: '' for key in FIELDS}, 'mainlines': [], **{key: [] for key in LIST_FIELDS.values()}}


def save(value):
    value = validate(value)
    store.save('user_profile', {'id': 'manual', **value})
    return value


def context(value=None):
    value = get() if value is None else validate(value)
    sections = [f'{FIELDS[k][0]}：\n{v}' for k, v in value.items() if v and k in FIELDS and k not in ('display_name', 'gender', 'school', 'department', 'laboratory', 'mainline', 'mainline_detail', 'mainlines')]
    if value['mainlines']:
        sections.append('当前研究主线（同时参考，不默认第一条优先）：\n' + mainline_context(value))
    return '用户手动填写的资料（优先于推断；空白表示未知，不要沿用旧资料猜测）：\n' + ('\n\n'.join(sections) or '尚未填写，请根据本次问题回答，不假设其学历或研究领域。')


def mainline_context(value=None):
    value = get() if value is None else value
    return '\n\n'.join(f'主线 {i+1}：{line["title"] or "未填写标题"}' + (f'\n补充：{line["detail"]}' if line['detail'] else '')
                        for i, line in enumerate(value['mainlines']))


def save_display(value):
    if not isinstance(value, dict) or set(value) != {'display_name', 'gender'}:
        raise ValueError('请提供称呼和性别')
    with store.LOCK:
        return save({**get(), **value})


def save_research(value):
    if not isinstance(value, dict):
        raise ValueError('研究档案字段无效')
    with store.LOCK:
        current = get()
        return save({**value, 'display_name': current['display_name'], 'gender': current['gender']})
