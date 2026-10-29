"""Local conference catalog, personal focus and weekly official-source checks."""
import json
import re
import time
from datetime import datetime, date, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from pathlib import Path
from . import store

REGISTRY = json.loads(Path(__file__).with_name('conference_registry.json').read_text())
TZ = timezone(timedelta(hours=8))
MAX_BYTES = 2 * 1024 * 1024


def validate(value, previous=None):
    if not isinstance(value, dict) or value.get('schemaVersion') != 2 or type(value.get('revision')) is not int:
        raise ValueError('请选择完整会议目录（版本 2）')
    series = value.get('series')
    if not isinstance(series, list) or not 1 <= len(series) <= 100 or not isinstance(value.get('updates'), list):
        raise ValueError('会议目录缺少会议或更新记录')
    for update in value['updates']:
        if not isinstance(update, dict) or ('checks' in update and not isinstance(update['checks'], list)):
            raise ValueError('会议更新记录格式无效')
        for check in update.get('checks', []):
            if not isinstance(check, dict) or not isinstance(check.get('id'), str):
                raise ValueError('会议核查记录格式无效')
    ids = set()
    for item in series:
        ident = item.get('id', '')
        if not re.fullmatch(r'[a-z0-9-]{1,60}', ident) or ident in ids:
            raise ValueError('会议标识无效或重复')
        ids.add(ident)
        if any(not isinstance(item.get(k), str) for k in ('name', 'rank', 'topics', 'group')):
            raise ValueError('会议资料不完整')
        if item['rank'] not in ('A', 'B', 'C', 'N'):
            raise ValueError('CCF 分类无效')
        if not isinstance(item.get('editions'), list) or not 1 <= len(item['editions']) <= 100:
            raise ValueError('缺少届次资料')
        years = set()
        for e in item['editions']:
            if type(e.get('year')) is not int or not 2000 <= e['year'] <= 2100 or e['year'] in years:
                raise ValueError('届次无效或重复')
            years.add(e['year'])
            u = urlsplit(e.get('source', ''))
            if u.scheme != 'https' or not u.hostname or u.username or u.password:
                raise ValueError('官方来源地址无效')
            proofs = e.get('sourceProofs', [])
            if not isinstance(proofs, list) or len(proofs) > 100:
                raise ValueError('官方依据格式无效')
            for proof in proofs:
                if not isinstance(proof, dict):
                    raise ValueError('官方依据格式无效')
                address = urlsplit(proof.get('url', ''))
                if address.scheme != 'https' or not address.hostname or address.username or address.password:
                    raise ValueError('官方依据地址无效')
            if e.get('announcement') not in ('cfp', 'meeting', 'unverified') or e.get('entryKey') not in (None, 'abstract', 'paper') or e.get('paperAudience') not in ('all', 'registered', 'invited'):
                raise ValueError('投稿阶段规则无效')
            if e.get('verification') not in ('verified', 'notlisted', 'failed', 'conflict') or not e.get('evidence'):
                raise ValueError('缺少核查依据')
            try:
                if e.get('checked'):
                    date.fromisoformat(e['checked'])
                elif e['announcement'] != 'unverified':
                    raise ValueError('缺少核查日期')
                ZoneInfo(e['zone'])
                for key in ('abstract', 'paper'):
                    if e.get(key):
                        if datetime.fromisoformat(e[key].replace('Z', '+00:00')).tzinfo is None:
                            raise ValueError('缺少时区')
                    if e.get(key + 'Day'):
                        date.fromisoformat(e[key + 'Day'])
                    if e.get(key) and e.get(key + 'Day'):
                        raise ValueError('日期重复')
                if e.get('entryKey') and (e['announcement'] != 'cfp' or not (e.get(e['entryKey']) or e.get(e['entryKey'] + 'Day'))):
                    raise ValueError('缺少首次投稿日期')
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError('会议日期或时区无效') from exc
    if previous:
        if value['revision'] < previous['revision']:
            raise ValueError('导入版本较旧，现有目录已保留')
        if value['revision'] == previous['revision'] and value != previous:
            raise ValueError('同一修订号内容不一致，现有目录已保留')
        for old in previous['series']:
            new = next((s for s in series if s['id'] == old['id']), None)
            if not new:
                raise ValueError('不能丢失已有会议系列')
            for edition in old['editions']:
                updated = next((e for e in new['editions'] if e['year'] == edition['year']), None)
                if not updated:
                    raise ValueError('不能丢失历届记录')
                for k in ('abstract', 'paper', 'abstractDay', 'paperDay'):
                    if edition.get(k) and not updated.get(k) and not (k.endswith('Day') and updated.get(k[:-3])):
                        raise ValueError('不能清空已确认日期')
    return value


def saved():
    try:
        return store.get('conference_catalog', 'current')
    except ValueError:
        return {}


def import_catalog(value):
    if len(json.dumps(value)) > MAX_BYTES:
        raise ValueError('会议目录过大')
    with store.LOCK:
        catalog = validate(value, saved().get('catalog'))
        store.save('conference_catalog', {'id': 'current', 'catalog': catalog, 'checked_at': time.time()})
    return current(refresh=False)


def initialize():
    """Only series metadata/official entry points are bundled, never seed deadlines."""
    with store.LOCK:
        if saved().get('catalog'):
            return
        series = []
        for row in REGISTRY:
            entry = {k: row[k] for k in ('id', 'name', 'rank', 'topics', 'group')}
            entry['editions'] = [{'year': row['start_year'], 'source': row['sources'][0],
                'announcement': 'unverified', 'verification': 'notlisted', 'checked': None,
                'entryKey': None, 'paperAudience': 'all', 'zone': 'UTC', 'zoneLabel': '',
                'abstract': None, 'paper': None, 'abstractDay': None, 'paperDay': None,
                'evidence': '尚未核查官网', 'note': ''}]
            series.append(entry)
        catalog = {'schemaVersion': 2, 'revision': 0, 'series': series, 'updates': [],
                   'updatedAt': None, 'lastRunAt': None}
        store.save('conference_catalog', {'id': 'current', 'catalog': catalog})


def configuration():
    try:
        return store.get('conference_schedule', 'current')
    except ValueError:
        return {'id': 'current', 'enabled': False}


def configure(enabled):
    if type(enabled) is not bool:
        raise ValueError('自动核查设置无效')
    with store.LOCK:
        config = configuration()
        config['enabled'] = enabled
        store.save('conference_schedule', config)
    return current()


def active_job():
    return next((j for j in store.all_objects('job') if j.get('kind') == 'conferences'
                 and j.get('status') in ('queued', 'running')), None)


def current(refresh=False, force=False):
    # GET is local-only, even for old clients still sending ?refresh=1.
    initialize()
    cached = saved()
    try:
        focused = store.get('conference_focus', 'current').get('series_id')
    except ValueError:
        focused = None
    job = active_job()
    return {'catalog': cached.get('catalog'), 'focus': focused, 'error': cached.get('error', ''),
            'schedule': configuration(),
            'job': {k: job[k] for k in ('id','status','progress')} if job else None}


def start_check():
    from . import service, conference_update
    with store.LOCK:
        initialize()
        existing = active_job()
        if existing:
            return existing
        job = service.job('conferences', conference_update.run)
        config = configuration()
        config.update(job_id=job['id'], checked_slot=weekly_slot().isoformat())
        store.save('conference_schedule', config)
        return job


def weekly_slot(moment=None):
    moment = (moment or datetime.now(TZ)).astimezone(TZ)
    latest = (moment - timedelta(days=(moment.weekday()-6) % 7)).replace(hour=10, minute=0, second=0, microsecond=0)
    return latest if latest <= moment else latest - timedelta(days=7)


def tick(moment=None):
    with store.LOCK:
        config = configuration()
        if not config['enabled'] or config.get('checked_slot') == weekly_slot(moment).isoformat():
            return
        # Foreground reading jobs take priority; no reservation until idle.
        if any(j.get('status') in ('queued', 'running') for j in store.all_objects('job')):
            return
        job = start_check()
        config = configuration()
        config['checked_slot'] = weekly_slot(moment).isoformat()
        store.save('conference_schedule', config)
        return job


def focus(series_id):
    ids = {s['id'] for s in saved().get('catalog', {}).get('series', [])}
    if series_id is not None and series_id not in ids:
        raise ValueError('会议不存在，请刷新目录')
    store.save('conference_focus', {'id': 'current', 'series_id': series_id})
    return {'focus': series_id}
