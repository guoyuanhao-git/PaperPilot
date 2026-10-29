/* One-time onboarding; the harness is a setup helper, not a new provider. */
(function(root){
 const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function card(p,state){
  const codex=p==='codex',configured=codex?state.capabilities.codex_available:state.capabilities.keys.deepseek;
  return `<div class="model-connection"><div class="model-connection-heading"><div><h3>${codex?'Codex':'DeepSeek'}</h3><span class="small muted">${codex?'ChatGPT 订阅':'DeepSeek API'}</span></div><span class="connection-badge ${configured?'configured':''}">${codex?(configured?'已检测到 CLI':'待安装 CLI'):(configured?'密钥已配置':'待接入')}</span></div><div class="model-connection-actions"><button id="model-setup-open" class="secondary" type="button">${codex?'让 Codex 协助接入':'让 dsh 协助接入'}</button><button id="model-setup-check" class="textbtn" type="button">检查接入</button></div><p id="model-setup-status" class="small muted" role="status" hidden></p></div>`;
 }
 function manual(p,state){
  const configured=state.capabilities.keys.deepseek,info=state.capabilities.key_storage?.deepseek||{};
  return `<details class="model-manual"><summary>手动配置</summary><div>${p==='codex'?`<p class="hint">在 PaperPilot 项目文件夹的终端中执行，随后完成 ChatGPT 登录。</p><code class="setup-command">${esc(state.codex_setup?.command||'codex login')}</code><button id="copy-codex-command" class="textbtn small" type="button">复制命令</button>`:`<label for="api-key">API Key</label><div class="api-key-row"><input id="api-key" type="${configured?'text':'password'}" autocomplete="off" spellcheck="false" ${configured?'readonly':''} value="${configured?esc(info.masked||'已配置'):''}" placeholder="输入 API Key"><button id="reset-api-key" class="secondary" ${!configured?'disabled':''}>重置</button><button id="confirm-api-key" class="primary" ${configured?'disabled':''}>确认</button></div><p class="hint">${info.backend==='keychain'?'保存至当前用户的 macOS 钥匙串。':'保存至当前用户的本地凭据文件（明文）。'}</p>${info.error?`<p class="error small">${esc(info.error)}</p>`:''}`}</div></details>`;
 }
 function models(p,c){
  return `<section class="advanced-section model-parameters"><h3>模型参数</h3>${p==='codex'?`<label>模型 ID<input id="model" value="${esc(c.model)}" placeholder="留空使用 gpt-6.1-sol"></label>`:`<label>API 地址<input id="base-url" value="${esc(c.deepseek.base_url)}" type="url"></label><label>速览与日常问答<input id="api-model" value="${esc(c.deepseek.model)}"></label><label>论文精读<select id="detail-model">${[['deepseek-flash','Flash · 推荐'],['deepseek-v4-pro','Pro · 图表由 Flash 辅助']].map(([v,label])=>`<option value="${v}" ${(c.deepseek.detail_model||'deepseek-flash')===v?'selected':''}>${label}</option>`).join('')}</select></label>`}</section>`;
 }
 function instruction(p,setup){
  const command=setup.commands[p];
  return `请帮我完成当前 PaperPilot 用户的 ${p==='codex'?'Codex 订阅':'DeepSeek API'} 接入。保持 PaperPilot 应用已启动。\n\n【当前接入目标 · 自动填入】\n项目目录：${setup.project_directory}\n本机应用：${setup.local_url}\nPaperPilot 用户 ID：${setup.account_id}\n命令环境：${setup.shell_label}\n\n先进入项目目录，再执行后续命令：\n${setup.enter_project_command}\n\n请确认该目录包含 paperpilot/model_setup.py。若目录不存在，请让我确认项目的新位置；不要猜测其他目录或修改用户 ID。\n\n检查当前接入：\n${command} --check\n\n随后完成接入（已配置时沿用已有凭据）：\n${command}${p==='deepseek'?' --key-from-env':''}\n\n${p==='codex'?'使用 Codex 官方登录流程，让我在浏览器完成授权；不要复制其他用户的登录凭据。':'仅在当前终端已经有我授权使用的 DEEPSEEK_API_KEY 时使用环境变量接入；如果没有，请引导我到 PaperPilot 的“手动配置”中输入，或由我在交互终端运行不带 --key-from-env 的命令。dsh 账号登录凭据不是 API Key，不要尝试提取或转换。'}\n\n已有配置时不要覆盖。不要读取其他账户的凭据，不要将密钥或登录令牌输出到对话、命令参数或日志。不要修改代码、模型档位、研究档案和其他设置。完成后再次 --check；未执行模型调用时只说明本地配置已完成，不要声称模型连接测试成功。`;
 }
 root.ModelSetupView={card,manual,models,instruction};
 if(typeof module!=='undefined')module.exports=root.ModelSetupView;
})(globalThis);
