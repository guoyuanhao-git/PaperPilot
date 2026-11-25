const test=require('node:test');
const assert=require('node:assert/strict');
const view=require('../web/report-view.js');
test('legacy author visiting note is omitted without altering body',()=>{
 const source='正文第一段。\n\n\\* 部分工作在访问麻省理工学院期间完成。\n\n第二段。';
 assert.equal(view.translationText(source),'正文第一段。\n\n第二段。');
 assert.equal(view.translationText('* 本研究在示例大学访问期间完成。'),'');
});
test('technical footnotes and mixed paragraphs remain intact',()=>{
 for(const source of ['* 此处假设速度场连续。','部分工作在访问某机构期间完成。','* 部分工作在访问某机构期间完成。该方法采用二阶更新。','正文\n* 部分工作在访问某机构期间完成。'])assert.equal(view.translationText(source),source);
});
