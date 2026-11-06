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
    if(this.config.variant!=='arc'){
      const dining='<path d="M34 54h112v12H34zM45 66h9v32h-9zM126 66h9v32h-9zM15 43h10v33h17v10H15zM155 43h10v43h-27V76h17zM20 86h8v12h-8zM152 86h8v12h-8z"/><path d="M87 8h6v14h-6zM77 22h26l10 18H67z"/><ellipse cx="90" cy="51" rx="12" ry="3" opacity=".3"/>';
      const balcony='<path d="M60 15h82v57H60zm9 9v39h28V24zm37 0v39h27V24zM54 76h96v8H54zM22 77h28l-4 22H26z"/><path d="M34 80V43h5v37zM36 62C13 63 14 43 17 40c15 1 23 9 19 22zM38 52c0-18 11-24 22-22 1 13-5 24-22 22z"/>';
      return `<svg class="flat-cover" viewBox="0 0 180 110" aria-hidden="true">${kind==='dining'?dining:balcony}</svg>`;
    }
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
      :host([variant=classic]) h2 .header-icon{display:none}:host([variant=classic]) h2{font-weight:500;color:var(--primary-text-color,#212121)}:host([variant=classic]) .tile{background:var(--secondary-background-color,#f4f4f4);color:#87939d}:host([variant=classic]) .tile[data-scene=balcony]{background:var(--secondary-background-color,#f4f4f4);color:#8b9b91}:host([variant=classic]) .label{font-weight:500;background:var(--card-background-color,#fff);border-radius:6px}:host([variant=classic]) .scene svg{opacity:.85}
      :host([variant=arc]) ha-card{padding:16px 18px}:host([variant=arc]) header{height:36px;margin-bottom:10px}:host([variant=arc]) h2{font-size:18px;color:var(--security-accent);gap:11px}:host([variant=arc]) .header-icon{display:flex;width:36px;height:36px;align-items:center;justify-content:center;border-radius:13px;background:#526ac420}:host([variant=arc]) .header-icon ha-icon{--mdc-icon-size:25px}:host([variant=arc]) .grid{height:calc(100% - 46px)}
      .header-actions{display:flex;align-items:center;gap:8px}.cat-recordings{display:flex;align-items:center;gap:4px;padding:7px 8px;min-height:34px;border-radius:12px;color:var(--security-accent);background:color-mix(in srgb,var(--security-accent) 7%,transparent);font:12px system-ui}.cat-recordings ha-icon{--mdc-icon-size:17px}:host([variant=classic]) .cat-recordings{color:var(--secondary-text-color,#666);background:var(--secondary-background-color,#f1f1f1)}.play{width:34px;height:34px;min-height:34px;padding:0;justify-content:center;border-radius:50%;flex-shrink:0}.play ha-icon{--mdc-icon-size:22px}:host([variant=arc]) .play{width:36px;height:36px;background:#526ac412;border-radius:13px}:host([variant=classic]) .play{background:var(--secondary-background-color,#f1f1f1);color:var(--primary-text-color,#555)}
      .tile.expanded{--popup-width:min(960px,calc(100vw - 24px),calc((100dvh - 140px) * var(--video-ratio,1.777778)));width:var(--popup-width);height:calc(var(--popup-width) / var(--video-ratio,1.777778) + 101px)}
      .flat-cover{display:block;width:100%;height:100%;max-width:220px;fill:var(--room-color);padding:12px 12px 0;opacity:.9}
      .tile{--room-color:#9570cd;background:var(--card-background-color,#fff);color:var(--room-color)}.tile[data-scene=balcony]{--room-color:#26a69a;background:var(--card-background-color,#fff);color:var(--room-color)}
      :host([variant=classic]) .tile,:host([variant=classic]) .tile[data-scene=balcony]{background:var(--card-background-color,#fff);color:var(--room-color)}
      .quarter{position:absolute;left:0;bottom:0;width:100px;height:100px;border-radius:0 100% 0 0;background:color-mix(in srgb,var(--room-color) 22%,transparent)}.room-symbol{position:absolute;left:10px;bottom:0;--mdc-icon-size:66px;color:var(--room-color)}
      .label,:host([variant=classic]) .label{top:6px;bottom:auto;left:7px;background:color-mix(in srgb,var(--card-background-color,#fff) 85%,transparent);font-weight:500}
      :host([variant=arc]) .tile{--room-color:#9c8941}:host([variant=arc]) .tile[data-scene=balcony]{--room-color:#8f6baa}:host([variant=arc]) .quarter{width:84px;height:84px;background:color-mix(in srgb,var(--room-color) 13%,transparent)}:host([variant=arc]) .room-symbol{--mdc-icon-size:54px;left:12px;bottom:2px}
      :host([variant=arc]) .tile{background:color-mix(in srgb,var(--security-accent) 9%,var(--card-background-color,#fff));color:var(--security-accent)}:host([variant=arc]) .tile[data-scene=balcony]{background:color-mix(in srgb,#4e9e88 11%,var(--card-background-color,#fff));color:#438775}
      .camera-mark{position:absolute;top:7px;right:8px;width:20px;height:20px;color:var(--secondary-text-color,#87909b);opacity:.65;pointer-events:none}.camera-mark svg{display:block;width:100%;height:100%}.expanded .camera-mark{display:none}
      .expanded .label{top:7px;left:12px}.expanded .scene{overflow:hidden}
      </style><ha-card><header><h2><span class="header-icon"><ha-icon icon="mdi:cctv"></ha-icon></span>安防</h2><div class="header-actions"><button class="play" aria-label="播放两个摄像机" title="播放两个摄像机"><ha-icon icon="mdi:play"></ha-icon></button></div></header><div class="grid"></div></ha-card><button class="backdrop" aria-label="关闭摄像机画面" hidden></button>`;
    this.setAttribute('variant',this.config.variant === 'arc'?'arc':'classic');
    this.config.cameras.forEach((camera,index) => {
      const tile=document.createElement('section');tile.className='tile';tile.dataset.scene=camera.scene;
      tile.innerHTML=`<div class="scene">${this.scene(camera.scene)}</div><div class="stream"></div><span class="camera-mark" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M4 6h16v3H4zM5 10h14a7 7 0 0 1-14 0Z" fill="currentColor"/><circle cx="12" cy="13" r="2.5" fill="var(--card-background-color,#fff)"/><circle cx="12" cy="13" r="1.1" fill="currentColor"/></svg></span><div class="label"></div><button class="open"></button><span class="status" role="status"></span><div class="popup-tools"><button class="recordings"><ha-icon icon="mdi:filmstrip"></ha-icon>查看录像</button></div><button class="close" hidden aria-label="关闭画面">✕</button>`;
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
        frame.onload=()=>{if(seq===this.sequence){tile.querySelector('.status').textContent='';const video=frame.contentDocument?.querySelector('video');if(video){const resize=()=>{if(video.videoWidth&&video.videoHeight)tile.style.setProperty('--video-ratio',String(video.videoWidth/video.videoHeight));};resize();video.addEventListener('loadedmetadata',resize,{once:true});}}};
        tile.querySelector('.stream').replaceChildren(frame);
      }catch(error){if(seq===this.sequence){this.active.delete(index);tile.querySelector('.status').textContent='连接失败，请重试';this.updateButton();}}
    }));
  }
  updateButton() {
    const b=this.shadowRoot.querySelector('.play');if(!b)return;
    b.ariaLabel=this.active.size?'停止摄像机':'播放两个摄像机';b.title=b.ariaLabel;b.querySelector('ha-icon').setAttribute('icon',this.active.size?'mdi:stop':'mdi:play');
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
    this.openRecordings(this.config.cameras[index].device);
  }
  openRecordings(device) {
    this.collapse();this.stop();
    history.pushState(null,'','/mi-cateye-recordings?device='+encodeURIComponent(device)+'&source=sd');window.dispatchEvent(new CustomEvent('location-changed'));
  }
}
if(!customElements.get('mi-security-card'))customElements.define('mi-security-card',MiSecurityCard);
window.customCards=window.customCards||[];
if(!window.customCards.some(c=>c.type==='mi-security-card'))window.customCards.push({type:'mi-security-card',name:'安防',description:'按需播放两路摄像机与存储卡回看'});
