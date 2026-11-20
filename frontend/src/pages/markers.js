import {markers,ledger} from '../api/business.js';
import {store} from '../stores/business.js';
import {esc,json} from '../utils/html.js';
import {table} from '../components/common/table.js';
import {status} from '../components/common/status.js';
import {feedback} from '../components/common/feedback.js';
import {LEDGER_STATES,LEDGER_ENTITIES,STATUSES} from '../constants/enums.js';
import {submit} from '../hooks/forms.js';

// 页面本地状态：当前标记、实体类型、分页 cursor 栈（中断后可逐页回到原位置）
const view={markers:[],overview:null,ledger:null,selected:null,type:'dataset',cursors:[null],pages:{},detail:null};
let renderer=null;
export function setRenderer(fn){renderer=fn;}

async function loadMarkers(){
 view.markers=await markers.list();
 if(view.selected)view.selected=view.markers.find(m=>m.id===view.selected)||null;
 if(!view.selected&&view.markers[0])view.selected=view.markers[0].id;
 if(store.user.role==='admin'){try{view.ledger=await ledger.overview();}catch{view.ledger=null;}}
 render();
}
async function openScene(id){
 view.selected=Number(id);view.type='dataset';view.cursors=[null];view.pages={};view.detail=null;
 await loadPage(true);
}
async function loadOverview(){
 view.overview=await markers.scene(view.selected);render();
}
async function loadPage(reset=false){
 if(view.selected==null)return;
 const cursor=view.cursors[view.cursors.length-1];
 const data=await markers.page(view.selected,view.type,cursor);
 view.pages[view.type]=data;
 if(reset)await loadOverview();else render();
}
function rowsOf(){
 const data=view.pages[view.type];
 if(!data)return [];
 return data.items.map(it=>{
  const e=it.entity;
  const main=view.type==='dataset'?`${esc(e.name)}<small>${esc(e.description||'')}</small>`
   :view.type==='plan'?`${esc(e.name)}<small>计划 #${e.dataset_id} · ${e.steps?.length||0} 个算子</small>`
   :`${esc(e.name)}<small>${esc(e.created_at||'')}</small>`;
  const mid=view.type==='trace'?status(e.status):(view.type==='dataset'?`readings ${e.readings?.length??0}<small>sensors ${e.sensors?.length??0}</small>`:`<div class="pipeline-mini">${(e.steps||[]).map(s=>`<span>${esc(s.op)}</span>`).join('→')}</div>`);
  return [main,mid,`<small>seq #${it.commit_seq} · ${it.change_type==='I'?'新增':'更新'}</small>`,`<button class="quiet" data-scene-entity="${it.entity_id}">翻看当时版本 →</button>`];
 });
}
export function markersPage(){
 const ready=view.ledger?.state==='ready';
 const banner=store.user.role==='admin'&&view.ledger?`
 <div class="ledger-banner ${view.ledger.state}">
  <div><span class="eyebrow">LEDGER / 时态账本</span><h2>${LEDGER_STATES[view.ledger.state]||view.ledger.state}</h2>
  <p>版本行 <em>${view.ledger.version_rows}</em> · 标记 <em>${view.ledger.markers}</em> ·
  采样 ${view.ledger.versioned_entities.dataset}/${view.ledger.total_entities.dataset} ·
  计划 ${view.ledger.versioned_entities.plan}/${view.ledger.total_entities.plan} ·
  剖面 ${view.ledger.versioned_entities.trace}/${view.ledger.total_entities.trace}</p></div>
  ${view.ledger.state==='building'?'<aside class="note">旧数据正在小事务回填，不同数据集的保存照常并发；回填完成后才能创建标记。</aside>':'<aside class="note">标记只冻结一个提交序号，不复制全库；晚于标记的写入不会出现在现场。</aside>'}
 </div>`:'';
 const createForm=store.user.role==='admin'?`
 <section><h2>标记这一节课的现场</h2>
 <form id="marker-form">
  <label>标记名称<input name="name" required placeholder="shift-20261117-上午班" ${ready?'':'disabled'}></label>
  <label>备注<input name="note" placeholder="采样复核与剖面讲评" ${ready?'':'disabled'}></label>
  <button type="submit" ${ready?'':'disabled'}>${ready?'创建课堂标记 →':'账本建账中…'}</button>
 </form></section>`:'<section><h2>课堂标记现场</h2><p>只读查看管理员创建的标记及其冻结的采样、计划与剖面状态。</p></section>';
 const markerList=table(['标记 / 时间','冻结序号','动作'],view.markers.map(m=>[
  `<b>${esc(m.name)}</b><small>${esc(m.created_at)} · ${esc(m.created_by)}</small>`,
  `<code class="checksum">seq ≤ ${m.horizon_seq}</code>`,
  `<button class="quiet" data-open-marker="${m.id}" ${m.id===view.selected?'disabled':''}>${m.id===view.selected?'查看中':'翻看现场 →'}</button>`
 ]));
 const scene=view.selected!=null?scenePanel():'';
 return `<div class="markers-view">${banner}<div class="split">${createForm}<section><h2>标记册 <em>${view.markers.length}</em></h2>${markerList}</section></div>${scene}</div>`;
}
function scenePanel(){
 const m=view.markers.find(x=>x.id===view.selected);
 if(!m)return '';
 const data=view.pages[view.type];
 const tabs=Object.entries(LEDGER_ENTITIES).map(([k,label])=>`<button class="quiet tab ${k===view.type?'active':''}" data-scene-tab="${k}">${label} <em>${view.overview?.counts[k]??'…'}</em></button>`).join('');
 const statusDist=view.type==='trace'&&view.overview?Object.entries(view.overview.trace_statuses).map(([k,v])=>`<span class="status ${k}">${STATUSES[k]||k} × ${v}</span>`).join(' '):'';
 const detail=view.detail?`
 <div class="scene-detail" id="scene-detail"><div class="result-head"><h3>实体 #${view.detail.entity_id} 在该标记时点的版本 <small>seq ${view.detail.commit_seq}</small></h3><button class="quiet" data-close-detail>关闭 ×</button></div><pre>${json(view.detail.entity)}</pre></div>`:'';
 return `<section class="scene-panel"><div class="result-head"><div><span class="eyebrow">MARKER #${m.id} / HORIZON seq ≤ ${m.horizon_seq}</span><h2>${esc(m.name)} 的现场</h2><p>${esc(m.note||'无备注')} · 创建于 ${esc(m.created_at)}</p></div></div>
 <div class="tabs">${tabs}</div><p>${statusDist}</p>
 ${data?table([LEDGER_ENTITIES[view.type],'当时状态','版本','动作'],rowsOf()):'<div class="empty">正在读取现场…</div>'}
 <div class="pager">
  <button class="quiet" data-page-prev ${view.cursors.length<=1?'disabled':''}>← 上一页（回到原位置）</button>
  <small>cursor: ${esc(String(view.cursors[view.cursors.length-1]))}</small>
  <button class="quiet" data-page-next ${!data?.next_cursor?'disabled':''}>下一页 →</button>
 </div>${detail}</section>`;
}
export function bindMarkers(){
 document.getElementById('marker-form')?.addEventListener('submit',async e=>{
  e.preventDefault();
  try{
   let created=null;
   await submit(e.target,async d=>{created=await markers.create(d);});
   feedback('标记已创建，horizon_seq='+created.horizon_seq);
   await openScene(created.id);
  }catch(err){feedback(err.message,true);}
 });
 document.querySelectorAll('[data-open-marker]').forEach(b=>b.onclick=()=>openScene(Number(b.dataset.openMarker)));
 document.querySelectorAll('[data-scene-tab]').forEach(b=>b.onclick=()=>{view.type=b.dataset.sceneTab;view.cursors=[null];view.detail=null;loadPage(true);});
 document.querySelectorAll('[data-page-next]').forEach(b=>b.onclick=()=>{const d=view.pages[view.type];if(d?.next_cursor){view.cursors.push(d.next_cursor);view.detail=null;loadPage();}});
 document.querySelectorAll('[data-page-prev]').forEach(b=>b.onclick=()=>{if(view.cursors.length>1){view.cursors.pop();view.detail=null;loadPage();}});
 document.querySelectorAll('[data-close-detail]').forEach(b=>b.onclick=()=>{view.detail=null;render();});
 document.querySelectorAll('[data-scene-entity]').forEach(b=>b.onclick=async()=>{
  view.detail=await markers.entity(view.selected,view.type,Number(b.dataset.sceneEntity));render();
  document.getElementById('scene-detail')?.scrollIntoView({behavior:'smooth',block:'center'});
 });
}
function render(){renderer?.();}
export async function initMarkers(){
 try{await loadMarkers();}catch(e){feedback(e.message,true);}
}
