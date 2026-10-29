"""Per-account weekly catch-up; compare graph inputs without calling a model."""
from datetime import datetime, timedelta, timezone
import re

from . import knowledge, store

TZ = timezone(timedelta(hours=8))
ACTIVE = ('queued', 'running')


def now():
    return datetime.now(TZ)


def saved(kind, ident):
    try:
        return store.get(kind, ident)
    except ValueError:
        return {}


def settings():
    return {'id': 'current', 'enabled': False, 'weekday': 6, 'time': '10:00',
            **saved('knowledge_schedule', 'current')}


def slot(config, moment):
    local = moment.astimezone(TZ)
    hour, minute = map(int, config['time'].split(':'))
    deadline = (local - timedelta(days=(local.weekday() - config['weekday']) % 7)).replace(
        hour=hour, minute=minute, second=0, microsecond=0)
    return deadline if deadline <= local else deadline - timedelta(days=7)


def configure(value):
    enabled, weekday, time = value.get('enabled'), value.get('weekday'), value.get('time')
    if type(enabled) is not bool or type(weekday) is not int or not 0 <= weekday <= 6:
        raise ValueError('请选择是否自动更新及每周更新时间')
    if not isinstance(time, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', time):
        raise ValueError('请填写有效的更新时间')
    with knowledge.LOCK:
        config = settings()
        changed = any(config[k] != value[k] for k in ('enabled', 'weekday', 'time'))
        config.update(enabled=enabled, weekday=weekday, time=time)
        if changed:
            config.pop('checked_slot', None)
        store.save('knowledge_schedule', config)
    return status()


def stale(graph, papers, key):
    if not graph or graph.get('fingerprint') != knowledge.fingerprint(papers):
        return True
    signature = knowledge.digest(knowledge.research_context(key))
    if 'research_signature' in graph:
        return graph['research_signature'] != signature
    # Older graphs only recorded the full model/profile signature. Compare using
    # their saved provider/model, not the currently selected provider snapshot.
    config = knowledge.config(key)
    config['provider'] = graph.get('provider', config['provider'])
    if config['provider'] == 'codex':
        config['model'] = graph.get('model', '')
        if config['model'] == 'gpt-6.1-sol' and not store.settings().get('model'):
            config['model'] = ''
    else:
        config['deepseek']['model'] = graph.get('model', config['deepseek']['model'])
    return graph.get('config_signature') != knowledge.config_signature(config)


def plan():
    papers = knowledge.members()
    core_papers = [p for p in papers if knowledge.is_core_paper(p)]
    core = saved('knowledge', 'core:starred')
    core_pending = bool(papers or core) and stale(core, core_papers, knowledge.CORE_KEY)
    lines = []
    for line in knowledge.mainline_options():
        graph = saved('knowledge', knowledge.namespaced('current', line['key']))
        if (papers or graph) and (core_pending or stale(graph, papers, line['key']) or
                                 graph.get('core_signature') != knowledge.structure_signature(core)):
            lines.append(line)
    return {'core': core_pending, 'mainlines': lines}


def running():
    return next((j for j in store.all_objects('job') if j.get('kind') in ('knowledge', 'knowledge-auto')
                 and j.get('status') in ACTIVE), None)


def status(moment=None):
    moment = moment or now()
    config = settings()
    deadline = slot(config, moment)
    pending = plan()
    job = saved('job', config.get('job_id', ''))
    active = running()
    dirty = pending['core'] or bool(pending['mainlines'])
    failed = bool(job.get('status') == 'failed' and dirty)
    state = 'running' if active else 'failed' if failed else 'pending' if dirty else 'synced'
    due = config.get('checked_slot') != deadline.isoformat()
    return {**{k: config[k] for k in ('enabled', 'weekday', 'time')}, 'timezone': 'Asia/Shanghai',
            'state': state, 'pending_core': pending['core'],
            'pending_mainlines': [line['title'] for line in pending['mainlines']],
            'due': due, 'next_at': (deadline if due and not failed else deadline + timedelta(days=7)).isoformat(),
            'last_checked_at': config.get('last_checked_at'), 'last_success_at': config.get('last_success_at'),
            'progress': active.get('progress', '') if active else '',
            'error': job.get('error', '') if failed else '', 'job_id': config.get('job_id'),
            'job_status': job.get('status'), 'finished_at': job.get('finished_at')}


def work(progress):
    from . import service
    completed = []
    if not settings()['enabled']:
        return {'paused': True}
    pending = plan()
    if pending['core']:
        progress('每周整理 · 更新领域骨架')
        knowledge.build_graph(progress, 'starred', configuration=knowledge.config(knowledge.CORE_KEY))
        completed.append('领域图谱')
    # Re-evaluate after the core is committed. All dependent mainlines now reuse it.
    errors = []
    for line in plan()['mainlines']:
        if not settings()['enabled']:
            return {'paused': True, 'updated': completed}
        try:
            progress('每周整理 · ' + line['title'])
            knowledge.build_graph(progress, 'all', configuration=knowledge.config(line['key']))
            completed.append(line['title'])
        except ValueError as exc:
            errors.append(line['title'] + '：' + str(exc))
    if errors:
        raise ValueError('；'.join(errors)[:650])
    with knowledge.LOCK:
        config = settings()
        config['last_success_at'] = service.now()
        store.save('knowledge_schedule', config)
    return {'updated': completed}


def tick(moment=None, retry=False):
    """Reserve one weekly slot before enqueueing, also on no-op checks/failures."""
    from . import service
    moment = moment or now()
    with knowledge.LOCK:
        config = settings()
        if not config['enabled']:
            if retry:
                raise ValueError('请先开启每周自动更新')
            return None
        deadline = slot(config, moment).isoformat()
        if not retry and config.get('checked_slot') == deadline:
            return None
        if running() or any(j.get('status') in ACTIVE for j in store.all_objects('job')):
            if retry:
                raise ValueError('当前有任务正在进行，完成后再重试')
            return None  # Do not consume the slot while busy.
        pending = plan()
        config.update(checked_slot=deadline, last_checked_at=moment.isoformat())
        store.save('knowledge_schedule', config)
        if not pending['core'] and not pending['mainlines']:
            return None
        job = service.job('knowledge-auto', work)
        config['job_id'] = job['id']
        store.save('knowledge_schedule', config)
        return job
