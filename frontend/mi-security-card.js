/* HA authenticated, on-demand two-camera overview. No background preloading. */
class MiSecurityCard extends HTMLElement {
  constructor() {
    super(); this.attachShadow({mode:'open'}); this.sequence = 0; this.active = new Set();
    this.onVisibility = () => { if (document.hidden) this.stop(); };
    this.onKey = e => { if(e.key === 'Escape') this.collapse(); };
  }
  setConfig(config) {
    if (!Array.isArray(config.cameras) || config.cameras.length !== 2 || config.cameras.some(c => !/^\d{1,24}$/.test(c.device) || !['dining','balcony'].includes(c.scene))) throw Error('Configure two supported cameras');
    this.stop(); this.config = structuredClone(config); if(this.isConnected) this.render();
  }
  set hass(value) { this._hass = value; }
  getCardSize() { return 3; }
  connectedCallback() {
    if(this.config) this.render();
    document.addEventListener('visibilitychange',this.onVisibility);
    document.addEventListener('keydown',this.onKey);
    this.observer = new IntersectionObserver(rows => { if(rows.every(r => !r.isIntersecting)) this.stop(); });
    this.observer.observe(this);
  }
  disconnectedCallback() { this.stop(); this.observer?.disconnect(); document.removeEventListener('visibilitychange',this.onVisibility); document.removeEventListener('keydown',this.onKey); }
  scene(kind) {
    const common='<path d="M0 110H240V140H0Z" fill="currentColor" opacity=".07"/><path d="M0 110H240M26 110V22H213V110" fill="none" stroke="currentColor" opacity=".18" stroke-width="2"/>';
    const dining='<path d="M55 82H183L172 91H65Z" fill="currentColor" opacity=".32"/><path d="M74 91V118M164 91V118M44 75V105H58V120M193 75V105H179V120M120 23V40" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" opacity=".42"/><path d="M104 53L111 40H129L136 53Z" fill="currentColor" opacity=".45"/><ellipse cx="120" cy="75" rx="11" ry="3" fill="currentColor" opacity=".24"/>';
    const balcony='<path d="M57 29H176V100H57ZM116 29V100M57 64H176" fill="none" stroke="currentColor" stroke-width="3" opacity=".32"/><path d="M35 103H54L51 121H38Z" fill="currentColor" opacity=".4"/><path d="M45 104V75M45 92Q26 90 30 78Q45 78 45 92M45 85Q60 81 57 69Q44 70 45 85" fill="none" stroke="currentColor" stroke-width="3" opacity=".48"/><path d="M190 39V91M185 46H201M185 65H201M185 84H201" stroke="currentColor" stroke-width="3" opacity=".25"/>';
    return `<svg viewBox="0 0 240 140" aria-hidden="true">${common}${kind==='dining'?dining:balcony}</svg>`;
  }
  render() {
    this.shadowRoot.innerHTML = `<style>
      :host{display:block;min-width:0;--security-accent:#526ac4;--security-height:178px;--security-radius:18px}
      :host([variant=arc]){--security-height:170px;--security-radius:28px}
      *{box-sizing:border-box}ha-card{display:block;height:var(--security-height);border-radius:var(--security-radius);overflow:hidden;background:var(--ha-card-background,var(--card-background-color,#fff));color:var(--primary-text-color,#222f55);border:1px solid var(--divider-color,#dfe5f2);padding:12px 14px;box-shadow:var(--ha-card-box-shadow,0 3px 12px #2c407006)}
      header{height:30px;display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px}h2{font:600 17px var(--paper-font-body1_-_font-family,system-ui);margin:0;display:flex;align-items:center;gap:7px}h2 ha-icon{--mdc-icon-size:21px;color:var(--security-accent)}button{font:inherit;cursor:pointer;border:0;color:inherit;background:transparent}button:focus-visible{outline:2px solid var(--security-accent);outline-offset:-3px}.play{display:flex;align-items:center;gap:5px;border-radius:18px;background:color-mix(in srgb,var(--security-accent) 12%,transparent);color:var(--security-accent);font-size:12px;padding:6px 11px;min-height:30px}.play ha-icon{--mdc-icon-size:17px}
      .grid{height:calc(100% - 38px);display:grid;grid-template-columns:1fr 1fr;gap:10px}.tile{position:relative;min-width:0;min-height:0;border-radius:12px;overflow:hidden;background:color-mix(in srgb,var(--security-accent) 9%,var(--card-background-color,#fff));color:var(--security-accent)}.tile[data-scene=balcony]{background:color-mix(in srgb,#4e9e88 11%,var(--card-background-color,#fff));color:#438775}.scene{position:absolute;inset:0;display:flex;justify-content:center;align-items:center;pointer-events:none}.scene svg{height:100%;width:100%;object-fit:contain}.label{position:absolute;left:10px;bottom:8px;border-radius:8px;padding:4px 7px;font:600 13px system-ui;background:color-mix(in srgb,var(--card-background-color,#fff) 85%,transparent);color:var(--primary-text-color,#222f55);pointer-events:none}.open{position:absolute;inset:0;width:100%;height:100%;z-index:2}.open ha-icon{position:absolute;right:8px;top:8px;--mdc-icon-size:18px;opacity:.7}.stream{position:absolute;inset:0;pointer-events:none}.stream iframe{border:0;width:100%;height:100%;display:block;background:#111}.status{position:absolute;right:8px;bottom:9px;z-index:3;font:11px system-ui;max-width:65%;background:#fffD;color:#333;border-radius:7px;padding:3px 5px;pointer-events:none}.status:empty{display:none}
      .backdrop{position:fixed;inset:0;z-index:1000;background:#0009}.tile.expanded{position:fixed;z-index:1001;width:min(960px,calc(100vw - 24px));height:min(640px,calc(100dvh - 40px));left:50%;top:50%;transform:translate(-50%,-50%);background:var(--card-background-color,#fff);border-radius:20px;display:flex;flex-direction:column;padding-bottom:56px;padding-top:45px}.expanded .scene,.expanded .stream{top:45px;bottom:56px}.expanded .stream iframe{object-fit:contain}.expanded .open{display:none}.expanded .label{top:7px;bottom:auto;left:12px;right:65px;background:transparent}.expanded .status{bottom:65px;right:12px}.popup-tools{display:none}.expanded .popup-tools{display:flex;position:absolute;bottom:0;left:0;right:0;height:56px;align-items:center;justify-content:flex-end;gap:10px;padding:8px 12px}.recordings{display:flex;align-items:center;gap:6px;background:var(--security-accent);color:white;border-radius:12px;padding:9px 13px;font:14px system-ui}.close{position:absolute;right:7px;top:3px;min-width:42px;min-height:38px}.recordings ha-icon{--mdc-icon-size:20px}[hidden]{display:none!important}@media(max-width:450px){ha-card{padding:10px 11px}.grid{gap:8px}.label{font-size:12px;left:5px;bottom:5px}.play{font-size:11px}}
      </style><ha-card><header><h2><ha-icon icon="mdi:shield-home-outline"></ha-icon>安防</h2><button class="play" aria-label="播放两个摄像机"><ha-icon icon="mdi:play"></ha-icon><span>播放</span></button></header><div class="grid"></div></ha-card><button class="backdrop" aria-label="关闭摄像机画面" hidden></button>`;
    this.setAttribute('variant',this.config.variant === 'arc'?'arc':'classic');
    this.config.cameras.forEach((camera,index) => {
      const tile=document.createElement('section');tile.className='tile';tile.dataset.scene=camera.scene;
      tile.innerHTML=`<div class="scene">${this.scene(camera.scene)}</div><div class="stream"></div><div class="label"></div><button class="open"></button><span class="status" role="status"></span><div class="popup-tools"><button class="recordings"><ha-icon icon="mdi:filmstrip"></ha-icon>查看录像</button></div><button class="close" hidden aria-label="关闭画面">✕</button>`;
      tile.querySelector('.label').textContent=camera.name;
      tile.querySelector('.open').ariaLabel='查看'+camera.name;
      tile.querySelector('.open').onclick=()=>this.expand(index);
      tile.querySelector('.close').onclick=()=>this.collapse();
      tile.querySelector('.recordings').onclick=()=>this.recordings(index);
      this.shadowRoot.querySelector('.grid').append(tile);
    });
    this.shadowRoot.querySelector('.play').onclick=()=>this.active.size?this.stop():this.play([0,1]);
    this.shadowRoot.querySelector('.backdrop').onclick=()=>this.collapse();
  }
  tiles() { return [...this.shadowRoot.querySelectorAll('.tile')]; }
  async play(indices) {
    if(!this._hass)return;
    const seq=this.sequence;
    await Promise.all(indices.map(async index=>{
      if(this.active.has(index))return;
      this.active.add(index);this.updateButton();
      const tile=this.tiles()[index];tile.querySelector('.status').textContent='正在连接…';
      try {
        const path='/api/mi_cateye/player?device='+encodeURIComponent(this.config.cameras[index].device);
        const signed=await this._hass.callWS({type:'auth/sign_path',path,expires:300});
        if(seq!==this.sequence||!this.isConnected||!this.active.has(index))return;
        const frame=document.createElement('iframe');frame.title=this.config.cameras[index].name+'实时画面';frame.allow='autoplay';frame.src=signed.path;
        frame.onload=()=>{if(seq===this.sequence)tile.querySelector('.status').textContent='';};
        tile.querySelector('.stream').replaceChildren(frame);
      }catch(error){if(seq===this.sequence){this.active.delete(index);tile.querySelector('.status').textContent='连接失败，请重试';this.updateButton();}}
    }));
  }
  updateButton() {
    const b=this.shadowRoot.querySelector('.play');if(!b)return;
    b.querySelector('span').textContent=this.active.size?'停止':'播放';b.ariaLabel=this.active.size?'停止摄像机':'播放两个摄像机';b.querySelector('ha-icon').setAttribute('icon',this.active.size?'mdi:stop':'mdi:play');
  }
  stop() {
    this.sequence++;this.active.clear();
    this.shadowRoot.querySelectorAll('iframe').forEach(f=>{f.removeAttribute('src');f.remove();});
    this.shadowRoot.querySelectorAll('.status').forEach(s=>s.textContent='');
    this.updateButton();
  }
  expand(index) {
    this.collapse();this.overviewWasPlaying=this.active.size>0;this.expanded=index;
    const tile=this.tiles()[index];tile.classList.add('expanded');tile.setAttribute('role','dialog');tile.setAttribute('aria-modal','true');tile.setAttribute('aria-label',this.config.cameras[index].name);
    tile.querySelector('.close').hidden=false;this.shadowRoot.querySelector('.backdrop').hidden=false;
    this.play([index]);tile.querySelector('.close').focus();
  }
  collapse() {
    if(this.expanded===undefined)return;
    const index=this.expanded;this.expanded=undefined;
    this.tiles().forEach(t=>{t.classList.remove('expanded');t.removeAttribute('role');t.removeAttribute('aria-modal');t.querySelector('.close').hidden=true;});
    this.shadowRoot.querySelector('.backdrop').hidden=true;
    if(!this.overviewWasPlaying)this.stop();
    this.tiles()[index]?.querySelector('.open').focus();
  }
  recordings(index) {
    const device=this.config.cameras[index].device;this.collapse();this.stop();
    history.pushState(null,'','/mi-cateye-recordings?device='+encodeURIComponent(device));window.dispatchEvent(new CustomEvent('location-changed'));
  }
}
if(!customElements.get('mi-security-card'))customElements.define('mi-security-card',MiSecurityCard);
window.customCards=window.customCards||[];
if(!window.customCards.some(c=>c.type==='mi-security-card'))window.customCards.push({type:'mi-security-card',name:'安防',description:'按需播放两路摄像机与存储卡回看'});
