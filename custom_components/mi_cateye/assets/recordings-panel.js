class CatEyeRecordingsPanel extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});this.items=[];this.generation=0;this.loaded=false;}
  set hass(value){this._hass=value;if(this.isConnected&&!this.loaded)this.load();}
  connectedCallback(){
    this.shadowRoot.innerHTML=`<style>
      :host{display:block;box-sizing:border-box;min-height:100%;padding:16px;color:var(--primary-text-color,#fff);background:var(--primary-background-color,#10151d);font:15px system-ui}
      main{max-width:820px;margin:auto}header{display:flex;justify-content:space-between;align-items:center;gap:12px}h2{font-size:20px;margin:8px 0}button,input,select,a{font:inherit}button,a{min-height:42px;padding:8px 14px;border:0;border-radius:12px;cursor:pointer;background:var(--primary-color,#03a9f4);color:#fff;text-decoration:none;box-sizing:border-box}button:disabled{opacity:.5;cursor:default}.back{color:inherit;background:transparent}
      .filters{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0;align-items:end}label{display:grid;gap:6px;font-size:13px}input,select{padding:10px;border-radius:10px;border:1px solid var(--divider-color,#777);color:inherit;background:var(--card-background-color,#202733);min-height:42px;box-sizing:border-box}.hint{color:var(--secondary-text-color,#aaa);font-size:13px;margin:8px 0}.list{display:grid;gap:8px;margin:12px 0}.item{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 16px;border-radius:14px;background:var(--card-background-color,#202733)}.meta{font-size:13px;color:var(--secondary-text-color,#aaa);margin-top:4px}.player{margin:16px 0;border-radius:16px;overflow:hidden;background:var(--card-background-color,#202733)}.video{position:relative;padding-top:56.25%;background:#10151d}video{position:absolute;inset:0;width:100%;height:100%;object-fit:contain}.toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;padding:12px}.toolbar span{flex:1}.status{min-height:24px;line-height:1.6}[hidden]{display:none!important}@media(max-width:500px){:host{padding:12px}.filters{gap:8px}input[type=time]{width:105px}.item{padding:12px}.toolbar{gap:6px}}
      </style><main><header><h2>门口录像回看</h2><button class="back" id="back">关闭</button></header>
      <div class="filters"><label>录像来源<select id="source"><option value="cloud">云端事件录像</option disabled>SD 卡回看暂不可用</option></select></label><label>日期<input id="day" type="date" aria-label="录像日期"></label><label>开始时间<input id="from" type="time" value="00:00" aria-label="开始时间"></label><label>结束时间<input id="to" type="time" value="23:59" aria-label="结束时间"></label><label>事件类型<select id="kind" aria-label="事件类型"><option value="all">全部事件</option></select></label><button id="query">查询录像</button></div>
      <p class="hint">云端事件录像，按时间选择片段；只有实际录制过的时段才有画面。云端录像以米家可用期限为准。</p>
      <section class="player" hidden><div class="video"><video controls playsinline preload="metadata" aria-label="门口录像播放器"></video></div><div class="toolbar"><span id="playing"></span><button id="previous">上一段</button><button id="next">下一段</button><a id="download" download="doorbell-recording.mp4">下载</a><button id="stop">关闭视频</button></div></section>
      <p class="status" id="status" role="status"></p><div class="list" id="list"></div></main>`;
    const now=new Date(),localDate=new Date(now.getTime()-now.getTimezoneOffset()*60000).toISOString().slice(0,10);
    this.$('#day').value=localDate;this.$('#day').max=localDate;
    this.$('#query').onclick=()=>this.load(true);this.$('#day').onchange=()=>this.load(true);
    this.$('#kind').onchange=()=>{this.stop();this.render();};this.$('#from').onchange=()=>{this.stop();this.render();};this.$('#to').onchange=()=>{this.stop();this.render();};
    this.$('#back').onclick=()=>{this.stop();history.replaceState(null,'','/');window.dispatchEvent(new CustomEvent('location-changed'));};
    this.$('#stop').onclick=()=>this.stop();this.$('#previous').onclick=()=>this.play(this.index+1);this.$('#next').onclick=()=>this.play(this.index-1);
    this.$('video').onerror=()=>{this.$('#status').textContent='当前设备无法播放这段录像，可以下载后查看，或选择其它片段。';};
    if(this._hass&&!this.loaded)this.load();
  }
  $(s){return this.shadowRoot.querySelector(s);}
  disconnectedCallback(){this.stop();this.loaded=false;}
  stop(){this.generation++;const v=this.$('video');if(v){v.pause();v.removeAttribute('src');v.load();}const p=this.$('.player');if(p)p.hidden=true;}
  bounds(){const day=this.$('#day').value;if(!/^\d{4}-\d{2}-\d{2}$/.test(day))throw Error('请选择日期');const start=new Date(day+'T00:00:00').getTime(),end=new Date(day+'T23:59:59.999').getTime();return{start,end};}
  async load(force=false){
    if(!this._hass||!this.$('#day')||this.loading)return;
    this.loaded=true;this.loading=true;this.stop();this.items=[];this.$('#list').replaceChildren();this.$('#day').disabled=true;this.$('#query').disabled=true;this.$('#status').textContent='正在读取录像…';
    try{const {start,end}=this.bounds();const result=await this._hass.callWS({type:'mi_cateye/recordings_list',start,end,source:'cloud'});if(!this.isConnected)return;this.items=result.items||[];this.renderKinds();this.render();}
    catch(e){this.items=[];this.$('#list').replaceChildren();this.$('#status').textContent=e?.message||'暂时无法读取录像，请稍后重试。';}
    finally{this.loading=false;if(this.$('#query'))this.$('#query').disabled=false;if(this.$('#day'))this.$('#day').disabled=false;}
  }
  eventLabel(event){return {Bell:'按门铃',Ring:'按门铃',Doorbell:'按门铃',Pass:'经过','Pass:Stay':'停留',Stay:'停留',Linger:'停留',Motion:'移动事件',Face:'人脸事件'}[event]||('其它：'+(event||'未标记'));}
  renderKinds(){const select=this.$('#kind'),previous=select.value;select.replaceChildren();const all=document.createElement('option');all.value='all';all.textContent='全部事件';select.append(all);for(const kind of [...new Set(this.items.map(x=>x.event))].sort()){const option=document.createElement('option');option.value=kind;option.textContent=this.eventLabel(kind);select.append(option);}select.value=[...select.options].some(o=>o.value===previous)?previous:'all';}
  filtered(){const from=this.$('#from').value||'00:00',to=this.$('#to').value||'23:59';return this.items.filter(item=>{const d=new Date(item.start),t=String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0');return t>=from&&t<=to&&(this.$('#kind').value==='all'||item.event===this.$('#kind').value);});}
  render(){
    this.visibleItems=this.filtered();const list=this.$('#list');list.replaceChildren();
    this.$('#status').textContent=this.visibleItems.length?'共 '+this.visibleItems.length+' 段录像，点击播放。':'这个时间范围没有可用的云端录像。';
    const labels={Ring:'有人按门铃',Pass:'有人经过',Stay:'有人停留',Linger:'有人停留',Motion:'移动事件'};
    this.visibleItems.forEach((item,index)=>{const row=document.createElement('div');row.className='item';const detail=document.createElement('div'),title=document.createElement('div'),meta=document.createElement('div'),button=document.createElement('button');title.textContent=new Date(item.start).toLocaleTimeString('zh-CN',{hour12:false});meta.className='meta';meta.textContent=this.eventLabel(item.event)+' · '+Math.round(item.duration)+' 秒';button.textContent='播放';button.onclick=()=>this.play(index);detail.append(title,meta);row.append(detail,button);list.append(row);});
  }
  async play(index){
    const item=this.visibleItems?.[index];if(!item||!this._hass)return;
    this.stop();this.index=index;const mine=this.generation;this.$('#status').textContent='正在准备 '+new Date(item.start).toLocaleTimeString('zh-CN',{hour12:false})+' 的录像…';
    try{const result=await this._hass.callWS({type:'mi_cateye/recordings_prepare',recording_id:item.id});if(mine!==this.generation||!this.isConnected)return;this.$('.player').hidden=false;this.$('#playing').textContent=new Date(item.start).toLocaleString('zh-CN',{hour12:false});this.$('#download').href=result.download_url;this.$('#previous').disabled=index+1>=this.visibleItems.length;this.$('#next').disabled=index===0;const v=this.$('video');v.src=result.url;this.$('#status').textContent='';v.play().catch(()=>{this.$('#status').textContent='录像已准备好，请点播放器的播放按钮。';});}
    catch(e){if(mine===this.generation)this.$('#status').textContent=e?.message||'这段录像暂时无法播放，请选择其它时间。';}
  }
}
if(!customElements.get('mi-cateye-recordings-panel'))customElements.define('mi-cateye-recordings-panel',CatEyeRecordingsPanel);
