"""Shared reader/export rendering and safe discussion markup contracts."""
import shutil
import subprocess
import unittest
from paperpilot import store


@unittest.skipUnless(shutil.which('node'), 'Node required for shared browser rendering')
class ReaderUi(unittest.TestCase):
    def test_report_inline_math_and_legacy_equation_notes(self):
        subprocess.run(['node', '-e', r'''
const assert=require('node:assert/strict'),r=require('./web/report-view.js'),katex=require('katex');
const math=(s,d)=>katex.renderToString(s,{displayMode:d,throwOnError:true,trust:false});
const e={latex:String.raw`P_{ee}=P_o-d\vec{a}_o`,meaning:'接触点P_o、接近轴a_o和偏移距离$d$。',implementation:'使用 $P_{ee}$ 计算。'};
// Only symbols unambiguously present in the corresponding equation are restored.
const html=r.equationNoteHTML(e,'deep',math);
assert.equal((html.match(/class="katex"/g)||[]).length,4);
assert(!html.includes('katex-error'));assert(!html.includes('接触点P_o'));
assert.equal(r.inline('file_name source.pdf 50% 12.5'), 'file_name source.pdf 50% 12.5');
const explicit=r.inline(String.raw`接触点 $P_o$ 与 \(a_o\) <img src=x onerror=alert(1)>`,math);
assert.equal((explicit.match(/class="katex"/g)||[]).length,2);assert(!explicit.includes('<img'));
const calls=[];const render=(s,d)=>{calls.push([s,d]);return '<math>safe</math>'};
assert.equal(r.inline('`P_o` https://example.org/P_o file_P_o P_other P_o',render,[],r.equationSymbols('P_o')), '<code>P_o</code> https://example.org/P_o file_P_o P_other <math>safe</math>');
assert.deepEqual(calls,[['P_o',false]]);
const section={key:'method',paragraphs:[String.raw`重点：$P_o$ 与 \(a_o\)。`],highlights:['重点'],figures:[],equations:[]};
assert.match(r.sectionContent(section,()=>'',()=>'',math),/<mark>重点<\/mark>/);
assert.match(r.sectionContent(section,()=>'',()=>'',math),/class="katex"/);
const abstract={...section,key:'abstract'};assert.match(r.sectionBody(abstract,false,math),/class="katex"/);
assert.equal(r.inline('$P_o$',()=>{throw Error('invalid')}),'P_o');
assert.match(r.inline('$\\href{javascript:alert(1)}{x}$',math),/katex/);
assert(!r.inline('$\\href{javascript:alert(1)}{x}$',math).includes('href="javascript:'));
'''], cwd=store.ROOT, check=True, capture_output=True)

    def test_recommendation_numbering_across_paragraphs_and_blank_lines(self):
        subprocess.run(['node', '-e', r'''
const assert=require('node:assert/strict'),chat=require('./web/chat-view.js');
const html=chat.render('1. **Paper A**\n\n推荐理由 A。\n\n2. **Paper B**\n\n推荐理由 B。\n\n3. **Paper C**');
assert.match(html,/<ol><li><strong>Paper A/);
assert.match(html,/<ol start="2"><li><strong>Paper B/);
assert.match(html,/<ol start="3"><li><strong>Paper C/);
for(const source of ['1. A\n\n2. B\n\n3. C','1. A\n\n1. B\n\n1. C','1. A\n2. B\n3. C']){
 assert.equal(chat.render(source),'<ol><li>A</li><li>B</li><li>C</li></ol>');
}
assert.equal(chat.render('4. D\n5. E'),'<ol start="4"><li>D</li><li>E</li></ol>');
assert.equal(chat.render('1. A\n\n## Another list\n\n1. B'),'<ol><li>A</li></ol><h3>Another list</h3><ol><li>B</li></ol>');
assert.equal(chat.render('- A\n\n- B'),'<ul><li>A</li><li>B</li></ul>');
assert.equal(chat.render('1. A\n\n- detail\n\n2. B'),'<ol><li>A</li></ol><ul><li>detail</li></ul><ol start="2"><li>B</li></ol>');
'''], cwd=store.ROOT, check=True, capture_output=True)

    def test_equation_modes_and_untrusted_chat_markup(self):
        subprocess.run(['node', '-e', r'''
const assert=require('node:assert/strict');
const reader=require('./web/report-view.js'),chat=require('./web/chat-view.js');
assert.equal(reader.label({caption:'Figure 1 VLA-Rolling reuses action tails.'}),'Figure 1');
assert.equal(reader.label({caption:'Table 6 Results on real-world tasks.'}),'Table 6');
assert.equal(reader.label({caption:'Table 12: Comparison.'}),'Table 12');
assert.equal(chat.authorIcon('assistant','男'),'saixiaoxi');
assert.equal(chat.authorIcon('user','男'),'liuxing');
assert.equal(chat.authorIcon('user','女'),'lanxue');
assert.equal(chat.authorIcon('user','秘密'),'naiwa');
for(const v of ['',undefined])assert.equal(chat.authorIcon('user',v),'nailong');
const e={latex:'x=y',meaning:'约束预测接近目标。',implementation:'逐项计算后取平均。'};
assert.deepEqual(reader.equationNotes(e,'overview'),[e.meaning]);
assert.deepEqual(reader.equationNotes(e,'detailed'),[e.meaning]);
assert.deepEqual(reader.equationNotes(e,'deep'),[e.meaning,e.implementation]);
assert.deepEqual(reader.equationNotes({meaning:'',implementation:'旧格式说明'},'overview'),['旧格式说明']);
const html=chat.render('# 解释\n\n**重点**与 `代码`\n\n|A|B|\n|---|---|\n|1|2|\n\n<script>alert(1)</script>\n\n[危险](javascript:alert(1))\n[论文](https://arxiv.org/abs/1234.56789)\n\n```\n<img onerror=alert(1)>\n```');
assert.match(html,/<h3>解释<\/h3>/);assert.match(html,/<strong>重点<\/strong>/);
assert.match(html,/<table>/);assert.match(html,/<code>代码<\/code>/);
assert.ok(!html.includes('<script>'));assert.ok(!html.includes('<img'));
assert.ok(!html.includes('href="javascript:'));assert.match(html,/rel="noopener noreferrer"/);
let formulas=[];
chat.render('内联 $x+y$ 与 \\(z\\)\n\n$$\na=b\n$$',(s,d)=>{formulas.push([s.trim(),d]);return 'MATH'});
assert.deepEqual(formulas,[['x+y',false],['z',false],['a=b',true]]);
'''], cwd=store.ROOT, check=True, capture_output=True)

    def test_math_inside_bold_lists_headings_and_tables(self):
        subprocess.run(['node', '-e', r'''
const assert=require('node:assert/strict'),chat=require('./web/chat-view.js');
const formulas=[];
const source=String.raw`## **定义：\(B_{\mathrm{fixed}}\)**

- **+\(A+B_{\mathrm{fixed}}\)**：固定混入 50% 噪声。
- **+\(A+B\)**：按置信度再加噪。
- **最优 $x^*$**：星号也属于公式。

| 符号 | 含义 |
| --- | --- |
| **\(B_{\mathrm{fixed}}\)** | 固定比例 |

**代码：\`\(literal\)\`**

\`\(code\)\`

\[ a=b \]

**<img src=x onerror=alert(1)> 与 \(x\)**`;
// Code examples are separately checked below to avoid JS template delimiters.
const html=chat.render(source,(s,d)=>{formulas.push([s.trim(),d]);return '<span class="math">MATH</span>'});
assert.match(html,/<h3><strong>定义：<span class="math">/);
assert.match(html,/<li><strong>\+<span class="math">/);
assert.match(html,/<th>符号<\/th>/);
assert.match(html,/<td><strong><span class="math">/);
assert.ok(formulas.some(([s])=>s==='A+B_{\\mathrm{fixed}}'));
assert.ok(formulas.some(([s])=>s==='x^*'));
assert.ok(formulas.some(([s,d])=>s==='a=b'&&d));
assert.ok(!html.includes('<img'));
let called=0;
const code=chat.render('**`\\(literal\\)`**\n\n```latex\n\\(code\\)\n```',()=>{called++;return 'MATH'});
assert.equal(called,0);assert.match(code,/<strong><code>/);
const katex=require('katex');
const rendered=chat.render(String.raw`- **+\(A+B_{\mathrm{fixed}}\)**：说明`,(s,d)=>katex.renderToString(s,{throwOnError:true,displayMode:d,trust:false}));
assert.match(rendered,/<strong>\+<span class="katex">/);
assert.ok(!rendered.includes('katex-error'));assert.ok(!rendered.includes('\\('));
'''], cwd=store.ROOT, check=True, capture_output=True)
