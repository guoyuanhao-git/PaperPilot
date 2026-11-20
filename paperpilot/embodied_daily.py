"""Read-only connection to Embodied DailyPapers; all personal actions stay local."""
import json
import os
import re
import time
import uuid
import urllib.request
from datetime import date, datetime
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo
from . import store

DEFAULT_URL = 'https://ipplab.github.io/embodied-ai-daily-papers'
MAX_BYTES = 12 * 1024 * 1024


def base_url():
    value = os.environ.get('PAPERPILOT_EMBODIED_DAILY_URL', DEFAULT_URL).rstrip('/')
    parts = urlsplit(value)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('具身日报地址配置无效')
    return value


def links():
    return {'home': base_url() + '/?lang=zh'}


def fetch(path):
    url = base_url() + path
    class SameOrigin(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if urlsplit(newurl)[:2] != urlsplit(url)[:2]:
                raise ValueError('具身日报重定向到了其他站点')
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    opener = urllib.request.build_opener(SameOrigin())
    with opener.open(urllib.request.Request(url, headers={'User-Agent': 'PaperPilot/1.0'}), timeout=20) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('具身日报响应过大')
    return json.loads(raw)


def catalog():
    value = fetch('/data/catalog.json')
    if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('papers'), list):
        raise ValueError('日报目录格式无效')
    return value['papers']


def paper_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}\.\d{4,5}(?:v\d+)?', value):
        raise ValueError('无效的日报论文编号')
    return re.sub(r'v\d+$', '', value)


def normalize(raw):
    ident = paper_id(raw.get('id'))
    title = raw.get('title')
    if not isinstance(title, str) or not title.strip() or len(title) > 1000:
        raise ValueError('日报论文缺少有效标题')
    summary = (raw.get('translations') or {}).get('zh', {}).get('summary') or raw.get('summary') or ''
    abstract = raw.get('abstract') or ''
    if not isinstance(summary, str) or not isinstance(abstract, str):
        raise ValueError('日报论文内容格式无效')
    return {'id': ident, 'title': title.strip(), 'source': 'embodied_daily',
            'paper_url': 'https://arxiv.org/abs/' + ident, 'source_url': 'https://arxiv.org/abs/' + ident,
            'abstract': abstract[:50000], 'summary': summary[:3000], 'authors': [],
            'reading_url': base_url() + '/reader.html?' + urlencode({'id': ident, 'lang': 'zh'}),
            'reading_ready': bool(raw.get('summary') and (raw.get('slides') or raw.get('slide_count', 0)) and (raw.get('downloads') or {}).get('pdf')),
            'evidence_scope': '具身日报概括' if raw.get('summary_scope') != 'abstract' else '具身日报摘要预览'}


def save_listing(value):
    # Queue and skipped entries own their snapshots; old feed caches can expire.
    with store.LOCK:
        store.save('embodied_listing', value)
        for old in store.all_objects('embodied_listing')[100:]:
            store.remove('embodied_listing', old['id'])
    return value


def preview(ident):
    ident = paper_id(ident)
    try:
        raw = next((row for row in catalog() if paper_id(row.get('id')) == ident), None)
        if raw is None:
            raise ValueError('日报中未找到该论文')
        item = normalize(raw)
        if item['id'] != ident:
            raise ValueError('论文编号不匹配')
    except Exception as exc:
        raise ValueError('无法读取这篇日报论文，请稍后重试') from exc
    value = {'id': uuid.uuid4().hex, 'items': [item]}
    return save_listing(value)


def listing(day=None):
    today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
    day = day or today.isoformat()
    if not isinstance(day, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
        raise ValueError('日期格式无效')
    if date.fromisoformat(day) > today:
        raise ValueError('不能读取未来日期')
    previous = next((r for r in store.all_objects('embodied_listing') if r.get('day') == day and r.get('base_url') == base_url()), None)
    if previous and time.time() - previous.get('fetched_at', 0) < 300:
        return previous
    try:
        rows = catalog()
        items, seen = [], set()
        for row in rows:
            if day not in (row.get('hf_dates') or []):
                continue
            item = normalize(row)
            if item['id'] not in seen:
                items.append(item); seen.add(item['id'])
        value = {'id': uuid.uuid4().hex, 'day': day, 'items': items, 'base_url': base_url(),
                 'fetched_at': time.time(), 'home': links()['home']}
        return save_listing(value)
    except Exception as exc:
        if previous:
            return {**previous, 'stale': True, 'error': '具身日报暂时无法连接，显示上次内容'}
        raise ValueError('具身日报暂时无法连接，请稍后重试或打开网站') from exc
