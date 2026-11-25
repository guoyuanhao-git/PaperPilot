import hashlib
import io
import json
import math
import os
import tempfile
from contextlib import contextmanager
import re
import threading
import uuid
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium

from . import store

PDF_LOCK = threading.RLock()  # PDFium is not thread safe.
INVENTORY_VERSION = 11


def first_page_title(page):
    """Conservative local fallback: contiguous large-type lines near page top."""
    from statistics import median
    lines = []
    for line in page.extract_text_lines():
        text = line['text'].strip()
        if line['top'] > page.height * .35 or len(text) < 4 or re.search(r'arxiv:|preprint|under review|accepted at', text, re.I):
            continue
        sizes = [c['size'] for c in line.get('chars', []) if str(c.get('text', '')).strip() and c.get('upright', True)]
        if sizes:
            lines.append((line, median(sizes)))
    if not lines:
        return ''
    peak = max(size for _, size in lines)
    if peak < 12:
        return ''
    selected = []
    for line, size in lines:
        if size < peak * .88:
            if selected:
                break
            continue
        if selected and line['top'] - selected[-1]['bottom'] > peak * 1.5:
            break
        selected.append(line)
    title = ' '.join(line['text'].strip() for line in selected)
    return title if 8 <= len(title) <= 500 else ''


def figure_label(text):
    match = re.match(r'^\s*(Figure|Fig\.?|Table|图|表)\s*([A-Z]?\d+(?:\.\d+)*|[IVX]+)\s*[:：.．|｜]', text, re.I)
    if not match:
        match = re.match(r'^\s*(Figure|Fig\.?|Table|图|表)\s*([A-Z]?\d+(?:\.\d+)*|[IVX]+)(?:\s+|$)', text, re.I)
        if match and re.match(r'(?:show(?:s|ed)?|illustrates?|presents?|reports?|compares?|summarizes?|provides?|demonstrates?|depicts?|lists?|is|are|was|were)\b', text[match.end():], re.I):
            match = None
    return (('table' if match[1].lower() in ('table', '表') else 'figure'), match[2].lower()) if match else None


def directory(ident):
    if not re.fullmatch('[a-f0-9]{20}', ident):
        raise ValueError('无效论文 ID')
    return store.data_dir() / 'papers' / ident


def next_figure_number(paper):
    figures = [*paper.get('figures', []), *(paper.get('report') or {}).get('figures', [])]
    numbers = [int(f['id'][4:]) for f in figures if re.fullmatch(r'fig-\d+', f.get('id', ''))]
    return max([paper.get('last_figure_number', 0), *numbers]) + 1


def saved_figures(paper):
    """Images referenced by independently saved reading artifacts."""
    return [f for kind in ('report', 'translation')
            for f in (paper.get(kind) or {}).get('figures', [])]


def sync_captions(paper):
    """Original figures own captions; saved artifacts keep their crop snapshots."""
    originals = {f['id']: f for f in paper.get('figures', [])}
    for saved in saved_figures(paper):
        current = originals.get(saved['id'])
        if current and current.get('caption') == saved.get('caption'):
            saved['caption_zh'] = current.get('caption_zh', '')


def remove_figure(ident, figure_id, expected):
    from .service import SAVE_LOCK
    with SAVE_LOCK:
        paper = store.get('paper', ident)
        if any(j.get('paper_id') == ident and j.get('status') in ('running', 'queued')
               for j in store.all_objects('job')):
            raise ValueError('这篇论文还有任务正在运行，请结束后再移除图表')
        figure = next((f for f in paper['figures'] if f['id'] == figure_id), None)
        if not figure or figure != expected:
            raise ValueError('图表已变化，请刷新后重新确认')
        paper['last_figure_number'] = next_figure_number(paper) - 1
        removed = {figure_id}
        while True:
            aliases = {f['id'] for f in paper['figures'] if f.get('duplicate_of') in removed}
            if aliases <= removed:
                break
            removed.update(aliases)
        suppressed = paper.setdefault('removed_figure_candidates', [])
        for f in paper['figures']:
            if f['id'] in removed:
                record = {'page': f['page'], 'caption': f.get('caption', ''), 'pdf_sha256': paper.get('pdf_sha256')}
                if record not in suppressed:
                    suppressed.append(record)
        paper['figures'] = [f for f in paper['figures'] if f['id'] not in removed]
        # Keep report snapshots and their images intact; disposable crops use the shared LRU.
        store.save('paper', paper)
        return paper


def render_page(ident, page_no):
    p = store.get('paper', ident)
    if p.get('pdf_released'):
        raise ValueError('原文空间已释放，请先恢复 PDF 再查看页面或调整裁剪')
    if not isinstance(page_no, int) or not 1 <= page_no <= p['page_count']:
        raise ValueError('页码超出范围')
    target = directory(ident) / f'page-{page_no}.png'
    with PDF_LOCK:
        if not target.exists():
            with pdfium.PdfDocument(str(directory(ident) / 'source.pdf')) as doc:
                page = doc[page_no - 1]
                scale = min(1.8, 1600 / page.get_width())
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil()
                image.save(target)
                bitmap.close()
                page.close()
    return target


def crop_path(ident, figure, paper, quality='reading'):
    key = [figure['page'], figure['bbox']]
    revision = paper.get('source_storage', {}).get('content_revision')
    if revision:
        key.append(revision)
    if quality == 'reading':
        key.append('direct-pdf-2400-4mp-v1')
    digest = hashlib.sha256(json.dumps(key).encode()).hexdigest()[:16]
    return directory(ident) / ('crop-' + digest + '.png')


def crop_figure(ident, figure, quality='reading'):
    """Return a cache path. Consume under PDF_LOCK before calling trim()."""
    from PIL import Image
    if quality not in ('reading', 'model'):
        raise ValueError('无效图片质量')
    with PDF_LOCK:
        paper = store.get('paper', ident)
        cached = figure.get('image_file', '')
        if re.fullmatch(r'crop-[a-f0-9]{16}\.png', cached):
            target = directory(ident) / cached
            if target.is_file():
                return target
            raise ValueError('旧报告图片缺失，不能用新版原文替代')
        bbox = figure['bbox']
        if len(bbox) != 4 or any(not isinstance(v, (int, float)) or not 0 <= v <= 1 for v in bbox) or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
            raise ValueError('裁剪区域必须为页面内的非空矩形')
        page_no = figure['page']
        if type(page_no) is not int or not 1 <= page_no <= paper['page_count']:
            raise ValueError('页码超出范围')
        target = crop_path(ident, figure, paper, quality)
        if paper.get('pdf_released') or not (directory(ident) / 'source.pdf').is_file():
            # Compatibility: releases made before high-resolution rendering have
            # only the original preview crop. Never require/re-download a PDF.
            for saved in (crop_path(ident, figure, paper), crop_path(ident, figure, paper, 'model')):
                if saved.is_file():
                    return saved
            raise ValueError('报告图片缺失，请先恢复原文 PDF')
        if target.exists():
            os.utime(target, None)
            return target
        temporary = directory(ident) / ('crop-' + uuid.uuid4().hex + '.tmp.png')
        try:
            if quality == 'model':
                # Preserve the original model-input resolution, independently
                # of reading/export quality. This cache is evictable too.
                with Image.open(render_page(ident, page_no)) as image:
                    with image.crop(tuple(round(bbox[i] * (image.width if i % 2 == 0 else image.height)) for i in range(4))) as crop:
                        crop.save(temporary)
            else:
                with pdfium.PdfDocument(str(directory(ident) / 'source.pdf')) as doc:
                    page = doc[page_no - 1]
                    try:
                        width, height = page.get_width(), page.get_height()
                        cw, ch = width * (bbox[2] - bbox[0]), height * (bbox[3] - bbox[1])
                        # Render the region directly; do not allocate a high-DPI
                        # full page. Bound both dimensions and decoded pixels.
                        scale = min(2400 / cw, 4096 / ch, math.sqrt(4_000_000 / (cw * ch)), 12)
                        crop = (bbox[0] * width, (1 - bbox[3]) * height,
                                (1 - bbox[2]) * width, bbox[1] * height)
                        bitmap = page.render(scale=scale, crop=crop)
                        try:
                            with bitmap.to_pil() as image:
                                image.save(temporary)
                        finally:
                            bitmap.close()
                    finally:
                        page.close()
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target


def figure_bytes(ident, figure, quality='reading'):
    from . import image_cache
    with PDF_LOCK:
        try:
            return crop_figure(ident, figure, quality=quality).read_bytes()
        finally:
            image_cache.trim()


def page_bytes(ident, page_no):
    from . import image_cache
    with PDF_LOCK:
        try:
            target = render_page(ident, page_no)
            os.utime(target, None)
            return target.read_bytes()
        finally:
            image_cache.trim()


@contextmanager
def model_images(ident, figures, enabled=True):
    """Small, immutable job-local snapshots, removed even on failure/cancel.

    A provider (especially Codex) may read a path much later. Never give it an
    evictable cache path or hold PDF_LOCK while waiting for the network.
    """
    from PIL import Image
    from . import image_cache
    if not enabled:
        yield []
        return
    with tempfile.TemporaryDirectory(prefix='.model-images-', dir=directory(ident)) as folder:
        paths = []
        try:
            for index, figure in enumerate(figures):
                target = Path(folder) / f'{index}.png'
                with PDF_LOCK:
                    source = crop_figure(ident, figure, quality='model')
                    with Image.open(source) as image:
                        # Pinned/released images may be high-resolution. Keep a
                        # conservative model ceiling even without the PDF.
                        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                        image.save(target)
                    image_cache.trim()
                paths.append(target)
            yield paths
        finally:
            image_cache.trim()


def caption_number(text):
    # A caption label has punctuation after its number; prose such as "Figure 3a shows"
    # must not create another image candidate.
    match = re.match(r'^\s*(?:Fig(?:ure)?\.?\s*(\d+)|图\s*(\d+))\s*[:：.．|｜]', text, re.I)
    return (match[1] or match[2]) if match else None


def full_caption(lines, first):
    parts = [first['text']]
    previous = first
    for line in lines[lines.index(first) + 1:]:
        height = line['bottom'] - line['top']
        if (figure_label(line['text']) or line['top'] - previous['bottom'] > 6
                # Separators and inline subscripts can make the first line taller.
                or abs(height - (first['bottom'] - first['top'])) > 3
                or abs(line['x0'] - first['x0']) > 25):
            break
        parts.append(line['text'])
        previous = line
        if sum(map(len, parts)) > 1400:
            break
    return ' '.join(parts)[:1600]


def extract_pdf(data):
    """Extract a candidate PDF before committing it to a paper record."""
    pages, figures = [], []
    with PDF_LOCK, pdfplumber.open(io.BytesIO(data)) as doc:
        if not 1 <= len(doc.pages) <= 250:
            raise ValueError('当前支持 1–250 页的论文 PDF')
        extracted_title = first_page_title(doc.pages[0])
        for i, page in enumerate(doc.pages):
            text = page.extract_text() or ''
            pages.append({'page': i + 1, 'text': text})
            lines = page.extract_text_lines()
            for line in lines:
                if not caption_number(line['text']):
                    continue
                top = line['top']
                if top < 45:
                    continue
                # Captions propose a crop; the reader can correct vector plots and mixed layouts.
                visuals = page.images + page.rects + page.curves + page.lines
                related = [img for img in visuals if img['bottom'] <= top + 10 and img['bottom'] > top - 200 and img['x1'] > img['x0']]
                if related:
                    x0, y0, x1 = min(v['x0'] for v in related), min(v['top'] for v in related), max(v['x1'] for v in related)
                else:
                    x0, y0, x1 = max(0, line['x0'] - 10), max(20, top - 250), min(page.width, max(line['x1'], line['x0'] + page.width * .42))
                figures.append({'id': 'fig-' + str(len(figures) + 1), 'page': i + 1,
                                'caption': full_caption(lines, line), 'bbox': [max(0, x0) / page.width, max(0, y0) / page.height, min(page.width, x1) / page.width, (top - 2) / page.height],
                                'selected': True, 'auto_crop': True, 'crop_version': 3})
        metadata = doc.metadata or {}
    return pages, figures, metadata, extracted_title


def ingest(data, filename, source_url='', is_reference=False, target_id=None, max_bytes=40 * 1024 * 1024):
    if len(data) > max_bytes or not data.startswith(b'%PDF-'):
        raise ValueError(f'请提供不超过 {max_bytes // (1024 * 1024)} MB 的 PDF 文件')
    pdf_hash = hashlib.sha256(data).hexdigest()[:20]
    duplicate = next((p for p in store.all_objects('paper') if not p.get('metadata_only') and (p.get('pdf_sha256') or p['id']) == pdf_hash), None)
    if duplicate and not target_id:
        if duplicate.get('pdf_released'):
            from . import paper_storage
            paper_storage.idle(duplicate['id'])
            return paper_storage.restore_bytes(duplicate['id'], data)
        return duplicate
    if duplicate and target_id and duplicate['id'] != target_id:
        raise ValueError('这份 PDF 已属于另一篇论文，请打开已有条目，或上传正确的原文')
    ident = target_id or pdf_hash
    previous = store.get('paper', target_id) if target_id else None
    try:
        existing = store.get('paper', ident)
        if not existing.get('metadata_only'):
            return existing
    except ValueError:
        pass
    pages, figures, metadata, extracted_title = extract_pdf(data)
    path = directory(ident)
    path.mkdir(parents=True, exist_ok=True)
    (path / 'source.pdf').write_bytes(data)
    (path / 'pages.json').write_text(json.dumps(pages, ensure_ascii=False))
    title = str(metadata.get('Title') or Path(filename).stem).strip()
    from .news_metadata import unresolved
    if (not metadata.get('Title') or unresolved({'title': title})) and extracted_title:
        title = extracted_title
    paper = {'id': ident, 'pdf_sha256': pdf_hash, 'title': title[:300], 'filename': Path(filename).name,
             'source_url': source_url, 'is_reference': is_reference, 'page_count': len(pages),
             'text_chars': sum(len(p['text']) for p in pages), 'figures': figures,
             'feedback': '', 'notes': '', 'read_status': '未标记', 'report': None, 'messages': []}
    try:
        history = store.get('reading_history', ident)
        paper.update(feedback=history.get('feedback', ''))
    except ValueError:
        pass
    if previous:
        for key in ('title', 'original_title', 'abstract', 'authors', 'publication_month', 'publication_date_source', 'short_title', 'short_title_source', 'notes', 'feedback', 'starred', 'liked', 'read_status', 'reading_completions', 'reading_session', 'reading_state_version', 'added_at', 'historical_import_at', 'messages', 'pdf_url', 'date_basis_url', 'import_input_title', 'metadata_source_kind', 'publication_precision'):
            if key in previous:
                paper[key] = previous[key]
        paper['metadata_only'] = False
    from . import publication
    publication.apply(paper, pages[0]['text'])
    inventory(paper)
    from . import paper_abstracts
    paper_abstracts.prepare(paper)
    from . import library
    library.initialize(paper)
    store.save('paper', paper)
    store.remove('reading_history', ident)
    return paper


def upgrade_library_figures():
    """Repair old automatic crops and aliases without changing manual selections."""
    for paper in store.all_objects('paper'):
        if paper.get('pdf_released'):
            continue
        groups = [paper['figures'], (paper.get('report') or {}).get('figures', [])]
        pending = [f for group in groups for f in group if f.get('auto_crop') and f.get('crop_version', 1) < 3]
        if not pending:
            continue
        try:
            aliases = {}
            with PDF_LOCK, pdfplumber.open(directory(paper['id']) / 'source.pdf') as pdf:
                page_lines = {n: pdf.pages[n - 1].extract_text_lines() for n in {f['page'] for f in pending}}
                for group in groups:
                    seen, cleaned = {}, []
                    for f in group:
                        if not f.get('auto_crop') or f.get('crop_version', 1) >= 3:
                            cleaned.append(f)
                            continue
                        page = pdf.pages[f['page'] - 1]
                        lines = page_lines[f['page']]
                        number = re.match(r'^\s*(?:Fig(?:ure)?\.?\s*|图\s*)(\d+)', f.get('caption', ''), re.I)
                        line = next((l for l in lines if number and caption_number(l['text']) == number[1]), None)
                        if line:
                            key = (f['page'], number[1])
                            if key in seen:
                                aliases[f['id']] = seen[key]['id']
                                seen[key]['selected'] = seen[key].get('selected') or f.get('selected')
                                continue
                            seen[key] = f
                            bottom = (line['top'] - 2) / page.height
                            if f['bbox'][1] < bottom < f['bbox'][3]:
                                f['bbox'] = [*f['bbox'][:3], bottom]
                            caption = full_caption(lines, line)
                            if f.get('caption') != caption:
                                f['caption_zh'] = ''
                            f['caption'] = caption
                        f['crop_version'] = 3
                        cleaned.append(f)
                    group[:] = cleaned
            if paper.get('report'):
                for section in paper['report'].get('sections', []):
                    section['figures'] = list(dict.fromkeys(aliases.get(ident, ident) for ident in section.get('figures', [])))
            store.save('paper', paper)
        except (OSError, ValueError, IndexError):
            continue


def context(paper, limit, query=''):
    pages = json.loads((directory(paper['id']) / 'pages.json').read_text())
    if paper['text_chars'] < 100:
        raise ValueError('这份 PDF 几乎没有可提取文字。当前尚不支持扫描件 OCR，请使用文字版 PDF')
    chunks = [f'[PDF 第 {p["page"]} 页]\n{p["text"]}' for p in pages]
    if sum(len(s) for s in chunks) <= limit:
        return '\n\n'.join(chunks), f'文字提取覆盖全部 {len(pages)} 页；图表理解以所选图片/图注为限，未进行公式 OCR'
    # Long PDFs: selection is explicit in provenance, never labelled full-text review.
    terms = re.findall(r'[A-Za-z]{3,}|[\u4e00-\u9fff]{2,}', query.lower())
    scores = []
    for i, p in enumerate(pages):
        t = p['text'].lower()
        score = sum(t.count(term) for term in terms) if terms else sum(t.count(term) for term in ['method', 'experiment', 'result', 'conclusion', 'abstract'])
        scores.append((score + (3 if i < 3 else 0), i))
    chosen, used = [], 0
    for _, i in sorted(scores, reverse=True):
        if used + len(chunks[i]) <= limit:
            chosen.append(i)
            used += len(chunks[i])
    if not chosen:
        return chunks[0][:limit], '仅截取第一页部分文字，受上下文上限限制'
    chosen.sort()
    return '\n\n'.join(chunks[i] for i in chosen), '受上下文上限限制，仅选取 PDF 页：' + ', '.join(str(i + 1) for i in chosen)


def parallel_tables(page):
    """Separate caption-labelled tables sharing a row using their actual rule spans.

    Page halves are not reliable columns: papers also use unequal or three-column
    tables. Require multiple aligned rules, and retain manual crops in inventory.
    """
    found = []
    for line in page.extract_text_lines():
        chars = sorted(line.get('chars', []), key=lambda c:c['x0'])
        text, positions = '', []
        for char in chars:
            text += char['text']
            positions.extend([char] * len(char['text']))
        labels = list(re.finditer(r'Table\s*(\d+)\s*[:：.]', text, re.I))
        if len(labels) < 2:
            continue
        rules = [r for r in page.lines + page.rects
                 if line['bottom'] < r['top'] < line['bottom'] + 260
                 and r['bottom'] - r['top'] < 2 and r['x1'] - r['x0'] > 40]
        groups = {}
        for r in rules:
            groups.setdefault((round(r['x0'], 1), round(r['x1'], 1)), []).append(r)
        for label in labels:
            x = positions[label.start()]['x0']
            choices = [(span, rs) for span, rs in groups.items() if len(rs) >= 2 and span[0] - 15 <= x < span[1] - 20]
            if not choices:
                continue
            (x0,x1), rs = min(choices, key=lambda item:(abs(item[0][0]-x), min(r['top'] for r in item[1])))
            top, bottom = min(r['top'] for r in rs), max(r['bottom'] for r in rs)
            caption = page.crop((max(0,x0-2),line['top']-1,min(page.width,x1+2),top-1)).extract_text() or ''
            if not re.match(r'^Table\s*' + label[1] + r'\s*[:：.]', caption, re.I):
                continue
            found.append({'number':label[1], 'caption':caption.replace('\n',' '),
                          'bbox':[max(0,x0-2)/page.width,(top-2)/page.height,min(page.width,x1+2)/page.width,(bottom+3)/page.height]})
    return found


def table_region(page, caption):
    """Locate aligned table rules on either side of a caption, not a fixed page slice."""
    groups = []
    for rule in page.lines + page.rects:
        if rule['bottom'] - rule['top'] > 2 or rule['x1'] - rule['x0'] < 40:
            continue
        group = next((g for g in groups if abs(g[0]['x0'] - rule['x0']) < 2
                      and abs(g[0]['x1'] - rule['x1']) < 2), None)
        if group is None:
            groups.append([rule])
        else:
            group.append(rule)
    choices = []
    for group in groups:
        x0, x1 = group[0]['x0'], group[0]['x1']
        # The label must belong to this table's horizontal span, including centered captions.
        centered = (caption['x0'] <= x0 and caption['x1'] >= x1
                    and abs(caption['x0'] + caption['x1'] - x0 - x1) < 60)
        if not centered and not (x0 - 30 <= caption['x0'] < x1 - 20 or caption['x0'] < x0 <= caption['x1']):
            continue
        cap_x0 = min(x0, caption['x0']) - 4
        cap_x1 = max(x1, caption['x1']) + 4 if centered or x1 - x0 > page.width * .5 else x1 + 4
        local = page.crop((max(0, cap_x0), 0, min(page.width, cap_x1), page.height)).extract_text_lines(x_tolerance=1)
        labels = [l for l in local if figure_label(l['text'])]
        parts = [[]]
        for rule in sorted(group, key=lambda r: r['top']):
            if parts[-1] and any(parts[-1][-1]['bottom'] < l['top'] < rule['top'] for l in labels):
                parts.append([])
            parts[-1].append(rule)
        for rules in parts:
            # A repeated page-header rule separated by empty whitespace is not part of the table.
            while len(rules) > 2 and rules[1]['top'] - rules[0]['bottom'] > 8 and not any(
                    rules[0]['bottom'] + 1 < l['top'] < rules[1]['top'] - 1 for l in local):
                rules = rules[1:]
            if len(rules) < 2:
                continue
            top, bottom = rules[0]['top'], max(r['bottom'] for r in rules)
            if bottom - top < 12:  # A double top rule is not a whole table.
                continue
            if bottom <= caption['top'] + 1:
                distance, side = caption['top'] - bottom, 'above'
            elif top >= caption['bottom'] - 1:
                distance, side = top - caption['bottom'], 'below'
            else:
                continue
            if distance > 90:
                continue
            # Do not assign a preceding table (already introduced by its own
            # heading) to the next caption, or skip over another caption.
            other_labels = [l for l in labels if figure_label(l['text']) != figure_label(caption['text'])]
            if side == 'above' and any(0 <= top-l['bottom'] < 65 for l in other_labels):
                continue
            if side == 'below' and any(caption['bottom'] < l['top'] < top for l in other_labels):
                continue
            start = next((l for l in local if figure_label(l['text']) == figure_label(caption['text'])
                          and abs(l['top'] - caption['top']) < 4), None)
            if start is None:
                continue
            caption_lines = [l for l in local if side == 'above' or l['top'] < top - 1]
            text = full_caption(caption_lines, start)
            choices.append((distance, {'bbox': [max(0,x0-3)/page.width, max(0,top-2)/page.height,
                                                 min(page.width,x1+3)/page.width, min(page.height,bottom+3)/page.height],
                                       'caption': text}))
    return min(choices, key=lambda choice: choice[0])[1] if choices else None


def raster_region(page, caption):
    """Prefer the nearby embedded figure over unrelated page logos and decorative rules."""
    images = [v for v in page.images if v['x1']-v['x0'] > 60 and v['bottom']-v['top'] > 40
              and 0 <= caption['top'] - v['bottom'] <= 45
              and v['x1'] > caption['x0'] and v['x0'] < caption['x1']]
    if not images:
        return None
    return {'bbox': [max(0,min(v['x0'] for v in images)-2)/page.width,
                     max(0,min(v['top'] for v in images)-2)/page.height,
                     min(page.width,max(v['x1'] for v in images)+2)/page.width,
                     min(caption['top']-1,max(v['bottom'] for v in images)+2)/page.height]}


def embedded_captions(page, lines):
    """Recover captions concatenated after neighboring-column prose, using glyph positions."""
    output = []
    for line in lines:
        chars = sorted(line.get('chars', []), key=lambda c: c['x0'])
        text, positions = '', []
        for char in chars:
            text += char['text']
            positions.extend([char] * len(char['text']))
        for match in re.finditer(r'(?:Figure|Fig\.?|Table)\s*\d+(?:\s*[:：|｜]|(?=[A-Z]))', text, re.I):
            x0 = positions[match.start()]['x0']
            if x0 <= line['x0'] + 3:
                continue
            column = page.crop((max(0,x0-1), 0, page.width, page.height)).extract_text_lines(x_tolerance=1)
            candidate = next((l for l in column if abs(l['top']-line['top']) < 4 and figure_label(l['text'])), None)
            if candidate:
                output.append((column, candidate))
    return output


def inventory(paper, source_path=None):
    """Extend legacy inventories without replacing crops, IDs, reports or reader choices."""
    if paper.get('pdf_released'):
        raise ValueError('请先恢复原文 PDF，再重新解析图表')
    if paper.get('figure_inventory_version') == INVENTORY_VERSION:
        return paper
    figures = paper['figures']
    label = figure_label
    seen = {(f['page'], label(f['caption'])) for f in figures if label(f['caption'])}
    seen.update((f['page'], label(f['caption'])) for f in paper.get('removed_figure_candidates', [])
                if f.get('pdf_sha256') == paper.get('pdf_sha256') and label(f['caption']))
    next_id = next_figure_number(paper)
    appendix = False
    references_seen = False
    with PDF_LOCK, pdfplumber.open(source_path or directory(paper['id']) / 'source.pdf') as pdf:
        for index, page in enumerate(pdf.pages):
            text = page.extract_text() or ''
            # Explicit headings only; mentioning an appendix in prose is not a boundary.
            if re.search(r'(?im)^\s*(?:appendix|appendices|supplementary\s+material)\s*(?:$|[:.]|[A-Z]\s)', text):
                appendix = True
            if re.search(r'(?im)^\s*(?:\d+\s*)?(?:references|bibliography)\s*$', text):
                references_seen = True
            if references_seen and re.search(r'(?m)^A\s+[A-Z][A-Za-z][^\n.]{1,85}$', text[:250]):
                appendix = True
            for f in figures:
                if f['page'] == index + 1:
                    f.setdefault('region', 'appendix' if appendix else 'main')
                    f.setdefault('kind', (label(f['caption']) or ('figure', ''))[0])
            # Extract captions independently by column too: a right-column caption may
            # otherwise be concatenated after unrelated left-column prose.
            columns = [page.crop((x0, 0, x1, page.height)).extract_text_lines(x_tolerance=1)
                       for x0, x1 in ((0, page.width / 2), (page.width / 2, page.width))]
            lines = page.extract_text_lines(x_tolerance=1)
            candidates = [(lines, line) for line in lines if label(line['text']) and not re.fullmatch(r'\s*Table\s*\d+\s*\.\s*', line['text'], re.I)]
            global_labels = {label(line['text']) for _, line in candidates}
            for column in columns:
                for line in column:
                    tag = label(line['text'])
                    if not tag or re.fullmatch(r'\s*Table\s*\d+\s*\.\s*', line['text'], re.I):
                        continue
                    global_line = next((l for _, l in candidates if label(l['text']) == tag), None)
                    if (tag not in global_labels or line['x0'] >= page.width / 2
                            or global_line and len(re.findall(r'(?:Figure|Fig\.?|Table)\s*\d+\s*[:.|｜]', global_line['text'], re.I)) > 1):
                        candidates = [(ls, l) for ls, l in candidates if label(l['text']) != tag]
                        candidates.append((column, line))
                        global_labels.add(tag)
            for column, line in embedded_captions(page, lines):
                tag = label(line['text'])
                if tag not in global_labels:
                    candidates.append((column, line))
                    global_labels.add(tag)
            # Prefer a true colon-labelled caption over a prose reference with the same number.
            candidates = [item for item in candidates if re.search('[:：|｜]', item[1]['text'])
                          or not any(label(other[1]['text']) == label(item[1]['text']) and re.search('[:：|｜]', other[1]['text']) for other in candidates)]
            for source_lines, line in candidates:
                key = (index + 1, label(line['text']))
                table = table_region(page, line) if key[1][0] == 'table' else None
                raster = raster_region(page, line) if key[1][0] == 'figure' else None
                if key in seen:
                    existing = [f for f in figures if f['page'] == key[0] and label(f['caption']) == key[1]]
                    # A prose reference beginning 'Figure 5.' can duplicate a true caption.
                    for duplicate in existing[1:]:
                        if duplicate.get('auto_crop'):
                            duplicate['duplicate_of'] = existing[0]['id']
                    primary = existing[0] if existing else None
                    if primary and primary.get('auto_crop') and line['text'].strip().lower().startswith(('figure', 'fig', 'table')):
                        candidate = full_caption(source_lines, line)
                        if len(candidate) > len(primary['caption']):
                            primary['caption'] = candidate
                    if primary and primary.get('auto_crop') and key[1][0] == 'figure' and primary.get('crop_version', 0) < 7:
                        box = primary['bbox']
                        primary['bbox'] = [max(0, min(box[0] * page.width, line['x0']) - 12) / page.width,
                                           max(20, box[1] * page.height - 20) / page.height,
                                           min(page.width, max(box[2] * page.width, line['x1']) + 6) / page.width, box[3]]
                        primary['crop_version'] = 7
                    if primary and primary.get('auto_crop') and line['x0'] >= page.width / 2:
                        primary['bbox'][0] = max(primary['bbox'][0], (line['x0'] - 3) / page.width)
                    if primary and primary.get('auto_crop') and (table or raster):
                        primary.update(bbox=(table or raster)['bbox'], crop_version=INVENTORY_VERSION)
                        if table:
                            primary['caption'] = table['caption']
                    continue
                kind = key[1][0]
                caption = full_caption(source_lines, line)
                if kind == 'table':
                    # Table captions usually sit above data. Rule segments below the caption
                    # supply the table extent, including vector/text-only tables.
                    x0 = max(0, line['x0'] - 8)
                    x1 = min(page.width, max(line['x1'] + 8, x0 + page.width * .4))
                    cap_lines, parts = [], []
                    for candidate_line in source_lines[source_lines.index(line):]:
                        if not caption.startswith(' '.join(parts + [candidate_line['text']])):
                            break
                        parts.append(candidate_line['text'])
                        cap_lines.append(candidate_line)
                    top = max(l['bottom'] for l in cap_lines) + 2 if cap_lines else line['bottom'] + 2
                    next_caption = min([l['top'] for l in source_lines if l['top'] > top and label(l['text']) and l['x0'] < x1 and l['x1'] > x0] or [page.height - 25])
                    rules = [v for v in page.lines + page.rects if top <= v['top'] < min(top + 320, next_caption)
                             and v['x0'] >= x0 - 12 and v['x1'] <= x1 + 12 and v['x1'] - v['x0'] > (x1 - x0) * .55]
                    bottom = max(v['bottom'] for v in rules) + 4 if len(rules) >= 2 else min(top + 220, next_caption - 3, page.height - 25)
                    if rules:
                        x0, x1 = min(x0, min(v['x0'] for v in rules)), max(x1, max(v['x1'] for v in rules))
                else:
                    bottom = line['top'] - 2
                    previous = max([l['bottom'] for l in lines if label(l['text']) and l['bottom'] < bottom] or [20])
                    visuals = [v for v in page.images + page.rects + page.curves + page.lines
                               if previous <= v['top'] < v['bottom'] <= bottom + 3 and v['x1'] > v['x0']]
                    top = min(v['top'] for v in visuals) if visuals else max(previous, bottom - 300)
                    x0 = min(v['x0'] for v in visuals) if visuals else max(0, line['x0'] - 10)
                    x1 = max(v['x1'] for v in visuals) if visuals else min(page.width, max(line['x1'], x0 + page.width * .42))
                if kind == 'figure':
                    x0, x1 = min(x0, line['x0']) - 12, max(x1, line['x1']) + 6
                    top = max(20, top - 20)
                    if line['x0'] >= page.width / 2:
                        x0 = max(x0, line['x0'] - 3)
                box = [max(0, x0) / page.width, max(0, top) / page.height, min(page.width, x1) / page.width, min(page.height, bottom) / page.height]
                if table or raster:
                    box = (table or raster)['bbox']
                    if table:
                        caption = table['caption']
                if box[0] >= box[2] or box[1] >= box[3]:
                    continue
                figures.append({'id': f'fig-{next_id}', 'page': index + 1, 'caption': caption, 'bbox': box,
                                'kind': kind, 'region': 'appendix' if appendix else 'main',
                                'selected': True, 'auto_crop': True, 'crop_version': 7})
                next_id += 1
                seen.add(key)
            for table in parallel_tables(page):
                existing = next((f for f in figures if f['page']==index+1 and label(f['caption'])==('table',table['number'])), None)
                if existing:
                    if existing.get('auto_crop'):
                        existing.update(bbox=table['bbox'],caption=table['caption'],caption_zh='',crop_version=9)
                else:
                    figures.append({'id':f'fig-{next_id}','page':index+1,'caption':table['caption'],'bbox':table['bbox'],
                                    'kind':'table','region':'appendix' if appendix else 'main','selected':True,'auto_crop':True,'crop_version':9})
                    next_id += 1
    # Retire old bare prose references, keeping their IDs for old report snapshots.
    for f in figures:
        if f.get('auto_crop') and re.fullmatch(r'\s*Table\s*\d+\s*\.\s*', f['caption'], re.I):
            actual = next((other for other in figures if other is not f and label(other['caption']) == label(f['caption'])
                           and not re.fullmatch(r'\s*Table\s*\d+\s*\.\s*', other['caption'], re.I)), None)
            if actual:
                f['duplicate_of'] = actual['id']
    # Reuse an existing manually added crop when its newly discovered caption
    # describes the same area. Never replace the user's box or Chinese caption.
    for manual in figures:
        if manual.get('auto_crop') or manual.get('caption') != '用户选择的原文图表':
            continue
        a = manual['bbox']
        for found in figures:
            if not found.get('auto_crop') or found['page'] != manual['page']:
                continue
            b = found['bbox']
            overlap = max(0,min(a[2],b[2])-max(a[0],b[0])) * max(0,min(a[3],b[3])-max(a[1],b[1]))
            union = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-overlap
            if union > 0 and overlap / union > .75:
                manual.update(caption=found['caption'], kind=found.get('kind'), region=found.get('region'))
                found['duplicate_of'] = manual['id']
                break
    paper['figure_inventory_version'] = INVENTORY_VERSION
    return paper


def abstract_source(paper):
    """Keep the extracted original separately from its translation; never invent a missing abstract."""
    metadata = paper.get('abstract')
    if isinstance(metadata, str) and 40 <= len(metadata.strip()) <= 20000:
        return {'original': metadata.strip(), 'pages': [], 'status': 'source_metadata'}
    source = directory(paper['id']) / 'source.pdf'
    if not source.is_file():
        return {'original': '', 'pages': [], 'status': 'missing'}
    # Read layout-aware columns, never flattened two-column text. Require an
    # explicit end boundary rather than treating the rest of a page as abstract.
    heading = re.compile(r'^\s*(?:abstract|摘要)(?:\s*[—–:：.]\s*|\s+|$)', re.I)
    end = re.compile(r'^\s*(?:(?:1|I)[.．]?\s+\S|introduction\b|keywords\b|index terms\b|(?:Figure|Fig\.?|Table)\s+\d|(?:Email|Date|Code)\s*:)', re.I)
    with PDF_LOCK, pdfplumber.open(source) as pdf:
        for index, page in enumerate(pdf.pages[:3]):
            # A real gutter has body words on both sides but none across it.
            words = [w for w in page.extract_words() if page.height*.22 < w['top'] < page.height*.85]
            mid = page.width / 2
            two_columns = (sum(w['x0'] > mid+5 for w in words) > 15
                           and sum(w['x1'] < mid-5 for w in words) > 15
                           and not any(w['x0'] < mid-3 and w['x1'] > mid+3 for w in words))
            regions = [page.crop((0, 0, mid, page.height)), page.crop((mid, 0, page.width, page.height))] if two_columns else [page]
            for region in regions:
                lines = region.extract_text_lines(x_tolerance=1)
                for n, line in enumerate(lines):
                    match = heading.match(line['text'])
                    if not match:
                        continue
                    body = [line['text'][match.end():].strip()]
                    bounded = False
                    for following in lines[n+1:]:
                        text = following['text'].strip()
                        if end.match(text):
                            bounded = True
                            break
                        if re.fullmatch(r'\d+|arXiv:.*', text, re.I):
                            continue
                        body.append(text)
                    original = ' '.join(v for v in body if v).strip()
                    if bounded and 40 <= len(original) <= 20000:
                        return {'original': original, 'pages': [index+1], 'status': 'extracted'}
    # Some publishers use a single bold introductory abstract without an Abstract heading.
    # Require a long, homogeneous front-page block, not an arbitrary first paragraph.
    with PDF_LOCK, pdfplumber.open(directory(paper['id']) / 'source.pdf') as pdf:
        page = pdf.pages[0]
        groups, current = [], []
        for line in page.extract_text_lines(x_tolerance=1):
            chars = [c for c in line.get('chars', []) if c.get('upright', True)]
            sizes = sorted(c['size'] for c in chars)
            size = sizes[len(sizes)//2] if sizes else 0
            bold = sum('bold' in c.get('fontname','').lower() for c in chars) / max(1,len(chars))
            valid = (bold > .75 and 9 <= size <= 13 and len(line['text']) > 35
                     and page.height*.15 < line['top'] < page.height*.6
                     and line['x0'] < page.width*.3 and not figure_label(line['text']))
            if current and (not valid or line['top']-current[-1]['bottom'] > 12):
                groups.append(current); current = []
            if valid:
                current.append(line)
        if current:
            groups.append(current)
        candidates = [' '.join(l['text'] for l in group) for group in groups if len(group) >= 5]
        if len(candidates) == 1 and len(candidates[0]) >= 400:
            return {'original': candidates[0], 'pages': [1], 'status': 'extracted_unlabeled'}
    return {'original': '', 'pages': [], 'status': 'missing'}
