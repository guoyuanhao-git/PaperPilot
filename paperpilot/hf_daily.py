"""Whole DailyPapers editions, with pagination and no model ranking."""
import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from . import discovery, store

LOCK = threading.Lock()
TTL = 900


def utcnow():
    return datetime.now(timezone.utc)


def validate_days(days):
    if isinstance(days, bool) or not isinstance(days, int) or days not in (1, 3):
        raise ValueError('DailyPapers 列表时间请选择近一天或近三天')
    return days


def edition(day):
    items, seen, page_signatures = [], set(), set()
    try:
        # A bound guards upstream pagination bugs. Reaching it is explicitly
        # incomplete, never silently presented as the whole edition.
        for page in range(100):
            url = 'https://huggingface.co/api/daily_papers?' + urlencode({'date':day, 'p':page, 'limit':100, 'sort':'publishedAt'})
            raw = discovery.public_fetch(url, {'huggingface.co'})
            rows = json.loads(raw)
            if not isinstance(rows, list):
                raise ValueError('DailyPapers 返回格式发生变化')
            if not rows:
                return items, {'source':'huggingface', 'date':day, 'ok':True, 'count':len(items), 'message':day + ' · 已读取完整每日列表'}
            parsed = discovery.hf_items(raw)
            if len(parsed) != len(rows):
                raise ValueError('部分论文记录格式无法识别，列表不完整')
            signature = tuple(p['id'] for p in parsed)
            if signature in page_signatures:
                raise ValueError('来源返回重复分页，列表可能不完整')
            page_signatures.add(signature)
            for paper in parsed:
                ident = re.sub(r'v\d+$', '', paper['id'])
                if ident in seen:
                    continue
                seen.add(ident)
                paper.update(listing_date=day, evidence_scope='DailyPapers 收录与原始摘要；未进行模型筛选，未读论文全文')
                items.append(paper)
        raise ValueError('来源分页未结束，请稍后刷新；当前列表不完整')
    except Exception as error:
        message = str(error)[:180] if isinstance(error, ValueError) else '来源暂时无法读取，请稍后刷新'
        return items, {'source':'huggingface', 'date':day, 'ok':False, 'count':len(items), 'message':day + ' · ' + message}


def collect(days, now=None):
    validate_days(days)
    now = now or utcnow()
    today = now.astimezone(ZoneInfo('Asia/Shanghai')).date()
    dates = [(today - timedelta(days=i)).isoformat() for i in range(days)]
    items, statuses, seen = [], [], set()
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks = [pool.submit(edition, day) for day in dates]
        for task in tasks:  # Preserve edition order, including empty weekend editions.
            rows, status = task.result()
            statuses.append(status)
            for paper in rows:
                ident = re.sub(r'v\d+$', '', paper['id'])
                if ident not in seen:
                    items.append(paper)
                    seen.add(ident)
    return {'id':uuid.uuid4().hex, 'days':days, 'dates':dates, 'updated_at':now.isoformat(), 'items':items,
            'source_status':statuses, 'complete':all(s['ok'] for s in statuses)}


def refresh(days, force=False):
    validate_days(days)
    with LOCK:
        now = utcnow()
        today = now.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
        previous = next((r for r in store.all_objects('hf_listing') if r.get('days')==days and r.get('dates',[])[:1]==[today]), None)
        if previous and previous.get('complete'):
            age = (now - datetime.fromisoformat(previous['updated_at'])).total_seconds()
            if 0 <= age < (10 if force else TTL):
                return previous
        result = collect(days, now)
        # On partial failure retain known cards from the same dates, clearly marked.
        if previous:
            failed = {s['date'] for s in result['source_status'] if not s['ok']}
            seen = {p['id'] for p in result['items']}
            for paper in previous['items']:
                if paper['listing_date'] in failed and paper['id'] not in seen:
                    result['items'].append({**paper, 'listing_cached':True})
        result['items'].sort(key=lambda p:p['listing_date'], reverse=True)
        store.save('hf_listing', result)
        # Keep bounded trusted snapshots for favorites and optional translations.
        for old in store.all_objects('hf_listing')[12:]:
            store.remove('hf_listing', old['id'])
        return result
