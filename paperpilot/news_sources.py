"""Per-user news subscriptions; custom feeds never change the shared adapter catalog."""
import hashlib
import http.client
import ipaddress
import json
import socket
import ssl
from urllib.parse import urlparse, urljoin
from datetime import datetime
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET
from . import store, discovery as d


def url(value):
    if not isinstance(value, str) or len(value) > 1500:
        raise ValueError('请输入公开的 HTTPS 订阅地址')
    value = value.strip()
    try:
        p = urlparse(value)
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443) or p.fragment:
            raise ValueError()
        host = p.hostname.lower()
        if '.' not in host or host.endswith(('.local', '.localhost', '.internal')):
            raise ValueError()
        try:
            if not ipaddress.ip_address(host).is_global:
                raise ValueError()
        except ValueError:
            # Hostnames are resolved and checked again at connection time.
            if ':' in host or all(c.isdigit() or c == '.' for c in host):
                raise ValueError()
    except ValueError:
        raise ValueError('仅支持公开的 HTTPS 地址，不支持本机、内网或带登录凭据的地址') from None
    return value


def defaults():
    from .daily import OUTLETS
    return {'id': 'current', 'selected': list(OUTLETS), 'custom': []}


def current():
    try:
        return store.get('news_sources', 'current')
    except ValueError:
        return defaults()


def signature(config=None):
    return hashlib.sha256(json.dumps(config or current(), sort_keys=True).encode()).hexdigest()


def save(value):
    from .daily import OUTLETS
    custom, selected = value.get('custom'), value.get('selected')
    if not isinstance(custom, list) or len(custom) > 20 or not isinstance(selected, list):
        raise ValueError('最多添加 20 个自定义订阅')
    rows = []
    for item in custom:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not 1 <= len(item['name'].strip()) <= 40:
            raise ValueError('来源名称须为 1–40 字')
        feed = url(item.get('url'))
        ident = 'feed-' + hashlib.sha256(feed.encode()).hexdigest()[:20]
        if any(r['id'] == ident for r in rows):
            raise ValueError('该订阅地址已添加')
        rows.append({'id': ident, 'name': item['name'].strip(), 'url': feed})
    allowed = set(OUTLETS) | {r['id'] for r in rows}
    if any(not isinstance(s, str) or s not in allowed for s in selected):
        raise ValueError('所选来源无效')
    return store.save('news_sources', {'id': 'current', 'selected': list(dict.fromkeys(selected)), 'custom': rows})


def catalog(config=None):
    return {**d.SOURCES, **{r['id']: {**r, 'kind': 'news'} for r in (config or current())['custom']}}


def fetch(address):
    """HTTPS with public-IP validation, pinned connections, and bounded redirects/body."""
    for _ in range(4):
        address = url(address)
        p = urlparse(address)
        try:
            ips = list(dict.fromkeys(r[4][0] for r in socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)))
            if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
                raise ValueError('订阅地址解析到非公开网络，无法读取')
            conn = http.client.HTTPSConnection(p.hostname, timeout=20)
            # Do not resolve the hostname again after validation (DNS rebinding).
            sock = socket.create_connection((ips[0], 443), timeout=20)
            try:
                conn.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=p.hostname)
            except Exception:
                sock.close()
                raise
            try:
                conn.request('GET', (p.path or '/') + ('?' + p.query if p.query else ''),
                             headers={'User-Agent': 'PaperPilot/1.0', 'Accept': 'application/rss+xml, application/atom+xml, application/xml'})
                response = conn.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    address = urljoin(address, response.getheader('Location', ''))
                    continue
                if response.status != 200:
                    raise ValueError(f'订阅源返回 HTTP {response.status}')
                data = response.read(3 * 1024 * 1024 + 1)
                if len(data) > 3 * 1024 * 1024:
                    raise ValueError('订阅内容超过 3 MB')
                return data
            finally:
                conn.close()
        except (OSError, http.client.HTTPException):
            raise ValueError('暂时无法读取订阅地址，请检查公开 RSS/Atom 地址后重试') from None
    raise ValueError('订阅地址跳转过多')


def parse(raw, record):
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise ValueError('该地址不是可读取的 RSS/Atom 订阅，请勿填写单篇文章地址') from None
    atom = '{http://www.w3.org/2005/Atom}'
    if root.tag == 'rss':
        title = root.findtext('./channel/title') or ''
        entries = root.findall('./channel/item')
    elif root.tag == atom + 'feed':
        title = root.findtext(atom + 'title') or ''
        entries = root.findall(atom + 'entry')
    else:
        raise ValueError('请提供 RSS/Atom 订阅地址，公众号名称或单篇文章地址不能用于持续更新')
    rows = []
    for item in entries:
        if root.tag == 'rss':
            name, link, date = (item.findtext(k) or '' for k in ('title', 'link', 'pubDate'))
            body = item.findtext('{http://purl.org/rss/1.0/modules/content/}encoded') or item.findtext('description') or ''
        else:
            name = item.findtext(atom + 'title') or ''
            link = next((a.get('href', '') for a in item.findall(atom + 'link') if a.get('rel', 'alternate') == 'alternate'), '')
            date = item.findtext(atom + 'published') or item.findtext(atom + 'updated') or ''
            element = item.find(atom + 'content')
            if element is None:
                element = item.find(atom + 'summary')
            body = '' if element is None else ET.tostring(element, encoding='unicode') if len(element) else element.text or ''
        try:
            link = url(urljoin(record['url'], link)) if link else ''
            try:
                published = datetime.fromisoformat(date.replace('Z', '+00:00'))
            except ValueError:
                published = parsedate_to_datetime(date)
            if not published or not published.tzinfo or not name.strip() or not link:
                continue
        except (ValueError, TypeError, OverflowError):
            continue
        rows.append({'title': d.clean_text(name), 'source_url': link, 'source': record['id'],
                     'published': published.isoformat(), 'channel': 'rss', 'feed_url': record['url'],
                     'body': body, 'links_unavailable': True})
    return d.clean_text(title), rows


def probe(address):
    address = url(address)
    ident = 'feed-' + hashlib.sha256(address.encode()).hexdigest()[:20]
    title, rows = parse(fetch(address), {'id': ident, 'url': address})
    return {'id': ident, 'url': address, 'name': title[:40], 'count': len(rows),
            'latest': max((r['published'] for r in rows), default='')}


def articles(record, now):
    from .daily import recent
    _, rows = parse(fetch(record['url']), record)
    return [r for r in rows if recent(r['published'], now)], '自定义 RSS/Atom；依据订阅正文或摘要初筛，更新及时性取决于订阅提供方，论文链接可能不完整'
