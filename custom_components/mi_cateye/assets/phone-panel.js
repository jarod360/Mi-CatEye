
class DoorbellPhonePanel extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});this.sequence=0;this.started=false;}
  set hass(value){this._hass=value;if(this.isConnected&&!this.started)this.open();}
  connectedCallback(){
    this.shadowRoot.innerHTML=`<style>
      :host{display:flex;box-sizing:border-box;min-height:100%;height:100%;align-items:center;justify-content:center;padding:12px;background:var(--primary-background-color,#10151d);color:var(--primary-text-color,#fff);font-family:system-ui}
      .card{width:min(600px,100%);border-radius:20px;overflow:hidden;background:var(--card-background-color,#1b2330);box-shadow:0 8px 32px #0004}
      header{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;gap:12px}h2{margin:0;font-size:18px;font-weight:600}
      button{border:0;background:transparent;color:inherit;font:inherit;padding:8px;cursor:pointer;min-width:44px;min-height:44px}
      .frame{position:relative;width:100%;padding-top:56.25%;background:#10151d}iframe{position:absolute;inset:0;width:100%;height:100%;border:0}
      p{margin:0;padding:16px}p:empty{display:none}footer{padding:4px 12px;text-align:right}
      [hidden]{display:none}
      </style><section class="card"><header><h2>门口实时画面</h2><button id="close" aria-label="关闭视频">关闭</button></header><div class="frame"><iframe title="门口实时视频" allow="autoplay"></iframe></div><p id="status">正在连接…</p><footer hidden><button id="retry">重新连接</button></footer></section>`;
    this.shadowRoot.querySelector('#close').onclick=()=>{
      this.shadowRoot.querySelector('iframe').src='about:blank';
      history.replaceState(null,'','/');window.dispatchEvent(new CustomEvent('location-changed'));
    };
    this.shadowRoot.querySelector('#retry').onclick=()=>{this.started=false;this.open();};
    if(this._hass&&!this.started)this.open();
  }
  disconnectedCallback(){this.sequence++;this.started=false;this.shadowRoot.querySelector('iframe')?.removeAttribute('src');}
  async open(){
    if(!this._hass||!this.shadowRoot.querySelector('iframe'))return;
    this.started=true;const mine=++this.sequence;
    const status=this.shadowRoot.querySelector('#status'),footer=this.shadowRoot.querySelector('footer');
    footer.hidden=true;status.textContent='正在连接…';
    try{
      const result=await this._hass.callWS({type:'auth/sign_path',path:'/api/mi_cateye/player',expires:300});
      if(mine!==this.sequence||!this.isConnected)return;
      this.shadowRoot.querySelector('iframe').src=result.path;status.textContent='';
    }catch(e){if(mine===this.sequence){status.textContent='暂时无法打开视频，请重试';footer.hidden=false;this.started=false;}}
  }
}
if(!customElements.get('mi-cateye-phone-panel'))customElements.define('mi-cateye-phone-panel',DoorbellPhonePanel);
