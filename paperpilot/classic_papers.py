"""Small verified alias directory; metadata is fetched from the official paper page.

This supplements indexes with incomplete coverage of early landmark papers.
It never manufactures an arXiv ID or accepts a model-provided arbitrary URL.
"""
import re
from html.parser import HTMLParser
from . import discovery

RECORDS = (
    {'title':'ImageNet Classification with Deep Convolutional Neural Networks',
     'aliases':('AlexNet',), 'year':'2012', 'conference_month':'2012-12',
     'date_basis_url':'https://nips.cc/Conferences/2012',
     'venue':'NIPS 2012',
     'url':'https://papers.nips.cc/paper_files/paper/2012/hash/c399862d3b9d6b76c8436e924a68c45b-Abstract.html'},
    {'title':'Generative Adversarial Networks',
     'aliases':('GAN','Generative Adversarial Nets'), 'arxiv':'1406.2661',
     'url':'https://arxiv.org/abs/1406.2661'},
)


def reference(query):
    from .title_search import same_title
    return next((r for r in RECORDS if any(same_title(query,t) for t in (r['title'],*r['aliases']))), None)


class CitationPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta = {}; self.parts = []; self.abstract_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'meta' and a.get('name','').startswith('citation_'):
            self.meta.setdefault(a['name'],[]).append(a.get('content',''))
        if self.abstract_depth:
            self.abstract_depth += 1
        elif 'paper-abstract' in a.get('class','').split():
            self.abstract_depth = 1

    def handle_endtag(self, tag):
        if self.abstract_depth:
            self.abstract_depth -= 1

    def handle_data(self, data):
        if self.abstract_depth:
            self.parts.append(data)

    def value(self, key):
        return (self.meta.get(key) or [''])[0]


def lookup(query):
    ref = reference(query)
    if not ref:
        return []
    from .title_search import same_title, safe_url
    parser = CitationPage()
    parser.feed(discovery.public_fetch(ref['url'], {'papers.nips.cc','proceedings.neurips.cc','arxiv.org'}))
    title = parser.value('citation_title')
    abstract = parser.value('citation_abstract') or ' '.join(' '.join(parser.parts).split())
    if not same_title(title,ref['title']) or not abstract:
        raise ValueError('官方论文页面未能核实题名与摘要')
    published = parser.value('citation_online_date') or parser.value('citation_date') or parser.value('citation_publication_date')
    published = published.replace('/','-')
    basis = 'arXiv 首次提交年月'
    if 'arxiv' in ref:
        expected_month = '20'+ref['arxiv'][:2]+'-'+ref['arxiv'][2:4]
        if (parser.value('citation_arxiv_id') != ref['arxiv'] or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',published)
                or published[:7] != expected_month):
            raise ValueError('官方论文标识或日期不一致')
    else:
        if published != ref['year']:
            raise ValueError('会议官网出版年份与记录不一致')
        # The proceedings expose a year only. The label uses the verified conference month,
        # explicitly distinguished from an exact paper publication date.
        published = ref['conference_month']
        basis = 'NIPS 2012 会期年月（论文官网仅标出版年份）'
    return [{'id':ref.get('arxiv') or 'official-alexnet-2012', 'title':title,
             'abstract':abstract, 'authors':parser.meta.get('citation_author',[]),
             'published':published, 'source':'official_papers', 'kind':'paper',
             'paper_url':ref['url'], 'source_url':ref['url'],
             'pdf_url':safe_url(parser.value('citation_pdf_url')), 'venue':ref.get('venue',''),
             'publication_date_source':basis, 'date_basis_url':ref.get('date_basis_url',''),
             'evidence_scope':'官方论文页面的题名、作者与摘要；未读全文'}]
