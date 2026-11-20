import {ledger} from '../api/business.js';import {api} from '../api/client.js';
import {esc} from '../utils/html.js';
import {feedback} from '../components/common/feedback.js';
import {LEDGER_STATES} from '../constants/enums.js';

let cache={overview:null,audits:null};
export async function loadAudit(){
 try{
  const [overview,audits]=await Promise.all([ledger.overview(),api('/audit')]);
  cache={overview,audits};
 }catch(e){feedback(e.message,true);}
}
export function auditPage(){
 const o=cache.overview;
 const banner=o?`<div class="ledger-banner ${o.state}">
  <div><span class="eyebrow">LEDGER / 时态账本</span><h2>${LEDGER_STATES[o.state]||o.state}</h2>
  <p>版本行 <em>${o.version_rows}</em> · 课堂标记 <em>${o.markers}</em></p>
  <p>版本化进度：采样 ${o.versioned_entities.dataset}/${o.total_entities.dataset} ·
  计划 ${o.versioned_entities.plan}/${o.total_entities.plan} ·
  剖面 ${o.versioned_entities.trace}/${o.total_entities.trace}</p></div>
  <aside class="note">${o.state==='building'?'建账中：旧数据按小事务回填，在线保存不受阻；可查前禁止创建标记。':'可查：所有历史写入均已版本化，课堂标记可正常创建与翻看。'}</aside>
 </div>`:'<div class="empty">正在读取账本状态…</div>';
 return `${banner}<section><h2>业务审计 <em>${cache.audits?.length??0}</em></h2>
 ${cache.audits?`<div class=table-wrap><table><thead><tr><th>时间</th><th>操作人</th><th>动作</th><th>对象</th></tr></thead><tbody>
 ${cache.audits.map(a=>`<tr><td><small>${esc(a.created_at)}</small></td><td>${esc(a.actor)}</td><td><code>${esc(a.action)}</code></td><td><small>${esc(a.detail)}</small></td></tr>`).join('')}
 </tbody></table></div>`:'<pre id="audit-data">正在读取…</pre>'}</section>`;
}
