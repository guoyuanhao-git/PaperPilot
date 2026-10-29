"""Bounded official-site crawl. No dependency on the former conference website."""
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin, urldefrag
from . import discovery

MAX_PAGES = 6


def allowed(url, domains):
    try:
        p = urlsplit(url)
        return (p.scheme == 'https' and p.port in (None, 443) and not p.username and
                not p.password and any(p.hostname == d or p.hostname.endswith('.' + d) for d in domains))
    except (ValueError, AttributeError):
        return False


class Page(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []; self.links = []; self.skip = 0; self.anchor = None

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.skip += 1
        if tag == 'a' and not self.skip:
            self.anchor = [dict(attrs).get('href', ''), '']

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.skip = max(0, self.skip - 1)
        if tag == 'a' and self.anchor:
            self.links.append(self.anchor); self.anchor = None
        if tag in ('p', 'div', 'tr', 'li', 'h1', 'h2', 'h3', 'section'):
            self.parts.append('\n')

    def handle_data(self, text):
        if not self.skip:
            self.parts.append(text)
            if self.anchor:
                self.anchor[1] += text


def fetch_page(url, domains):
    # Redirect destinations are checked too; arbitrary links never become sources.
    import urllib.request
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if not allowed(newurl, domains):
                raise ValueError('官网跳转到未收录的来源')
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    if not allowed(url, domains):
        raise ValueError('不是此会议的官方来源')
    request = urllib.request.Request(url, headers={**discovery.UA, 'Accept': 'text/html'})
    with urllib.request.build_opener(Redirect()).open(request, timeout=15) as response:
        if 'html' not in response.headers.get_content_type():
            raise ValueError('官网页面不是 HTML')
        raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError('官网页面过大')
        address = response.geturl()
        html = raw.decode(response.headers.get_content_charset() or 'utf-8', errors='replace')
    page = Page(); page.feed(html)
    # Some conference sites load only their menu from a static HTML fragment.
    # Read a literal same-site fragment; never execute JavaScript or guess paths.
    for fragment in re.findall(r'fetch\(\s*["\']([^"\']*(?:header|nav|menu)\.html)["\']\s*\)', html, re.I)[:1]:
        target = urljoin(address, fragment)
        if allowed(target, domains):
            page.links.append([target, 'Official navigation'])
    lines = [re.sub(r'\s+', ' ', line).strip() for line in ''.join(page.parts).splitlines()]
    text = '\n'.join(line for line in lines if line)
    if len(text) < 80 or re.search(r'Attention Required!|Just a moment|verify you are human|Access Denied', text[:1500], re.I):
        raise ValueError('官网暂时无法读取')
    return address, text, page.links


def collect(registry, series):
    domains = registry['domains']
    # Read the known CFP/date entry and the root before exploring navigation;
    # otherwise a large association homepage can exhaust the budget on old news.
    deep = [u for u in registry['sources'] if urlsplit(u).path.strip('/')]
    roots = [u for u in registry['sources'] if not urlsplit(u).path.strip('/')]
    latest = [e['source'] for e in sorted(series['editions'], key=lambda e:e['year'], reverse=True)
              if e['announcement'] != 'unverified'][:1]
    seeds = list(dict.fromkeys(deep[:1] + roots[:1] + latest + deep[1:] + roots[1:]))
    queue = list(dict.fromkeys(seeds)); seen = set(); pages = []; failures = []
    while queue and len(seen) < MAX_PAGES:
        url = queue.pop(0)
        if url in seen or not allowed(url, domains):
            continue
        seen.add(url)
        try:
            address, text, links = fetch_page(url, domains)
            if address not in {p['url'] for p in pages}:
                # Preserve the whole text locally; bounded excerpts go to the model.
                pages.append({'id': str(len(pages) + 1), 'url': address, 'text': excerpt(text)})
            found = []
            for href, label in links:
                target = urldefrag(urljoin(address, href))[0]
                if target in seen or not allowed(target, domains) or urlsplit(target).path.lower().endswith(('.pdf','.jpg','.png','.zip','.pptx','.docx')):
                    continue
                if urlsplit(target).query or re.search(r'login|profile|timezone|organizer|committee|sponsor|contact|privacy|conduct|press|bidding', target, re.I):
                    continue
                hint = target + ' ' + label
                if re.search(r'call.?for.?papers?|/cfp|important.?dates|deadlines|/dates|submission|author|future.?meeting|20\d{2}|(?:header|nav|menu)\.html', hint, re.I):
                    score = 3 * bool(re.search(r'call.?for.?papers?|/cfp|important.?dates|/dates|deadlines', hint, re.I))
                    score += 4 * bool(re.search(r'(?:header|nav|menu)\.html', hint, re.I))
                    score += 2 * bool(re.search(r'author|submission|future.?meeting', hint, re.I))
                    score += max([int(y) for y in re.findall(r'20\d{2}', hint)] or [2000]) / 10000
                    found.append((score, target))
            # Explore actual official links; never invent a next-year URL or date.
            first_root = queue[:1] if len(seen) == 1 else []
            queue = list(dict.fromkeys(first_root + [u for _, u in sorted(found, reverse=True)] + queue))
        except Exception as exc:
            failures.append({'url': url, 'error': str(exc)[:200]})
    return pages, failures


def excerpt(text, limit=15000):
    if len(text) <= limit:
        return text
    # Long homepages often put CFP dates at the end. Keep both context and all
    # date-related neighborhoods, rather than truncating the opening only.
    lines = text.splitlines(); chosen = set(range(min(16, len(lines))))
    for i, line in enumerate(lines):
        if re.search(r'deadline|abstract|registration|submission|call for|20\d{2}|time.?zone|AoE', line, re.I):
            chosen.update(range(max(0, i-2), min(len(lines), i+3)))
    return '\n'.join(lines[i] for i in sorted(chosen))[:limit]
