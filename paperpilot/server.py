import argparse
import json
import mimetypes
import os
import re
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import embodied_daily, conferences, workspace, model_setup
from . import discovery, documents, providers, service, store, user_profile, assistant_memory, collections, publication, credentials, abstracts, hf_daily, title_search, library, recommendation_chat, knowledge, historical, historical_pdf, paper_identity, accounts, codex_account, style_samples, style_cache, knowledge_schedule, hf_topics, hotspot_triage, paper_storage

TOKEN = secrets.token_urlsafe(32)


def export_report(ident, format):
    from .exports import export, validate_request
    paper = publication.apply(store.get('paper', ident))
    validate_request(paper, format)
    config = store.settings()
    return service.paper_job('export', ident, lambda progress: export(ident, format, progress, paper, config))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def response(self, body, status=200, mime='application/json', download=None):
        if mime == 'application/json':
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'SAMEORIGIN')
        self.send_header('Referrer-Policy', 'no-referrer')
        if download:
            self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + urllib.parse.quote(download))
        self.end_headers()
        self.wfile.write(body)

    def safe_origin(self):
        host = self.headers.get('Host', '')
        allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if host not in allowed:
            raise PermissionError('仅允许本机访问')
        origin = self.headers.get('Origin')
        if origin and origin not in {'http://' + h for h in allowed}:
            raise PermissionError('请求来源不匹配')

    def dispatch(self, method):
        with accounts.LOCK:
            if not accounts.enabled():
                return method()
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            try:
                self.safe_origin()
                public = path in ('/api/bootstrap', '/api/session', '/api/health')
                protected = (path.startswith(('/api/', '/files/')) and not public) or (path == '/api/bootstrap' and 'X-PaperPilot-Revision' in self.headers)
                if protected:
                    query = urllib.parse.parse_qs(parsed.query)
                    user = self.headers.get('X-PaperPilot-User', query.get('user', [''])[0])
                    revision = self.headers.get('X-PaperPilot-Revision', query.get('session', [''])[0])
                    current = accounts.public()
                    if user != (current['active'] or '') or revision != current['revision']:
                        return self.response({'error': '用户已切换，请刷新页面', 'account_changed': True}, 409)
                    if not current['active'] and not path.startswith('/api/accounts/'):
                        return self.response({'error': '请先创建用户'}, 403)
                with store.scope(accounts.binding(accounts.entry()) if accounts.entry() else None):
                    return method()
            except PermissionError as exc:
                return self.response({'error': str(exc)}, 403)

    def do_GET(self):
        self.dispatch(self.get)

    def do_POST(self):
        self.dispatch(self.post)

    def get(self):
        try:
            self.safe_origin()
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            if path == '/api/health':
                from .launcher import identity
                return self.response({'app': 'PaperPilot', 'instance': identity(), 'pid': os.getpid(),
                                      'desktop_nonce': os.environ.get('PAPERPILOT_DESKTOP_NONCE', ''),
                                      'busy': any(store.TASKS.values())})
            if path == '/api/conferences':
                return self.response(conferences.current())
            if path == '/api/embodied-daily':
                query = urllib.parse.parse_qs(parsed.query)
                return self.response(embodied_daily.listing(query.get('date', [None])[0]))
            if path == '/api/embodied-paper':
                query = urllib.parse.parse_qs(parsed.query)
                return self.response(embodied_daily.preview(query.get('id', [''])[0]))
            if path == '/api/session':
                return self.response(accounts.public())
            if path == '/api/style-cache':
                return self.response(style_cache.status())
            if path == '/api/model-setup':
                return self.response({'token': TOKEN, **model_setup.public(self.server.server_port)})
            if path == '/api/codex-status':
                return self.response(codex_account.status())
            if path == '/api/knowledge-schedule':
                return self.response(knowledge_schedule.status())
            if path == '/api/knowledge':
                query = urllib.parse.parse_qs(parsed.query)
                return self.response(knowledge.current(mainline=knowledge.default_mainline(query.get('mainline', [''])[0])))
            if path == '/api/bootstrap':
                if accounts.enabled() and not accounts.entry():
                    return self.response({'token': TOKEN, 'accounts': accounts.public(), 'jobs': []})
                papers = [publication.apply(library.initialize(p)) for p in store.all_objects('paper')]
                config = store.settings()
                mainline = urllib.parse.parse_qs(parsed.query).get('knowledge_mainline', [''])[0]
                if mainline not in {line['key'] for line in knowledge.mainline_options()}:
                    mainline = ''
                mainline = knowledge.default_mainline(mainline)
                return self.response({'token': TOKEN, 'accounts': accounts.public(), 'codex_setup': codex_account.setup(), 'style_samples': style_samples.public(), 'style_cache': style_cache.status(), 'settings': config, 'workspace': workspace.current(), 'embodied_daily': embodied_daily.links(), 'capabilities': providers.capabilities(config),
                                      'profile': user_profile.get(), 'memory_status': assistant_memory.status(), 'sources': {k: v for k, v in discovery.SOURCES.items() if v.get('kind') != 'news'}, 'papers': papers, 'reading_stats': library.statistics(papers),
                                      'knowledge': knowledge.current(mainline=mainline), 'historical_import': historical.latest(), 'knowledge_schedule': knowledge_schedule.status(),
                                      'reading_history': store.all_objects('reading_history'), 'analysis_jobs': service.analysis_statuses(),
                                      'hotspot_skips': hotspot_triage.public(), 'favorites': store.all_objects('favorite'), 'abstract_translations': store.all_objects('abstract_translation'), 'recommendation_chat': recommendation_chat.public(), 'routes': store.all_objects('route', limit=5), 'jobs': store.all_objects('job', limit=20)})
            if path.startswith('/api/job/'):
                return self.response(store.get('job', path.split('/')[-1]))
            match = re.fullmatch(r'/api/papers/([a-f0-9]{20})', path)
            if match:
                return self.response(publication.apply(store.get('paper', match[1])))
            match = re.fullmatch(r'/files/([a-f0-9]{20})/(source\.pdf|page-\d+\.png|fig-\d+\.png|report-[a-f0-9]+\.(?:pdf|pptx))', path)
            if match:
                ident, name = match.groups()
                store.get('paper', ident)
                folder = documents.directory(ident)
                if name.startswith('page-'):
                    return self.response(documents.page_bytes(ident, int(re.search(r'\d+', name)[0])), mime='image/png')
                elif name.startswith('fig-'):
                    p = store.get('paper', ident)
                    report_image = urllib.parse.parse_qs(parsed.query).get('report') == ['1']
                    figure_list = (p.get('report') or {}).get('figures', []) if report_image else p['figures']
                    f = next((f for f in figure_list if f['id'] + '.png' == name), None)
                    if not f:
                        raise ValueError('找不到图表')
                    return self.response(documents.figure_bytes(ident, f, quality='reading' if report_image else 'model'), mime='image/png')
                else:
                    file = (folder / 'exports' / name) if name.startswith('report-') else (folder / name)
                return self.response(file.read_bytes(), mime=mimetypes.guess_type(name)[0] or 'application/octet-stream',
                                     download=name if name.startswith('report-') else None)
            # Only static frontend and explicit KaTeX assets can be served; never expose data or keys.
            if path.startswith('/vendor/'):
                folder = store.ROOT / 'node_modules/katex/dist'
                rel = path[len('/vendor/'):]
            else:
                folder = store.ROOT / 'web'
                rel = path.lstrip('/') or 'index.html'
            target = (folder / rel).resolve()
            if not target.is_relative_to(folder.resolve()) or not target.is_file():
                return self.response({'error': '找不到文件'}, 404)
            return self.response(target.read_bytes(), mime=mimetypes.guess_type(str(target))[0] or 'application/octet-stream')
        except PermissionError as e:
            self.response({'error': str(e)}, 403)
        except (ValueError, FileNotFoundError) as e:
            self.response({'error': str(e)}, 404)
        except Exception:
            self.response({'error': '读取失败，请检查本地文件'}, 500)

    def post(self):
        try:
            self.safe_origin()
            if self.headers.get('X-PaperPilot-Token') != TOKEN:
                raise PermissionError('会话已失效，请刷新页面')
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 40 * 1024 * 1024:
                raise ValueError('请求大小超出限制')
            raw = self.rfile.read(length)
            path = urllib.parse.urlparse(self.path).path
            if path == '/api/style-samples/upload':
                filename = urllib.parse.unquote(self.headers.get('X-Filename', 'example.pdf'))
                items = style_samples.upload(raw, filename)
                style_cache.start()
                return self.response({'items': items, 'style_cache': style_cache.status()})
            if path == '/api/upload':
                filename = urllib.parse.unquote(self.headers.get('X-Filename', 'paper.pdf'))
                favorite_id = self.headers.get('X-Favorite-Id')
                favorite = store.get('favorite', favorite_id) if favorite_id else None
                target_id = self.headers.get('X-Paper-Id')
                if target_id and (store.get('paper', target_id).get('pdf_released') or self.headers.get('X-Restore-Mode') == 'manual'):
                    with service.SAVE_LOCK:
                        return self.response(paper_storage.manual_restore(target_id, raw, filename))
                if target_id and not store.get('paper', target_id).get('metadata_only'):
                    raise ValueError('此论文已经有 PDF')
                with service.SAVE_LOCK:
                    paper = documents.ingest(raw, filename, target_id=target_id)
                if favorite:
                    paper = collections.finish_import(favorite, paper['id'])
                return self.response(paper)
            body = json.loads(raw)
            if path == '/api/workspace':
                return self.response(workspace.save(body))
            if path == '/api/conferences/focus':
                return self.response(conferences.focus(body.get('series_id')))
            if path == '/api/conferences/import':
                return self.response(conferences.import_catalog(body.get('catalog')))
            if path == '/api/conferences/check':
                return self.response(conferences.start_check())
            if path == '/api/conferences/schedule':
                return self.response(conferences.configure(body.get('enabled')))

            if path == '/api/crop-page-text':
                from . import caption_selection
                return self.response(caption_selection.page_text(body['id'], body['page']))
            if path == '/api/crop-caption-translate':
                from . import caption_selection
                return self.response(caption_selection.translate(body['id'], body['page'], body['text']))
            if path == '/api/accounts/create':
                return self.response(accounts.create(body.get('name')))
            if path == '/api/accounts/switch':
                return self.response(accounts.switch(body.get('id')))
            if path == '/api/accounts/delete':
                return self.response(accounts.delete(body.get('id'), body.get('name')))
            if path == '/api/knowledge-schedule':
                return self.response(knowledge_schedule.configure(body))
            if path == '/api/knowledge-schedule-retry':
                knowledge_schedule.tick(retry=True)
                return self.response(knowledge_schedule.status())
            if path == '/api/knowledge-update':
                return self.response(knowledge.start(body.get('rebuild', False), body.get('mainline', ''), body.get('scope', 'all')))
            if path == '/api/historical-import':
                return self.response(historical.start(body.get('text'), body.get('target')))
            if path == '/api/historical-pdf-metadata':
                return self.response(historical_pdf.extract(body['id']))
            if path == '/api/historical-pdf-date':
                return self.response(historical_pdf.find_date(body['id'],body['title']))
            if path == '/api/historical-pdf-finish':
                return self.response(historical_pdf.finish(body['id'],body['title'],body['month'],body['short_title'],body['target']))
            if path == '/api/paper-report-preview':
                return self.response(paper_storage.report_preview(body['id']))
            if path == '/api/paper-report-delete':
                return self.response(paper_storage.delete_report(body['id'], body.get('revision')))
            if path == '/api/paper-report-batch-preview':
                return self.response(paper_storage.batch_storage(body.get('ids'), reports=True))
            if path == '/api/paper-report-batch-delete':
                return self.response(paper_storage.batch_storage(body.get('ids'), reports=True, release_files=True, revisions=body.get('revisions')))
            if path == '/api/paper-storage-batch-preview':
                return self.response(paper_storage.batch_storage(body.get('ids')))
            if path == '/api/paper-storage-batch-release':
                return self.response(paper_storage.batch_storage(body.get('ids'), release_files=True))
            if path == '/api/paper-storage-preview':
                return self.response(paper_storage.preview(body['id']))
            if path == '/api/paper-storage-release':
                return self.response(paper_storage.release(body['id']))
            if path == '/api/paper-storage-restore':
                return self.response(paper_storage.download(body['id']))
            if path == '/api/paper-download':
                return self.response(historical.download(body['id']))
            if path == '/api/import':
                return self.response(service.import_paper(body.get('url'), body.get('favorite_id')))
            if path == '/api/style-samples':
                items = style_samples.change(body['id'], body.get('action'), body.get('enabled'))
                style_cache.start()
                return self.response({'items': items, 'style_cache': style_cache.status()})
            if path == '/api/style-mode':
                mode = style_samples.set_mode(body.get('mode'))
                style_cache.start()
                return self.response({'items': style_samples.public(), 'mode': mode, 'style_cache': style_cache.status()})
            if path == '/api/style-cache':
                style_cache.start()
                return self.response(style_cache.status())
            if path == '/api/deepseek-key':
                with store.LOCK:
                    c = store.settings()
                    if body.get('action') == 'reset':
                        credentials.delete()
                        providers.KEYS.pop(providers.session_key('deepseek'), None)
                        c['deepseek_key_reset'] = True
                    elif body.get('action') == 'confirm':
                        if providers.api_key('deepseek'):
                            raise ValueError('请先重置，再输入新的 API Key')
                        credentials.save(body.get('key'))
                        providers.KEYS.pop(providers.session_key('deepseek'), None)
                        c['deepseek_key_reset'] = False
                    else:
                        raise ValueError('未知密钥操作')
                    store.save_settings(c)
                    return self.response({'capabilities': providers.capabilities(c)})
            if path == '/api/settings':
                with store.LOCK:
                    c = store.settings()
                    provider = body.get('provider', c['provider'])
                    if provider not in ('codex', 'deepseek'):
                        raise ValueError('未知接入方式')
                    c['provider'] = provider
                    c['model'] = str(body.get('model', c['model']))[:150]
                    from . import reasoning
                    if set(body) & {'reasoning', 'knowledge_deep_thinking', 'codex_reasoning_effort', 'codex_detail_reasoning_effort'}:
                        raise ValueError('请使用统一的场景配置；辅助任务档位由工具管理')
                    if 'reasoning_policy' in body:
                        c['reasoning_policy'] = reasoning.validate_policy(body['reasoning_policy'])
                    c['reasoning'] = reasoning.effective(c)
                    c['knowledge_deep_thinking'] = c['reasoning']['knowledge'] == 'high'

                    if 'web_supplement_enabled' in body:
                        if type(body['web_supplement_enabled']) is not bool:
                            raise ValueError('请选择是否启用联网补充')
                        c['web_supplement_enabled'] = body['web_supplement_enabled']
                    c['vision'] = bool(body.get('vision', c['vision']))
                    if 'deepseek' in body:
                        if set(body['deepseek']) & {'thinking', 'detail_thinking'}:
                            raise ValueError('请使用统一的场景配置调整思考档位')
                        thinking = c['deepseek'].get('thinking', 'low')
                        detail_thinking = c['deepseek'].get('detail_thinking', 'high')
                        c['deepseek'] = {'base_url': providers.validate_endpoint(body['deepseek']['base_url']), 'model': str(body['deepseek']['model'])[:150], 'thinking': thinking,
                                'detail_model': str(body['deepseek'].get('detail_model', c['deepseek'].get('detail_model', 'deepseek-flash')))[:150], 'detail_thinking':detail_thinking}
                    c['context_chars'] = max(10000, min(240000, int(body.get('context_chars', c['context_chars']))))
                    c['output_tokens_auto'] = bool(body.get('output_tokens_auto', c['output_tokens_auto']))
                    c['output_tokens'] = max(2000, min(131072, int(body.get('output_tokens', c['output_tokens']))))
                    if 'discovery_sources' in body:
                        c['discovery_sources'] = discovery.validate_search_sources(body['discovery_sources'])
                    if body.get('schedule', {}).get('enabled'):
                        raise ValueError('定时关键词推荐已停用，请在发现与学习中手动筛选')
                    key = body.get('deepseek_key', '')
                    if not isinstance(key, str):
                        raise ValueError('API Key 格式无效')
                    key = key.strip()
                    if body.get('clear_deepseek_key'):
                        credentials.delete()
                        providers.KEYS.pop(providers.session_key('deepseek'), None)
                    elif key or body.get('persist_deepseek_key'):
                        credentials.save(key or providers.api_key('deepseek'))
                        c['deepseek_key_reset'] = False
                        providers.KEYS.pop(providers.session_key('deepseek'), None)
                    store.save_settings(c)
                    return self.response({'settings': c, 'capabilities': providers.capabilities(c)})
            if path == '/api/test-provider':
                from . import reasoning
                return self.response(service.job('connection', lambda progress: providers.generate(reasoning.for_level(store.settings(), 'low'), '用中文简短回应，不调用工具。', [{'role': 'user', 'content': '回复“连接成功”即可。'}])))
            if path == '/api/paper-info':
                return self.response(service.refresh_paper_info(body['id']))
            if path == '/api/author-citations':
                return self.response(service.save_author_citations(body['id'], body.get('citations')))
            if path == '/api/profile-display':
                return self.response({'profile': user_profile.save_display(body)})
            if path == '/api/profile':
                return self.response({'profile': user_profile.save_research(body['profile'])})
            if path == '/api/memory':
                return self.response(assistant_memory.configure(body.get('enabled')))
            if path == '/api/memory-clear':
                return self.response(assistant_memory.clear())
            if path == '/api/paper-update':
                if 'read_status' in body:
                    raise ValueError('阅读状态由阅读操作自动更新')
                with service.SAVE_LOCK:
                    p = store.get('paper', body['id'])
                    if 'publication_month' in body:
                        p.update(publication_month=publication.validate_month(body['publication_month']), publication_date_source='手动填写')
                        publication.apply(p)
                    if 'short_title' in body:
                        p.update(short_title=paper_identity.short_title(body['short_title']), short_title_source='manual')
                    if 'short_title' in body or 'publication_month' in body:
                        paper_identity.validate(p, required=bool(p.get('starred') or p.get('liked') or p.get('read_status') in library.COMPLETED))
                    if 'reading_outline' in body or 'paper_type' in body:
                        from . import paper_types
                        paper_types.update(p, body)
                    if 'notes' in body:
                        if not isinstance(body['notes'], str) or len(body['notes']) > 20000:
                            raise ValueError('个人思考最多 20000 字符')
                        p['notes'] = body['notes']
                        p['notes_updated_at'] = service.now()
                    for key in ('feedback', 'title'):
                        if key in body:
                            p[key] = str(body[key])[:4000 if key == 'feedback' else 300]
                    if 'figures' in body:
                        if p.get('pdf_released'):
                            raise ValueError('请先恢复原文 PDF，再调整图表')
                        figures = body['figures']
                        if not isinstance(figures, list) or len(figures) > 600:
                            raise ValueError('最多保存 600 张图表')
                        known_ids = {f['id'] for f in p['figures']}
                        next_id = documents.next_figure_number(p)
                        seen = set()
                        for f in figures:
                            if not isinstance(f, dict):
                                raise ValueError('图表结构无效')
                            if 'id' not in f:
                                f['id'] = 'fig-' + str(next_id)
                                next_id += 1
                            elif f['id'] not in known_ids:
                                raise ValueError('未知图表 ID')
                            if f['id'] in seen:
                                raise ValueError('图表 ID 重复')
                            seen.add(f['id'])
                            f['caption'] = str(f.get('caption', ''))[:1600]
                            f['caption_zh'] = str(f.get('caption_zh', ''))[:1600]
                            label = documents.figure_label(f['caption'])
                            if label:
                                f['kind'] = label[0]
                            f['selected'] = bool(f.get('selected'))
                            documents.crop_figure(p['id'], f)
                        p['last_figure_number'] = next_id - 1
                        p['figures'] = figures
                        if p.get('report'):
                            p['report']['figures'] = [next((dict(f) for f in figures if f['id'] == old['id']), old) for old in p['report'].get('figures', [])]
                    store.save('paper', p)
                    for field, kind in [('notes', '个人思考'), ('feedback', '论文反馈')]:
                        if field in body:
                            if not p[field].strip():
                                assistant_memory.forget_paper(p['id'], [kind])
                            else:
                                assistant_memory.capture(kind, p[field], p['id'], p['title'])
                from . import image_cache
                image_cache.trim()
                return self.response(p)
            if path == '/api/paper-reading':
                return self.response(library.change(body['id'], body.get('action'), body.get('report_at'), body.get('starred'), body.get('preference')))
            if path == '/api/paper-delete':
                if not isinstance(body.get('keep_history'), bool):
                    raise ValueError('请选择是否保留阅读记录')
                return self.response(service.delete_paper(body['id'], body['keep_history']))
            if path == '/api/history-delete':
                store.remove('reading_history', body['id'])
                assistant_memory.forget_paper(body['id'])
                return self.response({'ok': True})
            if path == '/api/figure-remove':
                return self.response(documents.remove_figure(body['id'], body.get('figure_id'), body.get('expected')))
            if path == '/api/captions':
                return self.response(service.translate_captions(body['id']))
            if path == '/api/analyze':
                return self.response(service.analyze(body['id'], body.get('mode', 'overview'), body.get('figure_scope', 'all'), body.get('reading_outline')))
            if path == '/api/analysis-cancel':
                return self.response(service.cancel_analysis(body['job_id']))
            if path == '/api/chat-cancel':
                return self.response(service.cancel_chat(body['job_id']))
            if path == '/api/chat':
                return self.response(service.chat(body['id'], body['question']))
            if path == '/api/export':
                return self.response(export_report(body['id'], body['format']))
            if path == '/api/hotspot-skip':
                return self.response(hotspot_triage.skip(body))
            if path == '/api/hotspot-restore':
                return self.response(hotspot_triage.restore(body.get('id')))
            if path == '/api/model-discuss':
                return self.response(recommendation_chat.discuss(body.get('question'), body.get('revision')))
            if path == '/api/model-recommendations':
                return self.response(recommendation_chat.recommend(body.get('revision')))
            if path == '/api/model-discussion-reset':
                return self.response(recommendation_chat.reset())
            if path == '/api/hf-classify':
                return self.response(hf_topics.start(body.get('id')))
            if path == '/api/hf-classification':
                return self.response(hf_topics.view(store.get('hf_listing', body.get('id'))))
            if path == '/api/hf-list':
                return self.response(hf_topics.view(hf_daily.refresh(body.get('days', 1), bool(body.get('force', False)))))
            if path == '/api/title-search':
                query = title_search.validate_query(body.get('query'))
                if body.get('async'):
                    return self.response(service.job('title-search', lambda progress: title_search.search(query, progress)))
                return self.response(title_search.search(query))
            if path == '/api/favorite':
                return self.response(collections.save(body.get('origin'), body.get('run_id'), body.get('paper_id')))
            if path == '/api/favorite-update':
                return self.response(collections.change(body['id'], body['action']))
            if path == '/api/discovery-delete':
                store.get('discovery', body['id'])
                store.remove('discovery', body['id'])
                return self.response({'ok': True})
            if path == '/api/abstract-translate':
                return self.response(abstracts.translate(body.get('origin'), body.get('run_id'), body.get('paper_id'), body.get('language')))
            if path == '/api/recommend':
                return self.response(service.recommend(body['query'], max(0, min(3650, int(body.get('days', 30)))), body.get('sources'), body.get('count', 2)))
            if path == '/api/route':
                return self.response(service.learning_route(str(body.get('question', ''))[:1000], body.get('sources')))
            self.response({'error': '未知操作'}, 404)
        except PermissionError as e:
            self.response({'error': str(e)}, 403)
        except (ValueError, KeyError) as e:
            self.response({'error': str(e)}, 400)
        except Exception:
            self.response({'error': '操作失败，请检查网络、PDF 文件或运行环境'}, 500)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--codex-login', metavar='USERNAME')
    args = parser.parse_args()
    if args.codex_login:
        return codex_account.login(args.codex_login)
    with accounts.instance_lock():
        serve(args.port)


def serve(port):
    accounts.initialize(legacy_name=os.environ.get("PAPERPILOT_LEGACY_USER", "default"))
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    def scheduler():
        while True:
            try:
                with accounts.LOCK:
                    for user in accounts.registry()['users']:
                        with store.scope(accounts.binding(user)):
                            service.schedule_tick()
            except Exception:
                pass
            time.sleep(45)
    threading.Thread(target=scheduler, daemon=True).start()
    print(f'PaperPilot running: http://127.0.0.1:{port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == '__main__':
    main()
