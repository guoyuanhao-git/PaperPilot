"""Source-verified publication records and conservative paper-linked citations."""
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo
from . import discovery


def norm(text):
    return re.sub(r'[^\w]', '', text.casefold())


def fetch(url, host):
    def check(value):
        p = urllib.parse.urlsplit(value)
        if p.scheme != 'https' or p.hostname != host or p.username or p.password:
            raise ValueError('公共查询不可用')
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            check(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    check(url)
    with urllib.request.build_opener(Redirect()).open(urllib.request.Request(url, headers=discovery.UA), timeout=10) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024: raise ValueError('查询结果过大')
    return raw.decode('utf-8')



def venue(paper, info):
    """Only exact-title records with explicit publication/acceptance evidence qualify."""
    if not info.get('authors'): return None
    checked=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
    try:
        ident=re.sub(r'v\d+$','',discovery.arxiv_id(paper.get('source_url','')))
        url='https://export.arxiv.org/api/query?'+urllib.parse.urlencode({'id_list':ident})
        root=ET.fromstring(fetch(url,'export.arxiv.org'))
        ns={'a':'http://www.w3.org/2005/Atom','x':'http://arxiv.org/schemas/atom'}
        entry=root.find('a:entry',ns)
        if entry is not None and norm(entry.findtext('a:title','',ns))==norm(info['original_title']):
            journal=entry.findtext('x:journal_ref','',ns).strip()
            comment=entry.findtext('x:comment','',ns).strip()
            accepted=re.search(r'\b(?:accepted (?:by|at|to|for(?: publication in)?)|published (?:at|in))\s+([^.;\n]+)',comment,re.I)
            if re.search(r'\b(?:not|never)\s+(?:yet\s+)?accepted|withdrawn|rejected',comment,re.I): accepted=None
            name=journal or (accepted[1].strip() if accepted else '')
            if name and not re.search(r'\b(?:submitted|under review|not accepted|withdrawn)\b',name,re.I):
                return {'name':name,'source_url':'https://arxiv.org/abs/'+ident,'evidence':journal or comment,'verified':True,'checked_at':checked}
    except (OSError,ValueError,ET.ParseError):pass
    try:
        url='https://api.crossref.org/works?'+urllib.parse.urlencode({'query.title':info['original_title'],'rows':3})
        items=json.loads(fetch(url,'api.crossref.org')).get('message',{}).get('items',[])
        for item in items:
            if item.get('type') not in ('journal-article','proceedings-article'):continue
            if not any(norm(t)==norm(info['original_title']) for t in item.get('title',[])):continue
            people=item.get('author') or []
            expected=info.get('authors') or []
            if not people or not expected or norm(people[0].get('given','')+' '+people[0].get('family',''))!=norm(expected[0]['name']):continue
            names=item.get('container-title') or []
            doi=item.get('DOI','')
            if names and doi.startswith('10.'):
                return {'name':names[0],'source_url':'https://doi.org/'+urllib.parse.quote(doi,safe='/'), 'verified':True,'checked_at':checked}
    except (OSError,ValueError,TypeError):pass
    return None
