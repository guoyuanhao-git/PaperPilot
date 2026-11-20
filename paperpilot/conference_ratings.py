"""Reviewed directory editions; independent of CFP imports and model updates.

Only the supported conference series are mapped. N means absent from this
directory edition; an unknown series must not be treated as absent. Page
numbers are one-based PDF pages. Never infer new grades from a deadline page.
"""
from copy import deepcopy

DIRECTORIES = {
    'ccf': {
        'label': 'CCF', 'name': '中国计算机学会推荐国际学术会议和期刊目录',
        'version': '2026 · 第七版', 'checked': '2026-10-30',
        'source': 'https://www.ccf.org.cn/Academic_Evaluation/By_category/',
        'document': 'https://dengpingfan.github.io/papers/CCF-Recommend-2026.pdf',
        'documentLabel': '目录 PDF（公开副本）',
    },
    'th': {
        'label': 'TH', 'name': '清华大学计算机学科群推荐学术会议和期刊列表（TH-CPL）',
        'version': '2019-08-13', 'checked': '2026-10-30',
        'source': 'https://numbda.cs.tsinghua.edu.cn/~yuwj/TH-CPL.pdf',
        'document': 'https://numbda.cs.tsinghua.edu.cn/~yuwj/TH-CPL.pdf',
        'documentLabel': '清华目录 PDF',
    },
}

# (CCF grade, CCF page, TH-CPL grade, TH-CPL page).
ENTRIES = {
    'cvpr': ('A', 57, 'A', 11),
    'iccv': ('A', 57, 'A', 11),
    'icml': ('A', 57, 'A', 11),
    'neurips': ('A', 57, 'A', 11),
    'aaai': ('A', 57, 'A', 11),
    'iclr': ('A', 57, 'A', 11),
    'eccv': ('B', 58, 'A', 11),
    'icra': ('B', 58, 'A', 11),
    'rss': ('N', None, 'A', 11),
    'ijcai': ('B', 58, 'B', 12),
    'iros': ('C', 59, 'B', 12),
    'mm': ('A', 47, 'A', 14),
    'corl': ('N', None, 'N', None),
}


def current():
    """Public metadata only. Return fresh objects, never mutate saved catalogs."""
    return {'directories': deepcopy(DIRECTORIES), 'entries': {
        ident: {'ccf': {'grade': row[0], 'page': row[1]},
                'th': {'grade': row[2], 'page': row[3]}}
        for ident, row in ENTRIES.items()
    }}
