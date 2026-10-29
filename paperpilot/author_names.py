"""Conservative, source-backed common Chinese names; never transliterate guesses.

Entries are exact full-name matches, not surname or fuzzy matches. Extend only
after checking a public bilingual university/publisher source.
"""
import re
import json
import urllib.parse

NAMES = [
    ('Terence Tao', '陶哲轩', 'https://news.pku.edu.cn/xwzh/48bc7f2673824c81b750ee71b3801cdf.htm'),
    ('Geoffrey Hinton', '杰弗里·辛顿', 'https://www.phys.tsinghua.edu.cn/info/1063/6136.htm'),
    ('John Hopfield', '约翰·霍普菲尔德', 'https://www.phys.tsinghua.edu.cn/info/1063/6136.htm'),
    ('Yann LeCun', '杨立昆', 'https://www.tsinghua.edu.cn/info/1176/27432.htm'),
    ('Yoshua Bengio', '约书亚·本吉奥', 'https://www.tsinghua.edu.cn/info/1175/111622.htm'),
    ('Andrew Yao', '姚期智', 'https://www.tsinghua.edu.cn/info/1175/111622.htm'),
    ('Kaiming He', '何恺明', 'https://tis.hrbeu.edu.cn/Upload/PaperUpLoad/26b914f3-5baa-4ed2-9793-c27f13249adc.pdf'),
]


def lookup(name):
    normalized = re.sub(r'\s+', ' ', name.strip()).casefold()
    for english, chinese, source in NAMES:
        if normalized == english.casefold():
            return {'name': chinese, 'source_url': source, 'verified': True}
    return None


def enrich(info):
    for author in info.get('authors', []):
        value = lookup(author.get('name', ''))
        if value:
            author['chinese_name'] = value
    return info


def resolve(author):
    """Look up a sourced bilingual identity, requiring an exact name and employer.

    Called only during metadata generation, never while rendering or polling the
    library. Ambiguous identities, missing affiliations and unavailable sites fail
    closed to the original English name.
    """
    known = lookup(author.get('name', ''))
    if known:
        return known
    affiliations = author.get('affiliations', [])
    if not affiliations:
        return None
    from .scholarly_metadata import fetch, norm
    def request(**params):
        url = 'https://www.wikidata.org/w/api.php?' + urllib.parse.urlencode(dict(format='json', **params))
        return json.loads(fetch(url, 'www.wikidata.org'))
    try:
        results = request(action='wbsearchentities', search=author['name'], language='en', limit=5).get('search', [])
        ids = [r['id'] for r in results if re.fullmatch(r'Q\d+', r.get('id','')) and
               (norm(r.get('label','')) == norm(author['name']) or norm(r.get('match',{}).get('text','')) == norm(author['name']))]
        if not ids:
            return None
        entities = request(action='wbgetentities', ids='|'.join(ids), props='labels|aliases|claims', languages='en|zh|zh-hans|zh-cn').get('entities', {})
        def claim_ids(entity, key):
            return [c.get('mainsnak',{}).get('datavalue',{}).get('value',{}).get('id') for c in entity.get('claims',{}).get(key, [])]
        candidates = []
        for ident, entity in entities.items():
            labels = entity.get('labels', {})
            english = [labels.get('en',{}).get('value','')] + [a.get('value','') for a in entity.get('aliases',{}).get('en', [])]
            chinese = next((labels[l]['value'] for l in ('zh-cn','zh-hans','zh') if l in labels), '')
            employers = [e for e in claim_ids(entity, 'P108') if e and re.fullmatch(r'Q\d+', e)]
            if 'Q5' in claim_ids(entity, 'P31') and any(norm(n)==norm(author['name']) for n in english) and re.search(r'[\u4e00-\u9fff]', chinese) and employers:
                candidates.append((ident, chinese, employers))
        employers = list(dict.fromkeys(e for _,_,es in candidates for e in es))[:30]
        if not employers:
            return None
        organizations = request(action='wbgetentities', ids='|'.join(employers), props='labels|aliases', languages='en|zh|zh-hans').get('entities', {})
        matches = []
        for ident, chinese, employers in candidates:
            names = []
            for employer in employers:
                org = organizations.get(employer, {})
                names += [v.get('value','') for v in org.get('labels',{}).values()]
                names += [v.get('value','') for values in org.get('aliases',{}).values() for v in values]
            if any(len(norm(n)) >= 5 and norm(n) == norm(a) for n in names for a in affiliations):
                matches.append({'name':chinese, 'source_url':'https://www.wikidata.org/wiki/'+ident, 'verified':True})
        return matches[0] if len(matches)==1 else None
    except Exception:
        # Enrichment must never block a report or turn an unverified translation
        # into a claimed identity. No provider secrets are involved in this lookup.
        return None
