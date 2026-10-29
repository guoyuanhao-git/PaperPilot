import json
import os
import shutil
import subprocess
import sys
import uuid
import copy
from pathlib import Path

from . import documents, store, publication


def validate_request(paper, format):
    if format not in ('pdf','pptx'):
        raise ValueError('仅支持 PDF 和 PPTX')
    if format == 'pptx':
        if paper.get('metadata_only') or paper.get('pdf_released'):
            raise ValueError('请先下载或上传原文 PDF，再生成讲解 PPT')
    elif not paper.get('report'):
        raise ValueError('请先生成论文解读')


def export(ident, format, progress, paper=None, config=None):
    paper = copy.deepcopy(paper or publication.apply(store.get('paper', ident)))
    validate_request(paper, format)
    if format=='pptx':
        from . import presentations
        return presentations.export(paper,config or store.settings(),progress)
    snapshot = copy.deepcopy(paper['report'])
    node = shutil.which('node')
    if not node:
        raise ValueError('导出需要 Node.js，请安装或使用 Codex 自带运行环境')
    token = uuid.uuid4().hex[:12]
    directory = documents.directory(ident)
    build = directory / ('build-' + token)
    build.mkdir()
    output_dir = directory / 'exports'
    output_dir.mkdir(exist_ok=True)
    payload = {'paper': paper, 'format': format, 'output': str(output_dir / f'report-{token}.{format}'), 'build': str(build)}
    figures = paper['report'].get('figures', [])
    for f in figures:
        # Freeze actual image bytes so changing a crop later cannot change a completed export.
        source = documents.crop_figure(ident, f)
        target = build / (f['id'] + '.png')
        shutil.copyfile(source, target)
        f['path'] = str(target)
    source = build / 'report.json'
    source.write_text(json.dumps(payload, ensure_ascii=False))
    progress('排版公式、正文与原文图表')
    env = dict(os.environ)
    env.setdefault('PAPERPILOT_PYTHON', sys.executable)
    try:
        process = subprocess.run([node, str(store.ROOT / 'tools/export.mjs'), str(source)],
                                 capture_output=True, text=True, timeout=600, env=env)
    except subprocess.TimeoutExpired:
        raise ValueError('导出超时，解读仍已保存，可重新导出') from None
    if process.returncode != 0 or not Path(payload['output']).is_file():
        (build / 'export-error.log').write_text(process.stderr[-12000:])
        raise ValueError('导出失败，请确认 Node.js、KaTeX 和浏览器运行环境已配置。解读内容仍已保存。')
    info = {'format': format, 'url': f'/files/{ident}/report-{token}.{format}', 'filename': f'report-{token}.{format}', 'source_report_at': snapshot.get('generated_at')}
    from .service import SAVE_LOCK
    with SAVE_LOCK:
        current = publication.apply(store.get('paper', ident))
        if current.get('report') != snapshot:
            Path(payload['output']).unlink(missing_ok=True)
            raise ValueError('生成期间论文解读发生了更新，本次文件未挂入新报告；请重新导出')
        current.setdefault('exports', []).append(info)
        store.save('paper', current)
    return info
