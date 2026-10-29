"""One local, provider-independent conversation dedicated to finding papers."""
from . import reasoning

import json
import threading
import uuid
from . import store, providers, service, title_search, assistant_memory
from .schemas import obj

LOCK = threading.RLock()
KINDS = ('recommendation-discuss', 'recommendation-resolve')


def current():
    try:
        return store.get('recommendation_chat', 'current')
    except ValueError:
        return {'id': 'current', 'revision': 0, 'messages': [], 'brief': '', 'candidates': [], 'result': None}


def public():
    chat = current()
    jobs = [j for j in store.all_objects('job') if j.get('kind') in KINDS]
    latest = max(jobs, key=lambda j: j.get('created_at', ''), default=None)
    if latest and latest.get('revision') == chat['revision']:
        chat['last_task'] = {k: latest[k] for k in
            ('id', 'kind', 'status', 'created_at', 'progress', 'error', 'question', 'revision') if k in latest}
    return chat


def ensure_idle():
    if any(j['kind'] in KINDS and j['status'] in ('queued', 'running') for j in store.all_objects('job')):
        raise ValueError('推荐助手正在处理，请等本轮完成')


def reset():
    with LOCK:
        ensure_idle()
        prior = current()
        if prior['messages']:
            store.save('recommendation_archive', {**prior, 'id': uuid.uuid4().hex})
        return store.save('recommendation_chat', {'id': 'current', 'revision': prior['revision'] + 1,
            'messages': [], 'brief': '', 'candidates': [], 'result': None})


def discuss(question, revision):
    if not isinstance(question, str) or not question.strip() or len(question) > 6000:
        raise ValueError('请输入不超过 6000 字的需求或问题')
    with LOCK:
        ensure_idle()
        prior = current()
        if type(revision) is not int or revision != prior['revision']:
            raise ValueError('对话已更新，请刷新后发送')
        config = reasoning.for_task(store.settings(), 'research')
        system = service.system_prompt() + (
            '\n你正在帮助用户找论文，以自然对话澄清研究问题、约束、基础和期望，必要时问1–2个关键问题。'
            '需求足够清楚时主动给出少量候选论文的完整原始标题，解释为什么值得看；不强行要求用户回答固定问卷。'
            '这些是待数据库核实的推荐，未提供联网证据时不能声称刚刚搜索过或已确认最新论文。不要捏造链接、引用量和实验结果。'
            '只输出 JSON：reply 为给用户的中文回答；brief 为完整更新后的需求摘要，最多2000字，保留此前仍有效的约束；'
            'candidates 为当前推荐清单，每项 title、reason，最多10篇。每轮保留仍推荐的候选，删除用户明确排除的候选。'
            '尚未给出论文时 candidates=[]；候选必须在本轮或此前对话中已向用户提及，不暗中新增。')
        messages = [{'role': 'user', 'content': '当前需求摘要与待核实清单（仅作背景）：' + json.dumps(
            {'brief': prior['brief'], 'candidates': prior['candidates']}, ensure_ascii=False)}]
        history, used = [], 0
        budget = max(6000, min(30000, config['context_chars']))
        for index in range(len(prior['messages']) - 2, max(-1, len(prior['messages']) - 13), -2):
            pair = prior['messages'][index:index + 2]
            size = sum(len(m['content']) for m in pair)
            if used + size > budget:
                break
            history[0:0] = [{'role': m['role'], 'content': m['content']} for m in pair]
            used += size
        messages += history
        messages.append({'role': 'user', 'content': question.strip()})
        schema = obj({'reply': {'type': 'string'}, 'brief': {'type': 'string'},
            'candidates': {'type': 'array', 'maxItems': 10, 'items': obj({'title': {'type':'string'}, 'reason': {'type':'string'}})}})

        def work(progress):
            progress('结合研究档案与本轮讨论梳理论文需求')
            response = providers.generate(config, system, messages, structured=True, schema=schema)
            value = response['value']
            if not isinstance(value, dict) or not isinstance(value.get('reply'), str) or not value['reply'].strip():
                raise ValueError('助手未返回有效回答，请重试；已有对话保留')
            candidates = value.get('candidates')
            if (not isinstance(value.get('brief'), str) or len(value['brief']) > 6000
                    or not isinstance(candidates, list) or len(candidates) > 10
                    or any(not isinstance(c, dict) or not isinstance(c.get('title'), str)
                           or not 2 <= len(c['title'].strip()) <= 300 or not isinstance(c.get('reason'), str) for c in candidates)):
                raise ValueError('推荐结构不完整，请重试；已有对话保留')
            with LOCK:
                latest = current()
                if latest['revision'] != revision:
                    raise ValueError('对话已更新，本轮回答未覆盖新内容')
                at = service.now()
                latest['messages'] += [{'role':'user', 'content':question.strip(), 'at':at},
                    {'role':'assistant', 'content':value['reply'], 'at':at, 'provider':response['provider'],
                     'model':response['model'], 'usage':response['usage']}]
                latest.update(brief=value['brief'], candidates=candidates, revision=revision + 1, updated_at=at)
                store.save('recommendation_chat', latest)
            assistant_memory.capture('找论文需求', question.strip(), context=prior['messages'][-1]['content'] if prior['messages'] else '')
            return latest
        return service.job('recommendation-discuss', work, metadata={'question': question.strip(), 'revision': revision})


def verify_candidates(candidates, progress):
    """Verify each discussed title, in preferred index order; never invent result cards."""
    adapters = [('hf_papers', title_search.huggingface), ('papers_cool', title_search.papers_cool), ('arxiv', title_search.arxiv)]
    statuses = {s: {'source': s, 'ok': True, 'count': 0, 'requests': 0, 'message': '本轮无需查询'} for s, _ in adapters}
    items, checked = [], []
    for index, candidate in enumerate(candidates):
        progress(f'核实推荐 {index + 1}/{len(candidates)}：{candidate["title"][:90]}')
        matches = []
        for source, adapter in adapters:
            status = statuses[source]; status['requests'] += 1
            try:
                rows = adapter(candidate['title'])
                matches = [p for p in rows if title_search.same_title(p['title'], candidate['title'])]
                status['count'] += len(matches)
            except Exception:
                status['ok'] = False
                matches = []
            status['message'] = f'{status["requests"]} 次检索' + ('，已读取' if status['ok'] else '，部分请求未完成')
            if matches:
                items.extend({**p, 'reason':candidate['reason']} for p in matches)
                break
        checked.append({**candidate, 'verified': bool(matches)})
    return title_search.merge_verified(items), checked, list(statuses.values())


def recommend(revision):
    with LOCK:
        ensure_idle()
        prior = current()
        if type(revision) is not int or revision != prior['revision']:
            raise ValueError('对话已更新，请刷新后整理推荐')
        if not prior['candidates']:
            raise ValueError('先与助手讨论，让它给出具体论文后再整理推荐')
        def work(progress):
            items, checked, statuses = verify_candidates(prior['candidates'], progress)
            result = {'id': uuid.uuid4().hex, 'created_at': service.now(), 'revision': revision,
                'items': items, 'candidates': checked, 'source_status': statuses,
                'complete': all(c['verified'] for c in checked)}
            with LOCK:
                latest = current()
                if latest['revision'] != revision:
                    raise ValueError('对话已更新，请重新整理推荐')
                store.save('model_recommendation', result)
                latest['result'] = result
                store.save('recommendation_chat', latest)
            return latest
        return service.job('recommendation-resolve', work)
