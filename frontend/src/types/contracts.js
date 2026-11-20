/** @typedef {{id:number,name:string,sensors:object[],readings:object[]}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,steps:object[]}} Plan */
/** @typedef {{id:number,name:string,status:'queued'|'running'|'completed'|'failed',result:object|null}} Trace */
/** @typedef {{id:number,name:string,note:string,horizon_seq:number,created_by:string,created_at:string}} Marker */
/** @typedef {{state:'building'|'ready',state_label:string,versioned_entities:Object<string,number>,total_entities:Object<string,number>,version_rows:number,markers:number}} LedgerOverview */
/** @typedef {{entity_id:number,commit_seq:number,change_type:'I'|'U',entity:object}} SceneItem */
/** @typedef {{marker_id:number,entity_type:string,limit:number,next_cursor:number|null,items:SceneItem[]}} ScenePage */
export {};
