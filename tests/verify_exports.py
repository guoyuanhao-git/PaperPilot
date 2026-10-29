"""Manual export integration check. Uses isolated synthetic fixtures, no model call."""
import json
import sys
import tempfile
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from test_core import pdf
from paperpilot import documents, exports, store, service
from unittest.mock import patch

fixture = tempfile.TemporaryDirectory(prefix='paperpilot-export-')
store.DATA = Path(fixture.name)
store.init()
p = documents.ingest(pdf(), 'Software-export-fixture.pdf')
p.update(publication_month='2021-09', publication_date_source='手动填写')
p['report'] = {
    'title': '中文论文速览：软件导出测试', 'summary': '这是用于验证中文、公式与原文图表排版的软件测试夹具，不是一篇真实论文。',
    'mode': 'overview', 'scope': '测试材料，共 2 页', 'vision': False, 'provider': 'fixture', 'model': 'no-model-call',
    'figures': p['figures'],
    'paper_info':{'original_title':'Original Paper Title','authors':[{'name':'Test Author','affiliations':['Test University'],'corresponding':True,'scholar':{'source':'Google Scholar','count':123,'verified':True}}], 'first_author':{'name':'Test Author','count':123,'source':'Semantic Scholar','checked_at':'2026-10-12','url':'https://www.semanticscholar.org/author/123'},'project_url':'https://example.org','code_url':'https://github.com/example/example'},
    'sections': [
        {'key':'abstract','title':'论文摘要 · 中文翻译','paragraphs':['这是原论文摘要的完整中文翻译测试，保留在网页、PDF 中。它与一句话核心思想分开显示。'], 'pages':[1], 'figures':[], 'equations':[]},
        {'key':'motivation','title':'动机','paragraphs':['用户希望迅速理解论文的研究问题和方法来由。这个软件测试验证中文内容可以清楚呈现，而不是验证任何论文结论。'], 'pages':[1],'figures':[], 'equations':[]},
        {'key':'method','figure_first':True,'title':'方法与实现','paragraphs':['数学表达需要保持可读。下面的示例公式仅用于测试排版，训练时的采样方式和代码细节应当由真实原文确认。'], 'pages':[1],'figures':[p['figures'][0]['id']], 'equations':[{'latex':r'\mathcal{L}(\theta)=\mathbb{E}_{x,y}\left[\|f_\theta(x)-y\|^2\right]', 'meaning':'测试网络输出与目标之间的平方误差，所有符号均为软件测试样例。','implementation':'计算预测、目标和批次平均，示例并不代表某篇论文的真实代码。'}]},
        {'key':'experiments','title':'实验结果与适用条件','paragraphs':['测试检查 PDF 文字可提取、公式可显示、图表可以保留。这里没有真实科研实验结果。'], 'pages':[2],'figures':[],'equations':[]},
        {'key':'conclusion','title':'结论','paragraphs':['结论验证：四段研究故事线已闭合，测试仅说明导出结构，不代表真实论文结论。'], 'pages':[2],'figures':[],'equations':[]},
    ],
}
store.save('paper',p)
p['figures'][0]['caption_zh'] = '图 1：用于验证裁剪的矩形示意图'
for section in p['report']['sections']:
 section['highlights'] = [section['paragraphs'][0].split('。')[0]]
p['report']['sections'][2]['blocks']=[{k:v for k,v in p['report']['sections'][2].items() if k not in ('key','title','figure_first')}]
p['report']['sections'][2].update(paragraphs=[],highlights=[],equations=[])
store.save('paper',p)
info = exports.export(p['id'],'pdf',print)
output = documents.directory(p['id']) / 'exports' / info['filename']
from pypdf import PdfReader
assert '2109' in PdfReader(output).pages[0].extract_text()
assert '完整中文翻译测试' in unicodedata.normalize('NFKC', ''.join(page.extract_text() for page in PdfReader(output).pages))
text=unicodedata.normalize('NFKC', ''.join(page.extract_text() for page in PdfReader(output).pages))
for removed in ('论文摘要 · 中文翻译','原文定位','段落导读','PDF 第','思想与符号','实现连接'):
 assert removed not in text
assert 'Figure 1:' in text
assert '论文相关' in text
assert '结论验证' in text
assert 'OriginalPaperTitle' in ''.join(text.split())
assert 'Test Author' in text
if '--preview' in sys.argv:
 import pypdfium2 as pdfium
 preview = Path(tempfile.mkdtemp(prefix='paperpilot-pdf-preview-'))
 doc = pdfium.PdfDocument(output)
 for index in range(len(doc)):
  doc[index].render(scale=1).to_pil().save(preview/f'page-{index+1}.png')
 print('PREVIEW_DIR='+str(preview),flush=True)
print('PDF_EXPORT_CHECK_PASSED',flush=True)
