"""User-visible identity: verified month and an editable, unique short title."""
import re
import unicodedata
from . import publication, store


def short_title(value):
    if not isinstance(value, str) or len(value.strip()) > 60 or any(ord(c) < 32 for c in value):
        raise ValueError('短标题须为单行文字，最多 60 字符')
    return ' '.join(value.split())


def label(paper):
    month = paper.get('publication_month', '')
    return ' '.join(part for part in (month[2:4] + month[5:7] if month else '', paper.get('short_title', '')) if part)


def key(paper):
    return unicodedata.normalize('NFKC', label(paper)).casefold().replace(' ', '')


def validate(paper, required=False):
    paper['short_title'] = short_title(paper.get('short_title', ''))
    month = publication.validate_month(paper.get('publication_month', ''))
    if required and (not month or not paper['short_title']):
        raise ValueError('请先在论文阅读页填写发表年月和短标题，再标记喜欢、收藏或阅读完毕')
    if month and paper['short_title']:
        for other in store.all_objects('paper'):
            if other['id'] != paper['id'] and other.get('publication_month') and other.get('short_title') and key(other) == key(paper):
                raise ValueError('年月＋短标题已存在，请添加能区分论文的关键词或后缀')
    return paper


def infer(paper):
    if paper.get('short_title') or paper.get('short_title_source') == 'manual':
        return paper
    title = (paper.get('report') or {}).get('paper_info', {}).get('original_title') or paper.get('original_title') or paper.get('title', '')
    # A subtitle separator is reliable; do not invent acronyms for long full titles.
    prefix = re.split(r'[:：]', title, maxsplit=1)[0].strip()
    if len(prefix) <= 60 and (prefix != title or len(prefix.split()) <= 6):
        paper['short_title'] = prefix
        paper['short_title_source'] = 'title'
        try:
            validate(paper)
        except ValueError:
            paper['short_title'] = ''
    return paper


def migrate():
    for paper in store.all_objects('paper'):
        if paper.get('report') and not paper.get('short_title') and paper.get('short_title_source') != 'manual':
            before = dict(paper)
            infer(paper)
            if paper != before:
                store.save('paper', paper)
