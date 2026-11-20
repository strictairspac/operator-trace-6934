import {api,post} from './client.js';
export const datasets={list:()=>api('/datasets'),save:(d,id)=>post('/datasets'+(id?'/'+id:''),d,id?'PUT':'POST')};
export const plans={list:()=>api('/plans'),save:(d,id)=>post('/plans'+(id?'/'+id:''),d,id?'PUT':'POST')};
export const traces={list:()=>api('/traces'),run:d=>post('/traces',d),detail:id=>api('/traces/'+id)};
export const ledger={overview:()=>api('/ledger/overview')};
export const markers={
 list:()=>api('/markers'),
 create:d=>post('/markers',d),
 detail:id=>api('/markers/'+id),
 scene:id=>api('/markers/'+id+'/scene'),
 page:(id,type,cursor,limit=20)=>api(`/markers/${id}/scene/${type}?limit=${limit}`+(cursor!=null?`&cursor=${cursor}`:'')),
 entity:(id,type,eid)=>api(`/markers/${id}/scene/${type}/${eid}`)
};
