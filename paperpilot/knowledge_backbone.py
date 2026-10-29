"""Select navigational relationships without deleting evidence or imposing degree caps."""
from . import store
from .schemas import obj

VERSION = 1


def edge_id(edge):
    return '|'.join(sorted((edge['source'], edge['target'])))


def refine(progress, nodes, edges, config, core=None, rebuild=False):
    from .knowledge import digest, config_signature, validated_batch, batches, TEXT
    by_id = {n['id']: n for n in nodes}
    core_ids = {n['id'] for n in core['nodes']} if core else set()
    # The mainline view inherits the long-term backbone without rejudging it.
    selected = set(core.get('backbone_pairs', [edge_id(e) for e in core['edges'] if e.get('priority', 1) >= 2])) if core else set()
    adjacency = {n['id']: [] for n in nodes}
    for edge in edges:
        if core and {edge['source'], edge['target']} <= core_ids:
            continue
        for ident in (edge['source'], edge['target']):
            adjacency[ident].append(edge)
    roles = dict(core.get('node_roles', {})) if core else {}
    schema = obj({'choices': {'type': 'array', 'items': obj({
        'id': TEXT, 'keep': {'type': 'array', 'items': TEXT},
        'role': {'type': 'string', 'enum': ['foundation', 'bridge', 'specialist']},
        'reason': {'type': 'string', 'maxLength': 500}})}})
    prompt = ('为人阅读的知识地图做局部关系取舍，输出每个 id。只能从 links 的 id 中选择 keep，不能新增关系。'
              '保留直接且独特的方法关系、关键差异、互补及有依据的跨主题桥梁；共同主题、共同术语或重复解释不必各画一条边。'
              '比较每条联系增加的理解：同一知识点反复出现时保留最有代表性的表达。证据不足的迁移设想放在补充联系，不作为主干。'
              '没有固定名额；有多少条独立而重要的联系就保留多少条，允许枢纽保留全部，也允许 keep 为空。'
              '不能因为存在 A-B-C 路径就删除 A-C；只有具体语义确实冗余才取舍。不把收藏视为学术等级。'
              'role 表示当前材料中的基础支点 foundation、跨主题桥梁 bridge 或具体进展 specialist，不是引用量排名；reason 简述取舍理由。'
              '领域骨架按长期研究方向；主线外围按当前主线。只取舍给定联系，事实仍以已有证据为准。')
    pending, contexts = [], {}
    for index, node in enumerate(nodes):
        incident = sorted(adjacency[node['id']], key=lambda e: (-e.get('priority', 1), edge_id(e)))
        if len(incident) < 4:
            selected.update(edge_id(e) for e in incident if e.get('priority', 1) >= 2)
            continue
        links = []
        for edge in incident:
            other = edge['target'] if edge['source'] == node['id'] else edge['source']
            links.append({'id': edge_id(edge), 'paper': by_id[other]['title'], 'relation': edge['relation'],
                          'reason': edge['reason'][:400], 'use': edge['research_use'][:300],
                          'evidence': [edge.get('quote_a', '')[:250], edge.get('quote_b', '')[:250]],
                          'priority': edge.get('priority', 1)})
        # Bound input size, not node degree: high-degree hubs can keep links in every chunk.
        chunks, chunk, cost = [], [], 0
        budget = max(2000, config.get('context_chars', 100000)//3)
        for link in links:
            size = len(str(link))
            if chunk and (len(chunk) >= 24 or cost + size > budget):
                chunks.append(chunk); chunk, cost = [], 0
            chunk.append(link); cost += size
        if chunk: chunks.append(chunk)
        for part in chunks:
            ident = config['_knowledge_mainline'] + ':' + node['id'] + ':' + digest([l['id'] for l in part])[:16]
            signature = digest([VERSION, config_signature(config), node['insight'], part])
            try: cached = store.get('knowledge_backbone', ident)
            except ValueError: cached = {}
            if not rebuild and cached.get('signature') == signature:
                selected.update(cached['keep']); roles[node['id']] = cached['role']; continue
            payload = {'id': ident, 'paper': node['title'], 'insight': node['insight'][:1000], 'links': part}
            pending.append(payload)
            contexts[ident] = {'allowed': {link['id'] for link in part}, 'node_id': node['id'], 'signature': signature,
                               'paper_ids': sorted({node['id']} | {e['source'] for e in incident} | {e['target'] for e in incident})}
    for batch in batches(pending, lambda item: item, config, size=3):
        progress(f'提炼地图主干：比较 {len(batch)} 组局部联系（未变化结果复用）')
        def validate(value):
            context = contexts[value['id']]
            keep = value.get('keep')
            if not isinstance(keep, list) or any(not isinstance(k, str) or k not in context['allowed'] for k in keep) or len(set(keep)) != len(keep):
                raise ValueError('keep 必须是本批已有联系 id，不可重复或新增')
            role, reason = value.get('role'), value.get('reason')
            if role not in ('foundation', 'bridge', 'specialist') or not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
                raise ValueError('请给出有效 role 和不超过 500 字的取舍理由')
            return {'keep': keep, 'role': role, 'reason': reason}
        for ident, value in validated_batch(config, prompt, batch, schema, 'choices', validate, progress):
            context = contexts[ident]
            store.save('knowledge_backbone', {'id': ident, 'paper_ids': context['paper_ids'], 'signature': context['signature'], **value})
            selected.update(value['keep']); roles[context['node_id']] = value['role']
    valid = {edge_id(e) for e in edges}
    return {'backbone_version': VERSION, 'backbone_pairs': sorted(selected & valid), 'node_roles': roles}
