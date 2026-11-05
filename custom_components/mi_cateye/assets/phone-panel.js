
class DoorbellPhonePanel extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});this.sequence=0;this.started=false;}
  set hass(value){this._hass=value;if(this.isConnected){this.updateNotice();if(!this.started)this.open();}}
  updateNotice(){
    const notice=this.shadowRoot.querySelector('#battery-notice');if(!notice)return;
    const query=new URLSearchParams(window.location.search),raw=this._hass?.states?.['sensor.zhi_neng_mao_yan_dian_liang']?.state;
    const battery=raw&&raw.trim()!==''?Number(raw):NaN;
    notice.hidden=!(query.get('manual')==='1'&&!query.get('device')&&Number.isFinite(battery)&&battery>=0&&battery<30);
  }
  connectedCallback(){
    this.shadowRoot.innerHTML=`<style>
      :host{display:flex;box-sizing:border-box;min-height:100%;height:100%;align-items:center;justify-content:center;padding:12px;background:var(--primary-background-color,#10151d);color:var(--primary-text-color,#fff);font-family:system-ui}
      .card{width:min(600px,100%);border-radius:20px;overflow:hidden;background:var(--card-background-color,#1b2330);box-shadow:0 8px 32px #0004}
      header{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;gap:12px}h2{margin:0;font-size:18px;font-weight:600}
      button{border:0;background:transparent;color:inherit;font:inherit;padding:8px;cursor:pointer;min-width:44px;min-height:44px}
      .frame{position:relative;width:100%;padding-top:56.25%;background:#10151d}iframe{position:absolute;inset:0;width:100%;height:100%;border:0}
      p{margin:0;padding:16px}p:empty{display:none}footer{padding:4px 12px;text-align:right}
      #battery-notice{background:var(--warning-color,#c77700);color:#fff;line-height:1.5}
      .controls{display:flex;justify-content:center;gap:36px;padding:12px}.round{width:84px;height:84px;border-radius:50%;background:rgba(35,115,215,.5);display:flex;align-items:center;justify-content:center;color:white}.round svg{width:50px;height:50px;filter:drop-shadow(0 0 1px #ccc)}
      dialog{border:0;border-radius:20px;background:var(--card-background-color,#1b2330);color:inherit;padding:20px;width:min(360px,80vw)}dialog::backdrop{background:#0008}select{width:100%;padding:12px;font:inherit;color:inherit;background:var(--primary-background-color,#10151d);border:1px solid #8886;border-radius:10px}.actions{display:flex;justify-content:flex-end;gap:12px;padding-top:12px}
      [hidden]{display:none}
      </style><section class="card"><header><h2>门口实时画面</h2><button id="close" aria-label="关闭视频">关闭</button></header><p id="battery-notice" role="note" hidden>猫眼电量低于30%，手动查看可能受限，请充电后再试。门铃触发视频不受影响。</p><div class="frame"><iframe title="门口实时视频" allow="autoplay"></iframe></div><div class="controls"><button class="round" id="voice-reply" aria-label="语音回复" title="语音回复"><svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M3 4H21V17H10L5 21V17H3Z"/><g fill="#19764b"><circle cx="8" cy="10.5" r=".8"/><circle cx="12" cy="10.5" r=".8"/><circle cx="16" cy="10.5" r=".8"/></g></svg></button></div><p id="reply-status" role="status"></p><p id="status">正在连接…</p><footer hidden><button id="retry">重新连接</button></footer><dialog><h3>语音回复 · 男声</h3><select aria-label="选择回复"><option value="wait">请稍等，马上来</option><option value="parcel">请把快递放门口，谢谢</option><option value="later">现在不方便，请稍后再来</option></select><div class="actions"><button id="reply-cancel">取消</button><button id="reply-send">发送</button></div></dialog></section>`;
    this.updateNotice();
    const replyDialog=this.shadowRoot.querySelector('dialog');
    this.shadowRoot.querySelector('.controls').hidden=!!new URLSearchParams(window.location.search).get('device');
    this.shadowRoot.querySelector('#voice-reply').onclick=()=>replyDialog.showModal();
    this.shadowRoot.querySelector('#reply-cancel').onclick=()=>replyDialog.close();
    this.shadowRoot.querySelector('#reply-send').onclick=()=>this.sendReply();
    this.shadowRoot.querySelector('#close').onclick=()=>{
      this.shadowRoot.querySelector('iframe').src='about:blank';
      history.replaceState(null,'','/');window.dispatchEvent(new CustomEvent('location-changed'));
    };
    this.shadowRoot.querySelector('#retry').onclick=()=>{this.started=false;this.open();};
    if(this._hass&&!this.started)this.open();
  }
  disconnectedCallback(){this.sequence++;this.started=false;this.replyAbort?.abort();this.shadowRoot.querySelector('dialog')?.close();this.shadowRoot.querySelector('iframe')?.removeAttribute('src');}
  async sendReply(){
    if(this.replyBusy)return;
    this.replyBusy=true;
    const button=this.shadowRoot.querySelector('#reply-send'),status=this.shadowRoot.querySelector('#reply-status');
    button.disabled=true;status.textContent='正在发送语音…';this.replyAbort=new AbortController();
    try{
      const preset=this.shadowRoot.querySelector('select').value;
      if(!['wait','parcel','later'].includes(preset))throw new Error('Invalid preset');
      const signed=await this._hass.callWS({type:'auth/sign_path',path:'/api/mi_cateye/talk?action=authorize',expires:60});
      const grant=await fetch(signed.path,{signal:this.replyAbort.signal});if(!grant.ok)throw new Error('Unauthorized');
      const access=(await grant.json()).access;
      const result=await fetch('/api/mi_cateye/talk?action=reply',{method:'POST',headers:{'X-Talk-Access':access,'X-Talk-Preset':preset},signal:this.replyAbort.signal});
      if(!result.ok)throw new Error('Reply failed');
      status.textContent='语音已发送';this.shadowRoot.querySelector('dialog').close();
    }catch(error){if(error.name!=='AbortError')status.textContent='语音回复未完成，请确认视频已打开且没有正在进行的通话后重试';}
    finally{button.disabled=false;this.replyBusy=false;this.replyAbort=null;}
  }
  async open(){
    if(!this._hass||!this.shadowRoot.querySelector('iframe'))return;
    this.started=true;const mine=++this.sequence;
    const status=this.shadowRoot.querySelector('#status'),footer=this.shadowRoot.querySelector('footer');
    footer.hidden=true;status.textContent='正在连接…';
    try{
      const device=new URLSearchParams(window.location.search).get('device');
      if(device&&!/^[0-9]{1,24}$/.test(device))throw new Error('Invalid device');
      if(device)this.shadowRoot.querySelector('h2').textContent='摄像机实时画面';
      const path='/api/mi_cateye/player'+(device?'?device='+encodeURIComponent(device):'');
      const result=await this._hass.callWS({type:'auth/sign_path',path,expires:300});
      if(mine!==this.sequence||!this.isConnected)return;
      this.shadowRoot.querySelector('iframe').src=result.path;status.textContent='';
    }catch(e){if(mine===this.sequence){status.textContent='暂时无法打开视频，请重试';footer.hidden=false;this.started=false;}}
  }
}
if(!customElements.get('mi-cateye-phone-panel'))customElements.define('mi-cateye-phone-panel',DoorbellPhonePanel);
