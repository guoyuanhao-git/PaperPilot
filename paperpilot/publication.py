"""Publication month labels with explicit provenance, never PDF creation dates."""
import re
from datetime import datetime
from . import discovery, paper_info


def validate_month(value):
    if value == '':
        return value
    if not isinstance(value, str) or not re.fullmatch(r'(?:19|20)\d{2}-(?:0[1-9]|1[0-2])', value):
        raise ValueError('发表年月应为 YYYY-MM，例如 2021-09')
    if value > datetime.now().strftime('%Y-%m'):
        raise ValueError('发表年月不能晚于当前月份')
    return value


def infer(paper, first_page=''):
    if paper.get('publication_month'):
        return paper['publication_month'], paper.get('publication_date_source', '手动填写')
    if paper.get('publication_date_source') == '手动填写':
        return '', '手动填写'
    if paper.get('is_reference'):
        return '', ''
    try:
        ident = discovery.arxiv_id(paper.get('source_url', ''))
    except ValueError:
        match = re.search(r'(?im)^\s*arXiv:\s*((?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?)', first_page)
        ident = match[1] if match else ''
    code = ident.split('/')[-1][:4]
    if re.fullmatch(r'\d{2}(?:0[1-9]|1[0-2])', code):
        year = (1900 if int(code[:2]) >= 91 else 2000) + int(code[:2])
        try:
            return validate_month(f'{year:04}-{code[2:]}'), 'arXiv 首次提交年月'
        except ValueError:
            pass
    return '', ''


def apply(paper, first_page=''):
    month, source = infer(paper, first_page)
    paper.update(publication_month=month, publication_date_source=source)
    if paper.get('report'):
        report = paper['report']
        if report.get('paper_info'):
            paper_info.apply_defaults(report['paper_info'], paper)
        base = report.get('paper_info', {}).get('original_title') or paper.get('original_title') or paper.get('title') or report.setdefault('base_title', report['title'])
        # Prevent a model-supplied date prefix from doubling the verified prefix.
        if month:
            base = re.sub(r'^\d{4}\s*[·:：—-]\s*', '', base)
            report['base_title'] = base
        report['title'] = (month[2:4] + month[5:7] + ' · ' if month else '') + base
        report['publication_month'] = month
        report['publication_date_source'] = source
    return paper
