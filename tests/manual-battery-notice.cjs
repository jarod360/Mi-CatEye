const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let Panel;
const context={HTMLElement:class{},URLSearchParams,window:{location:{search:''}},customElements:{get:()=>false,define:(_,c)=>Panel=c}};
vm.runInNewContext(fs.readFileSync('custom_components/mi_cateye/assets/phone-panel.js','utf8'),context);
for(const [search,battery,hidden] of [['?manual=1','29',false],['?manual=1','30',true],['','29',true],['?manual=1&device=123','29',true],['?manual=1','unavailable',true],['?manual=1','',true]]){
 context.window.location.search=search;
 const notice={};const panel={_hass:{states:{'sensor.zhi_neng_mao_yan_dian_liang':{state:battery}}},shadowRoot:{querySelector:()=>notice}};
 Panel.prototype.updateNotice.call(panel);assert.equal(notice.hidden,hidden);
}
console.log('6 manual-only battery notice scenarios passed');
