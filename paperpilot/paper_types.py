"""Manual paper-type selection and per-type outlines; legacy detection stays compatible."""
import copy

from . import reading_outline, store

TYPES = ('research', 'survey')
SURVEY_OUTLINE = ['领域问题', '分类框架', '技术路线', '对比与评测', '挑战与展望']

SURVEY_REPORT_GUIDE = (
    '摘要、论文相关、助手判断保持统一格式；助手判断评价综述的覆盖、比较边界，并结合用户方向建议优先阅读的分支和代表作。'
)

SURVEY_GUIDE = (
    '当前是综述论文，目标是建立领域地图，不是给综述虚构一个新模型和实验。'
    '说明覆盖范围和遗漏、作者分类的依据、各技术路线的关键思想与代表工作、路线间的差异、评测条件及未解问题。'
    '区分综述作者的分类和结论、被综述工作的结果、助手为教学新增的归纳。'
    '仅凭引用或提及不能声称采用或继承；不能将不同数据集、设置、指标的数字直接排名。'
    '没有统一评测时据实说明，不强求实验章节。代表作只选理解各路线必需的，不逐篇罗列全部参考文献。'
    '图表优先分类树、演进关系、路线比较和评测框架，重复案例可舍弃；核对全部所选范围的图表候选。'
    '数学精读只深入原文实际讨论的数学框架、假设和方法差异，不套用扩散模型推导。'
    + SURVEY_REPORT_GUIDE +
    '建议的代表作必须在提供的材料中可核实，原文之外的判断明确标为助手建议。'
)


def validate(value):
    if value not in TYPES:
        raise ValueError('论文类型应为研究论文或综述论文')
    return value


def effective(paper):
    selected = paper.get('paper_type')
    if selected not in (None, 'auto'):
        return validate(selected)
    detected = paper.get('paper_type_detection', {}).get('type')
    return detected if detected in TYPES else 'research'


def default_outline(kind):
    return list(SURVEY_OUTLINE if kind == 'survey' else reading_outline.DEFAULT)


def outline(paper, kind=None):
    kind = kind or effective(paper)
    saved = paper.get('reading_outlines', {})
    if kind in saved:
        return reading_outline.validate(saved[kind])
    # Legacy single-outline papers belong to the research template. Never leak
    # that template into a newly detected survey.
    if kind == 'research' and not saved and paper.get('reading_outline'):
        return reading_outline.validate(paper['reading_outline'])
    return default_outline(kind)


def update(paper, changes):
    """Apply manual preferences without touching existing generated artifacts."""
    saved = dict(paper.get('reading_outlines', {}))
    if not saved and paper.get('reading_outline'):
        saved['research'] = reading_outline.validate(paper['reading_outline'])
    for kind in TYPES:
        saved.setdefault(kind, default_outline(kind))
    if 'paper_type' in changes:
        paper['paper_type'] = validate(changes['paper_type'])
    if 'reading_outline' in changes:
        kind = changes.get('reading_outline_type', effective(paper))
        if kind not in TYPES:
            raise ValueError('叙述线类型无效')
        saved[kind] = reading_outline.validate(changes['reading_outline'])
    paper['paper_type'] = effective(paper)
    paper['reading_outlines'] = saved
    paper['reading_outline'] = outline(paper)


def preferences(paper):
    return {k: copy.deepcopy(paper.get(k)) for k in ('paper_type', 'reading_outlines', 'reading_outline')}


def prepare(paper, config, progress):
    """Resolve the saved manual choice without a model request or source scan."""
    paper = copy.deepcopy(paper)
    before = preferences(paper)
    kind = effective(paper)
    # Preserve legacy detected surveys and custom outlines without reclassification.
    update(paper, {})
    paper['resolved_paper_type'] = kind
    from .service import SAVE_LOCK
    with SAVE_LOCK:
        current = store.get('paper', paper['id'])
        if preferences(current) != before:
            raise ValueError('生成期间论文类型或叙述线已修改，请重新生成')
        for field in ('paper_type', 'reading_outlines', 'reading_outline'):
            if field in paper:
                current[field] = copy.deepcopy(paper[field])
        store.save('paper', current)
    return paper


def instruction(paper):
    if effective(paper) != 'survey':
        return ''
    return SURVEY_GUIDE
