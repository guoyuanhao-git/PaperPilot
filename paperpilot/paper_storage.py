"""Release reproducible source files without deleting a user's reading work."""
import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path
from datetime import datetime, timezone
from . import store, documents, discovery


def recover():
    """Finish committed cleanup or roll back an interrupted pre-commit release."""
    for paper in store.all_objects('paper'):
        folder = documents.directory(paper['id'])
        replacement = folder / '.restore-staging'
        if replacement.exists():
            manifest = json.loads((replacement / 'manifest.json').read_text())
            if paper.get('source_storage', {}).get('manual_revision') != manifest['token']:
                for name in ('source.pdf', 'pages.json'):
                    backup = replacement / ('old-' + name)
                    if backup.exists():
                        backup.replace(folder / name)
                    elif name not in manifest['existing']:
                        (folder / name).unlink(missing_ok=True)
            else:
                for path in folder.glob('page-*.png'):
                    path.unlink(missing_ok=True)
            shutil.rmtree(replacement)
        staging = folder / '.release-staging'
        if not staging.exists():
            continue
        if not paper.get('pdf_released'):
            for path in staging.iterdir():
                path.replace(folder / path.name)
        shutil.rmtree(staging)


def idle(ident, allow_restore=False):
    # Graph jobs can read this paper without carrying a paper_id.
    if any(j.get('status') in ('queued', 'running') and not
           (allow_restore and j.get('kind') == 'restore_pdf' and j.get('paper_id') == ident)
           for j in store.all_objects('job')):
        raise ValueError('还有任务正在运行，请完成后再释放或替换原文')


def restore_url(paper, pages=None):
    try:
        ident = discovery.arxiv_id(paper.get('source_url') or '')
    except ValueError:
        return ''
    base = re.sub(r'v\d+$', '', ident)
    text = '\n'.join(p.get('text', '') for p in (pages or [])[:2])
    match = re.search(re.escape(base) + r'(v\d+)\b', text)
    if match:
        ident = base + match[1]
    return 'https://arxiv.org/abs/' + ident


def candidates(folder, keep):
    paths = [folder / 'source.pdf', *folder.glob('page-*.png'), *folder.glob('crop-*.png')]
    return [p for p in paths if p.is_file() and p.name not in keep] + [p for p in folder.glob('build-*') if p.is_dir() and re.fullmatch(r'build-[a-f0-9]{12}', p.name)]


def disk_size(path):
    return sum(p.stat().st_size for p in path.rglob('*') if p.is_file()) if path.is_dir() else path.stat().st_size


def prepare(paper):
    folder = documents.directory(paper['id'])
    if paper.get('pdf_released') or not (folder / 'source.pdf').is_file():
        raise ValueError('原文 PDF 已不在本地')
    try:
        pages = json.loads((folder / 'pages.json').read_text())
    except (OSError, ValueError):
        raise ValueError('缺少已提取的正文，暂不能释放原文') from None
    if not isinstance(pages, list) or not any(isinstance(p, dict) and str(p.get('text', '')).strip() for p in pages):
        raise ValueError('尚无可保留的正文文字，暂不能释放原文')
    # Every report image must remain viewable/exportable, including manually cropped versions.
    before = {p.name for p in folder.iterdir()}
    try:
        keep = {documents.crop_figure(paper['id'], f).name for f in (paper.get('report') or {}).get('figures', [])}
    except Exception:
        for path in [*folder.glob('page-*.png'), *folder.glob('crop-*.png')]:
            if path.name not in before:
                path.unlink(missing_ok=True)
        raise
    finally:
        for path in folder.glob('page-*.png'):
            if path.name not in before:
                path.unlink(missing_ok=True)
    files = candidates(folder, keep)
    created = [folder / name for name in keep if name not in before]
    # Count net space saved, not temporary page renders generated during preparation.
    size = sum(disk_size(p) for p in files) - sum(disk_size(p) for p in created)
    return pages, keep, files, created, size


def preview(ident):
    from .service import SAVE_LOCK
    with SAVE_LOCK, documents.PDF_LOCK:
        idle(ident)
        paper = store.get('paper', ident)
        pages, keep, files, created, size = prepare(paper)
        try:
            return {'bytes': max(0, size), 'images_kept': len(keep),
                    'can_download': bool(restore_url(paper, pages))}
        finally:
            for path in created:
                path.unlink(missing_ok=True)


def release(ident):
    from .service import SAVE_LOCK
    from .knowledge_sources import local_revision
    with SAVE_LOCK, documents.PDF_LOCK:
        idle(ident)
        paper = store.get('paper', ident)
        pages, keep, files, created, size = prepare(paper)
        if size <= 0:
            for path in created:
                path.unlink(missing_ok=True)
            raise ValueError('保留报告图表后没有可释放的空间，原文保持不变')
        folder = documents.directory(ident)
        source = folder / 'source.pdf'
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        revision = local_revision(paper)
        staging = folder / '.release-staging'
        if staging.exists():
            raise ValueError('上次空间清理尚未完成，请检查存储目录后再试')
        staging.mkdir()
        moved = []
        try:
            for path in files:
                path.rename(staging / path.name)
                moved.append(path)
            paper.update(pdf_released=True, pdf_cached=False,
                         source_storage={**paper.get('source_storage', {}), 'sha256': digest, 'revision': revision,
                                         'retained_images': sorted(keep),
                                         'restore_url': restore_url(paper, pages),
                                         'released_at': datetime.now(timezone.utc).isoformat()})
            store.save('paper', paper)
        except Exception:
            for path in moved:
                (staging / path.name).replace(path)
            staging.rmdir()
            for path in created:
                path.unlink(missing_ok=True)
            raise
        try:
            shutil.rmtree(staging)
        except OSError:
            # Do not claim space that is still allocated. Retain the committed state.
            raise ValueError('原文已停用，但暂存文件清理失败，尚未完全释放空间；请检查磁盘权限') from None
        return {'paper': paper, 'freed_bytes': size}


def restore_bytes(ident, data, expected_storage=None):
    from .service import SAVE_LOCK
    with SAVE_LOCK, documents.PDF_LOCK:
        paper = store.get('paper', ident)
        # A download started against an older release may never overwrite a manual choice.
        if expected_storage is not None and (paper.get('source_storage') != expected_storage or not paper.get('pdf_released')):
            return paper
        if not paper.get('pdf_released'):
            raise ValueError('此论文已有原文 PDF')
        if hashlib.sha256(data).hexdigest() != paper.get('source_storage', {}).get('sha256'):
            raise ValueError('这份 PDF 与释放前的版本不同，未替换原文。请上传原来的 PDF，避免报告页码和裁剪错位')
        folder = documents.directory(ident)
        target = folder / 'source.pdf'
        temp = folder / 'source.restore'
        try:
            temp.write_bytes(data)
            temp.replace(target)
            paper.update(pdf_released=False, pdf_cached=True)
            store.save('paper', paper)
        except Exception:
            temp.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            raise
        return paper


def manual_restore(ident, data, filename='paper.pdf'):
    """A user's replacement wins over any in-flight automatic restoration."""
    from .service import SAVE_LOCK
    with SAVE_LOCK, documents.PDF_LOCK:
        idle(ident, allow_restore=True)
        paper = store.get('paper', ident)
        if not paper.get('source_storage'):
            raise ValueError('此论文尚未释放过原文')
        if len(data) > 40 * 1024 * 1024 or not data.startswith(b'%PDF-'):
            raise ValueError('请提供不超过 40 MB 的 PDF 文件')
        digest = hashlib.sha256(data).hexdigest()
        if any(p['id'] != ident and (p.get('pdf_sha256') or p['id']) == digest[:20]
               for p in store.all_objects('paper')):
            raise ValueError('这份 PDF 已属于另一篇论文，请选择此论文的文件')
        pages, figures, _, _ = documents.extract_pdf(data)
        folder = documents.directory(ident)
        # Pin the old report's images before switching its underlying PDF version.
        for figure in (paper.get('report') or {}).get('figures', []):
            figure['image_file'] = documents.crop_figure(ident, figure).name
        staging = folder / '.restore-staging'
        token = uuid.uuid4().hex
        if staging.exists():
            raise ValueError('上次恢复尚未完成，请重启应用后再试')
        staging.mkdir()
        existing = [name for name in ('source.pdf', 'pages.json') if (folder / name).exists()]
        (staging / 'manifest.json').write_text(json.dumps({'token': token, 'existing': existing}))
        committed = False
        try:
            candidate = staging / 'source.pdf'
            candidate.write_bytes(data)
            paper.update(pdf_released=False, pdf_cached=True, pdf_sha256=digest[:20],
                         filename=Path(filename).name,
                         page_count=len(pages), text_chars=sum(len(p['text']) for p in pages), figures=figures)
            if digest != paper['source_storage'].get('sha256'):
                paper.pop('abstract', None)
                paper.pop('abstract_record', None)
            paper.pop('figure_inventory_version', None)
            documents.inventory(paper, source_path=candidate)
            paper['source_storage'] = {**paper['source_storage'], 'sha256': digest,
                                      'content_revision': digest, 'manual_revision': token}
            paper['source_storage'].pop('revision', None)
            # A newer uploaded PDF may carry its own pinned arXiv version.
            paper['source_storage']['restore_url'] = restore_url(paper, pages)
            (staging / 'pages.json').write_text(json.dumps(pages, ensure_ascii=False))
            for name in ('source.pdf', 'pages.json'):
                if name in existing:
                    (folder / name).replace(staging / ('old-' + name))
                (staging / name).replace(folder / name)
            store.save('paper', paper)
            committed = True
        finally:
            if not committed:
                for name in ('source.pdf', 'pages.json'):
                    backup = staging / ('old-' + name)
                    if backup.exists():
                        backup.replace(folder / name)
                    elif name not in existing:
                        (folder / name).unlink(missing_ok=True)
            else:
                for path in folder.glob('page-*.png'):
                    path.unlink(missing_ok=True)
            shutil.rmtree(staging)
        return paper


def cleanup_report_images(paper, previous_report):
    """Only after a new report is committed, retire its predecessor's retained images."""
    if paper.get('pdf_released'):
        return
    with documents.PDF_LOCK:
        try:
            keep = {documents.crop_figure(paper['id'], f).name
                    for f in (paper.get('report') or {}).get('figures', [])}
        except (OSError, ValueError):
            return  # The saved report wins over optional cache cleanup.
        old = set(paper.get('source_storage', {}).get('retained_images', []))
        old.update(f.get('image_file', '') for f in (previous_report or {}).get('figures', []))
        for name in old - keep:
            if re.fullmatch(r'crop-[a-f0-9]{16}\.png', name):
                try:
                    (documents.directory(paper['id']) / name).unlink(missing_ok=True)
                except OSError:
                    pass


def download(ident):
    from . import service
    with service.SAVE_LOCK:
        idle(ident)
        paper = store.get('paper', ident)
        if not paper.get('pdf_released'):
            raise ValueError('原文无需恢复')
        url = paper.get('source_storage', {}).get('restore_url')
        if not url:
            raise ValueError('没有可自动下载的原文地址，请上传原来的 PDF')
        def work(progress):
            progress('下载原文并核对文件版本')
            data, _, _ = discovery.download(url)
            restore_bytes(ident, data, expected_storage=paper['source_storage'])
            return {'paper_id': ident}
        return service.paper_job('restore_pdf', ident, work)
