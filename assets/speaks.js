// Private speaker-points page. Data: data/speaks.enc.json (AES-256-GCM, key = PBKDF2-SHA256 of the passphrase),
// built by tools/speaks/build.py + encrypt.py. Nothing here knows the passphrase or can tell a right one from a
// wrong one except by trying to decrypt.
(function(){
'use strict';
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const KEY_SLOT='npte-speaks-key';
$('dark').onclick=()=>{const d=document.documentElement.classList.toggle('dark');try{localStorage.setItem('npte-theme',d?'dark':'light')}catch(e){}};

// ---------------------------------------------------------------- unlock
const b64=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
const toB64=buf=>btoa(String.fromCharCode(...new Uint8Array(buf)));
let ENV=null;
async function envelope(){if(!ENV){const r=await fetch('data/speaks.enc.json',{cache:'no-store'});if(!r.ok)throw new Error('load');ENV=await r.json()}return ENV}
async function open(key,env){
  const pt=await crypto.subtle.decrypt({name:'AES-GCM',iv:b64(env.iv)},key,b64(env.ct));
  let bytes=new Uint8Array(pt);
  if(env.gz){const ds=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));bytes=new Uint8Array(await new Response(ds).arrayBuffer())}
  return JSON.parse(new TextDecoder().decode(bytes));
}
async function keyFromPass(pass,env){
  const km=await crypto.subtle.importKey('raw',new TextEncoder().encode(pass),'PBKDF2',false,['deriveKey']);
  return crypto.subtle.deriveKey({name:'PBKDF2',salt:b64(env.salt),iterations:env.iter,hash:'SHA-256'},km,{name:'AES-GCM',length:256},true,['decrypt']);
}
function lock(){try{sessionStorage.removeItem(KEY_SLOT)}catch(e){}location.hash='';location.reload()}
$('lock').onclick=lock;
$('gateForm').onsubmit=async ev=>{
  ev.preventDefault();
  const pass=$('pass').value;if(!pass)return;
  $('go').disabled=true;$('gateMsg').textContent='Unlocking…';
  let env;
  try{env=await envelope()}catch(e){$('gateMsg').textContent='Could not load the data file.';$('go').disabled=false;return}
  try{
    const key=await keyFromPass(pass,env);
    const data=await open(key,env);
    try{sessionStorage.setItem(KEY_SLOT,toB64(await crypto.subtle.exportKey('raw',key)))}catch(e){}
    $('pass').value='';start(data);
  }catch(e){$('gateMsg').textContent='Incorrect passphrase';$('pass').select()}
  $('go').disabled=false;
};
(async()=>{ // same tab, already unlocked: the derived key (never the passphrase) is kept until the tab closes or Lock is pressed
  let raw=null;try{raw=sessionStorage.getItem(KEY_SLOT)}catch(e){}
  if(!raw)return;
  try{const env=await envelope();const key=await crypto.subtle.importKey('raw',b64(raw),{name:'AES-GCM'},true,['decrypt']);start(await open(key,env))}
  catch(e){try{sessionStorage.removeItem(KEY_SLOT)}catch(_){}}
})();

// ---------------------------------------------------------------- app
function start(D){
$('gate').hidden=true;$('lock').hidden=false;$('app').hidden=false;
const R=D.r,DEC=D.d,T=D.tournaments,DEB=D.debaters,JUD=D.judges,SCH=D.schools,SEASONS=D.seasons;
// row: [0 tourn,1 round,2 debater,3 partner,4 school,5 judge,6 side,7 win,8 pts,9 rank]
const tOrder=i=>T[i][1]*100+T[i][2];
$('sub').textContent=`${R.length.toLocaleString()} speaker scores · ${D.meta.tournaments_with_speaks} of ${D.meta.tournaments_total} tournaments · ${SEASONS[0]} to ${SEASONS[SEASONS.length-1]} · built ${D.meta.built}`;

// ---- stats helpers
const mean=a=>a.length?a.reduce((x,y)=>x+y,0)/a.length:null;
const median=a=>{if(!a.length)return null;const s=a.slice().sort((x,y)=>x-y),m=s.length>>1;return s.length%2?s[m]:(s[m-1]+s[m])/2};
const sd=a=>{if(a.length<2)return null;const m=mean(a);return Math.sqrt(a.reduce((x,y)=>x+(y-m)*(y-m),0)/(a.length-1))};
const f=(v,d=2)=>v==null||isNaN(v)?'–':v.toFixed(d);
const sg=(v,d=2)=>v==null||isNaN(v)?'–':`<span class="${v>0.005?'pos':v<-0.005?'neg':''}">${v>0?'+':''}${v.toFixed(d)}</span>`;
const pct=(a,b)=>b?Math.round(100*a/b)+'%':'–';

// ---- judge baselines over every scored ballot (all seasons), with the debater's own ballots left out
const SD_FLOOR=0.5;
const J={},JD=new Map(),DB={};
for(const r of R){
  const d=DB[r[2]]||(DB[r[2]]={n:0,s:0});d.n++;d.s+=r[8];
  if(r[5]<0)continue;
  const j=J[r[5]]||(J[r[5]]={n:0,s:0,q:0});j.n++;j.s+=r[8];j.q+=r[8]*r[8];
  const k=r[5]*100000+r[2];const jd=JD.get(k)||{n:0,s:0,q:0};jd.n++;jd.s+=r[8];jd.q+=r[8]*r[8];JD.set(k,jd);
}
// league yardstick for turning a z-score back into points: the average score, and the typical spread of one judge's scores
let LG_N=0,LG_S=0,LG_SS=0,LG_J=0;
for(const k in J){const j=J[k];LG_N+=j.n;LG_S+=j.s;LG_SS+=j.q-j.s*j.s/j.n;LG_J++}
const LG_MU=LG_N?LG_S/LG_N:0,LG_SD=LG_N>LG_J?Math.sqrt(LG_SS/(LG_N-LG_J)):1;
const adjAvg=z=>z==null?null:LG_MU+z*LG_SD;
let MINJ=5;
function base(r){ // the judge's mean and SD on everyone else -> {mu, sd} or null if too few ballots
  if(r[5]<0)return null;const j=J[r[5]],jd=JD.get(r[5]*100000+r[2]),n=j.n-jd.n;
  if(n<MINJ)return null;const mu=(j.s-jd.s)/n,v=Math.max((j.q-jd.q)/n-mu*mu,0);
  return {mu,sd:Math.max(Math.sqrt(v),SD_FLOOR)};
}
function others(r){ // the debater's mean from every other judge
  if(r[5]<0)return null;const d=DB[r[2]],jd=JD.get(r[5]*100000+r[2]),n=d.n-jd.n;
  return n>=5?(d.s-jd.s)/n:null;
}

// ---- state
const S={tab:'c',seasons:new Set(),tourn:'',school:'',minC:10,minJ:3,qC:'',qJ:'',sortC:['aa',-1],sortJ:['rooms',-1]};
const inScope=t=>(!S.seasons.size||S.seasons.has(T[t][1]))&&(S.tourn===''||+S.tourn===t);

// ---- shell
$('app').innerHTML=`
<div class="tabs"><button class="btn" data-tab="c">Competitors</button><button class="btn" data-tab="j">Judges</button></div>
<div class="card" id="filters"></div>
<div class="card" id="out"></div>
<details class="card" id="cov"><summary>Coverage: which tournaments are in here, and which are not</summary><div id="covBody"></div></details>
<details class="card"><summary>How the numbers are worked out</summary><div class="note" id="method"></div></details>`;
$('method').innerHTML=`
<p><b>What counts.</b> Open/Varsity NPDA and NPTE prelim speaker points, one score per debater per judge per round, exactly as printed on the result sheets. Byes (which print an average, not a judge's score) and scores outside ${D.meta.range[0]}–${D.meta.range[1]} (zeros for an absent partner, forfeits, mis-keyed ranks) are left out.</p>
<p><b>Vs Judge.</b> For each ballot: the points a debater got minus what that judge gives on average to <i>everyone else</i> (the debater's own ballots are left out, so a debater seen often by one judge does not move their own yardstick). A judge needs at least the chosen number of other ballots to count. The column is the average of those differences: +0.50 means half a point above what the same judges usually give.</p>
<p><b>Z-score.</b> The same difference divided by how spread out that judge's points are (their standard deviation, never taken as less than ${SD_FLOOR}). It puts a generous judge with a wide range and a strict judge with a narrow range on the same scale. 0 is that judge's average; +1.0 is one standard deviation above it. Averaged over the debater's ballots. This is the fairest single column for comparing debaters who saw different judges.</p>
<p><b>Adj Avg.</b> The Z-score put back on the points scale so it reads like an average: the league-wide average score (${f(LG_MU)}) plus the Z-score times the spread of a typical judge's scores (${f(LG_SD)}). Read it as "what this debater would average in front of a typical judge". Compare it with Raw Avg: higher means their judges were stricter than usual, lower means their judges were generous. It ranks debaters in the same order as the Z-score.</p>
<p><b>Judge baselines use every season</b>, whatever filters are set, so a judge's yardstick does not wobble when you narrow the view.</p>
<p><b>Judges.</b> <i>Vs Others</i> is the mirror image: this judge's points minus what the same debaters averaged from all their other judges. Positive = more generous than their peers to the same people; negative = stricter. <i>W–L Gap</i> is the average points to winners minus losers. <i>Low-Pt Win</i> is how often the winning team got fewer total points than the losing team. <i>Aff % / Neg %</i> is the share of this judge's decisions that went to each side, counting prelims and, where the sheet records each panel member's vote, elims.</p>
<p><b>Caveat.</b> The adjustment assumes a judge sees a roughly typical mix of teams. A judge who mostly sits top-bracket rooms has a higher average for a real reason, so their debaters are adjusted down a little more than they should be. Treat small differences as ties.</p>`;
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{location.hash='';S.tab=b.dataset.tab;render()});

function filters(){
  const tl=T.map((t,i)=>[t,i]).filter(([t])=>!S.seasons.size||S.seasons.has(t[1])).filter(([t])=>S.tab==='c'?t[6]>0:(t[6]>0||t[7]>0));
  if(S.tourn!==''&&!tl.some(([,i])=>i===+S.tourn))S.tourn='';
  const sch=[...new Set(R.filter(r=>inScope(r[0])).map(r=>r[4]))].map(i=>[SCH[i],i]).sort((a,b)=>a[0].localeCompare(b[0]));
  const c=S.tab==='c';
  $('filters').innerHTML=`<div class="row">
  <div><label>Seasons (none selected = all)</label><div class="chips">${SEASONS.map((s,i)=>`<button class="chip ${S.seasons.has(i)?'on':''}" data-season="${i}">${esc(s)}</button>`).join('')}</div></div>
  </div><div class="row" style="margin-top:12px">
  <div><label>Tournament</label><select id="fT"><option value="">All tournaments</option>${tl.map(([t,i])=>`<option value="${i}" ${S.tourn!==''&&+S.tourn===i?'selected':''}>${esc(t[0])}</option>`).join('')}</select></div>
  ${c?`<div><label>School</label><select id="fS"><option value="">All schools</option>${sch.map(([n,i])=>`<option value="${i}" ${S.school!==''&&+S.school===i?'selected':''}>${esc(n)}</option>`).join('')}</select></div>`:''}
  <div><label>Min rounds</label><input id="fM" type="number" min="1" style="width:90px" value="${c?S.minC:S.minJ}"></div>
  ${c?`<div><label>Judge needs at least</label><select id="fN"><option value="5" ${MINJ===5?'selected':''}>5 other ballots</option><option value="10" ${MINJ===10?'selected':''}>10 other ballots</option></select></div>`:''}
  <div><label>Search ${c?'debater':'judge'} (ignores the minimum)</label><input class="name" id="fQ" list="dl" placeholder="Type a name…" value="${esc(c?S.qC:S.qJ)}"></div>
  </div><datalist id="dl">${(c?DEB:JUD.map(j=>j[0])).slice().sort().map(n=>`<option value="${esc(n)}">`).join('')}</datalist>`;
  document.querySelectorAll('[data-season]').forEach(b=>b.onclick=()=>{const i=+b.dataset.season;S.seasons.has(i)?S.seasons.delete(i):S.seasons.add(i);render()});
  $('fT').onchange=e=>{S.tourn=e.target.value;render()};
  if(c){$('fS').onchange=e=>{S.school=e.target.value;toTable()};$('fN').onchange=e=>{MINJ=+e.target.value;render()}}
  $('fM').oninput=e=>{const v=Math.max(1,+e.target.value||1);c?S.minC=v:S.minJ=v;toTable()};
  $('fQ').oninput=e=>{const v=e.target.value;c?S.qC=v:S.qJ=v;const list=c?DEB:JUD.map(j=>j[0]);const i=list.indexOf(v);if(i>=0){go(c?'c':'j',i)}else toTable()};
}
const norm=s=>s.toLowerCase().normalize('NFKD').replace(/[^a-z ]/g,'');
function go(kind,i){location.hash=kind+'='+encodeURIComponent(kind==='c'?DEB[i]:JUD[i][0])}
const linkC=i=>i<0?'':`<span class="clickable" data-go="c${i}">${esc(DEB[i])}</span>`;
const linkJ=i=>i<0?'<span class="muted">not named</span>':`<span class="clickable" data-go="j${i}">${esc(JUD[i][0])}</span>`;
function wire(root){root.querySelectorAll('[data-go]').forEach(e=>e.onclick=()=>go(e.dataset.go[0],+e.dataset.go.slice(1)))}

// ---- generic sortable table
function grid(cols,rows,sort,onSort,rowAttr){
  const [k,dir]=sort;const col=cols.find(c=>c.k===k)||cols[0];
  rows.sort((a,b)=>{const x=col.v(a),y=col.v(b);if(x==null&&y==null)return 0;if(x==null)return 1;if(y==null)return -1;return (typeof x==='string'?x.localeCompare(y):x-y)*dir});
  const h=cols.map(c=>`<th class="${c.num?'n':''}" data-k="${c.k}" title="${esc(c.tip||'')}">${esc(c.h)}${c.k===k?` <span class="arr">${dir>0?'▲':'▼'}</span>`:''}</th>`).join('');
  const b=rows.map((r,i)=>`<tr><td class="n muted">${i+1}</td>${cols.map(c=>`<td class="${c.num?'n':''}">${c.f?c.f(r):esc(c.v(r))}</td>`).join('')}</tr>`).join('');
  const el=document.createElement('div');el.className='tbl';
  el.innerHTML=`<table><thead><tr><th class="n">#</th>${h}</tr></thead><tbody>${b||`<tr><td colspan="${cols.length+1}" class="muted">Nothing matches these filters.</td></tr>`}</tbody></table>`;
  el.querySelectorAll('th[data-k]').forEach(th=>th.onclick=()=>{const nk=th.dataset.k;onSort(nk===k?[k,-dir]:[nk,(cols.find(c=>c.k===nk).num?-1:1)])});
  wire(el);return el;
}

// ---- competitor aggregation
function cStats(rows){
  const p=rows.map(r=>r[8]),dl=[],zs=[];
  for(const r of rows){const b=base(r);if(b){dl.push(r[8]-b.mu);zs.push((r[8]-b.mu)/b.sd)}}
  return {n:rows.length,avg:mean(p),med:median(p),sd:sd(p),hi:p.length?Math.max(...p):null,lo:p.length?Math.min(...p):null,
    w:mean(rows.filter(r=>r[7]===1).map(r=>r[8])),l:mean(rows.filter(r=>r[7]===0).map(r=>r[8])),
    adj:mean(dl),z:mean(zs),aa:adjAvg(mean(zs)),an:dl.length,rec:[rows.filter(r=>r[7]===1).length,rows.filter(r=>r[7]===0).length]};
}
function modeOf(a){const c=new Map();let b=null,bn=0;for(const x of a){const n=(c.get(x)||0)+1;c.set(x,n);if(n>=bn){b=x;bn=n}}return b}
function competitorTable(){
  const by=new Map();
  for(const r of R){if(!inScope(r[0]))continue;if(S.school!==''&&r[4]!==+S.school)continue;(by.get(r[2])||by.set(r[2],[]).get(r[2])).push(r)}
  const q=norm(S.qC.trim());let list=[];
  for(const [d,rows] of by){if(q?!norm(DEB[d]).includes(q):rows.length<S.minC)continue;const s=cStats(rows);s.d=d;s.name=DEB[d];s.school=SCH[modeOf(rows.map(r=>r[4]))];list.push(s)}
  const cols=[
   {k:'name',h:'Debater',v:r=>r.name,f:r=>linkC(r.d)},{k:'school',h:'School',v:r=>r.school},
   {k:'n',h:'Rounds',num:1,v:r=>r.n,tip:'Scored ballots in view'},{k:'avg',h:'Raw Avg',num:1,v:r=>r.avg,f:r=>f(r.avg)},
   {k:'aa',h:'Adj Avg',num:1,v:r=>r.aa,f:r=>r.aa==null?'–':`<b>${f(r.aa)}</b>`,tip:'Judge-adjusted average: what this debater would average in front of a typical judge (league average + Z-score × a typical judge\'s spread)'},
   {k:'med',h:'Median',num:1,v:r=>r.med,f:r=>f(r.med,1)},{k:'sd',h:'Std Dev',num:1,v:r=>r.sd,f:r=>f(r.sd)},
   {k:'hi',h:'High',num:1,v:r=>r.hi,f:r=>f(r.hi,1)},{k:'lo',h:'Low',num:1,v:r=>r.lo,f:r=>f(r.lo,1)},
   {k:'w',h:'Win Avg',num:1,v:r=>r.w,f:r=>f(r.w)},{k:'l',h:'Loss Avg',num:1,v:r=>r.l,f:r=>f(r.l)},
   {k:'adj',h:'Vs Judge',num:1,v:r=>r.adj,f:r=>sg(r.adj),tip:'Average of (points − what that judge gives everyone else)'},
   {k:'z',h:'Z-Score',num:1,v:r=>r.z,f:r=>sg(r.z),tip:'Judge-adjusted: 0 = that judge\'s average, +1 = one standard deviation above'},
   {k:'an',h:'Adj. Rounds',num:1,v:r=>r.an,tip:'Ballots from judges with enough other ballots to adjust against'}];
  const el=grid(cols,list,S.sortC,s=>{S.sortC=s;table()});
  const o=$('out');o.innerHTML=`<div class="note" style="margin-bottom:8px">${list.length.toLocaleString()} debaters${q?'':` with at least ${S.minC} scored rounds in view`}. Click a name for the full breakdown, a column to sort.</div>`;o.appendChild(el);
}

// ---- judge aggregation
function debates(rows){ // group one judge's ballots into rooms -> [{t,round,aff:[rows],neg:[rows]}]
  const m=new Map();for(const r of rows){const k=r[0]+'|'+r[1]+'|'+r[5];(m.get(k)||m.set(k,[]).get(k)).push(r)}
  return [...m.values()].map(g=>{
    let aff=g.filter(r=>r[6]===1),neg=g.filter(r=>r[6]===2),unk=false;const rest=g.filter(r=>r[6]===0);
    if(rest.length){ // side not recorded on the sheet: split into teams, fill whichever column is free
      const tm=new Map();for(const r of rest){const k=Math.min(r[2],r[3]<0?r[2]:r[3])+'-'+Math.max(r[2],r[3]);(tm.get(k)||tm.set(k,[]).get(k)).push(r)}
      for(const t of tm.values()){if(!aff.length)aff=t;else if(!neg.length)neg=t}unk=true}
    return {t:g[0][0],round:g[0][1],j:g[0][5],aff,neg,all:g,unk}});
}
function jStats(rows,decs){
  const p=rows.map(r=>r[8]),oth=[];for(const r of rows){const o=others(r);if(o!=null)oth.push(r[8]-o)}
  const db=debates(rows);let lp=0,lpn=0;
  for(const d of db){if(d.aff.length&&d.neg.length&&d.aff.length===d.neg.length&&d.aff[0][7]>=0&&d.neg[0][7]>=0&&d.aff[0][7]!==d.neg[0][7]){
    const a=d.aff.reduce((x,r)=>x+r[8],0),n=d.neg.reduce((x,r)=>x+r[8],0),aw=d.aff[0][7]===1;lpn++;if(aw?a<n:n<a)lp++}}
  const w=mean(rows.filter(r=>r[7]===1).map(r=>r[8])),l=mean(rows.filter(r=>r[7]===0).map(r=>r[8]));
  const aw=decs.filter(d=>d[3]===1).length;
  return {n:rows.length,rooms:db.length,avg:mean(p),med:median(p),sd:sd(p),lo:p.length?Math.min(...p):null,hi:p.length?Math.max(...p):null,
    gap:w!=null&&l!=null?w-l:null,lp:lpn?lp/lpn:null,lpn,oth:mean(oth),dn:decs.length,aff:decs.length?aw/decs.length:null,neg:decs.length?1-aw/decs.length:null,aw};
}
function judgeTable(){
  const by=new Map(),dby=new Map();
  for(const r of R){if(r[5]<0||!inScope(r[0]))continue;(by.get(r[5])||by.set(r[5],[]).get(r[5])).push(r)}
  for(const d of DEC){if(!inScope(d[0]))continue;(dby.get(d[2])||dby.set(d[2],[]).get(d[2])).push(d)}
  const q=norm(S.qJ.trim());let list=[];
  for(const j of new Set([...by.keys(),...dby.keys()])){const rows=by.get(j)||[];if(q&&!norm(JUD[j][0]).includes(q))continue;
    const s=jStats(rows,dby.get(j)||[]);if(!q&&s.rooms<S.minJ)continue;s.j=j;s.name=JUD[j][0];s.aff_=JUD[j][1];list.push(s)}
  const cols=[
   {k:'name',h:'Judge',v:r=>r.name,f:r=>linkJ(r.j)},{k:'aff_',h:'Affiliation',v:r=>r.aff_||null,f:r=>esc(r.aff_)},
   {k:'rooms',h:'Rounds',num:1,v:r=>r.rooms,tip:'Debates this judge scored'},{k:'n',h:'Ballots',num:1,v:r=>r.n,tip:'Individual speaker scores given (normally four per round)'},
   {k:'avg',h:'Mean',num:1,v:r=>r.avg,f:r=>f(r.avg)},{k:'med',h:'Median',num:1,v:r=>r.med,f:r=>f(r.med,1)},{k:'sd',h:'Std Dev',num:1,v:r=>r.sd,f:r=>f(r.sd)},
   {k:'lo',h:'Min',num:1,v:r=>r.lo,f:r=>f(r.lo,1)},{k:'hi',h:'Max',num:1,v:r=>r.hi,f:r=>f(r.hi,1)},
   {k:'oth',h:'Vs Others',num:1,v:r=>r.oth,f:r=>sg(r.oth),tip:'This judge\'s points minus what the same debaters average from their other judges. + generous, − strict'},
   {k:'gap',h:'W–L Gap',num:1,v:r=>r.gap,f:r=>f(r.gap),tip:'Average points to winners minus losers'},
   {k:'lp',h:'Low-Pt Win',num:1,v:r=>r.lp,f:r=>r.lp==null?'–':Math.round(100*r.lp)+'%',tip:'Share of rooms where the winning team got fewer total points'},
   {k:'dn',h:'Decisions',num:1,v:r=>r.dn},{k:'aff',h:'Aff %',num:1,v:r=>r.aff,f:r=>r.aff==null?'–':Math.round(100*r.aff)+'%'},
   {k:'neg',h:'Neg %',num:1,v:r=>r.neg,f:r=>r.neg==null?'–':Math.round(100*r.neg)+'%'}];
  const el=grid(cols,list,S.sortJ,s=>{S.sortJ=s;table()});
  const o=$('out');o.innerHTML=`<div class="note" style="margin-bottom:8px">${list.length.toLocaleString()} judges${q?'':` with at least ${S.minJ} scored round${S.minJ===1?'':'s'} in view`}. Sort by <b>Vs Others</b> to see who is generous and who is strict.</div>`;o.appendChild(el);
}
function table(){S.tab==='c'?competitorTable():judgeTable()}
function toTable(){if(location.hash.length>1){history.replaceState(null,'',location.pathname+location.search);}table()}

// ---- detail views
const stat=(v,l)=>`<div class="stat"><b>${v}</b><span>${esc(l)}</span></div>`;
const wl=w=>w===1?'<span class="W">W</span>':w===0?'<span class="L">L</span>':'<span class="muted">–</span>';
const side=s=>s===1?'Aff':s===2?'Neg':'';
function simpleTable(head,rows){return `<div class="tbl"><table><thead><tr>${head.map(h=>`<th class="${h[1]?'n':''}">${esc(h[0])}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map((c,i)=>`<td class="${head[i][1]?'n':''}">${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`}
function scopeNote(){const p=[];if(S.seasons.size)p.push([...S.seasons].sort().map(i=>SEASONS[i]).join(', '));if(S.tourn!=='')p.push(T[+S.tourn][0]);return p.length?`Showing ${esc(p.join(' · '))} only.`:'All seasons.'}

function competitorDetail(d){
  const all=R.filter(r=>r[2]===d),rows=all.filter(r=>inScope(r[0])).sort((a,b)=>tOrder(a[0])-tOrder(b[0])||a[1].localeCompare(b[1]));
  const s=cStats(rows);
  const sch=[...new Set(rows.map(r=>SCH[r[4]]))].join(', ');
  let h=`<button class="btn back" id="back">← Leaderboard</button><h2>${esc(DEB[d])}</h2><div class="muted">${esc(sch)} · ${scopeNote()}</div>`;
  if(!rows.length){$('out').innerHTML=h+'<p class="muted">No scored rounds in this view.</p>';$('back').onclick=()=>{location.hash=''};return}
  h+=`<div class="stats">${stat(s.n,'Scored rounds')}${stat(f(s.avg),'Raw average')}${stat(f(s.med,1),'Median')}${stat(f(s.sd),'Std dev')}${stat(f(s.hi,1)+' / '+f(s.lo,1),'High / low')}
   ${stat(f(s.w)+' / '+f(s.l),'Avg in wins / losses')}${stat(f(s.aa),'Adjusted average')}${stat(sg(s.adj),'Vs judge (avg)')}${stat(sg(s.z),'Judge-adjusted Z')}${stat(s.an,'Rounds adjusted')}</div>`;
  const grp=(keyf)=>{const m=new Map();for(const r of rows){const k=keyf(r);(m.get(k)||m.set(k,[]).get(k)).push(r)}return m};
  h+='<h3>By season</h3>'+simpleTable([['Season'],['Rounds',1],['Raw Avg',1],['Adj Avg',1],['Median',1],['High',1],['Low',1],['Vs Judge',1],['Z-Score',1]],
    [...grp(r=>T[r[0]][1])].sort((a,b)=>a[0]-b[0]).map(([k,g])=>{const x=cStats(g);return [esc(SEASONS[k]),x.n,f(x.avg),f(x.aa),f(x.med,1),f(x.hi,1),f(x.lo,1),sg(x.adj),sg(x.z)]}));
  h+='<h3>By tournament</h3>'+simpleTable([['Tournament'],['Partner'],['Record'],['Rounds',1],['Raw Avg',1],['Adj Avg',1],['High',1],['Low',1],['Vs Judge',1],['Z-Score',1]],
    [...grp(r=>r[0])].map(([k,g])=>{const x=cStats(g);return [esc(T[k][0]),[...new Set(g.map(r=>r[3]))].map(linkC).join(', '),`${x.rec[0]}-${x.rec[1]}`,x.n,f(x.avg),f(x.aa),f(x.hi,1),f(x.lo,1),sg(x.adj),sg(x.z)]}));
  const bj=[...grp(r=>r[5])].filter(([k])=>k>=0).map(([k,g])=>{const p=g.map(r=>r[8]),b=base(g[0]);return [k,g.length,mean(p),b?b.mu:null,b?mean(p)-b.mu:null]}).sort((a,b)=>b[1]-a[1]);
  h+='<h3>By judge</h3>'+simpleTable([['Judge'],['Rounds',1],['Avg given to this debater',1],['Judge avg to everyone else',1],['Difference',1]],
    bj.map(x=>[linkJ(x[0]),x[1],f(x[2]),f(x[3]),sg(x[4])]));
  h+='<h3>Round by round</h3>'+simpleTable([['Tournament'],['Rd'],['Partner'],['Side'],['Result'],['Judge'],['Points',1],['Rank',1],['Judge Avg',1],['Vs Judge',1],['Z',1]],
    rows.map(r=>{const b=base(r);return [esc(T[r[0]][0]),esc(r[1]),linkC(r[3]),side(r[6]),wl(r[7]),linkJ(r[5]),f(r[8],1),r[9]||'',b?f(b.mu):'–',b?sg(r[8]-b.mu):'–',b?sg((r[8]-b.mu)/b.sd):'–']}));
  if(all.length!==rows.length)h+=`<p class="note">${all.length-rows.length} more scored rounds are outside the current season/tournament filter.</p>`;
  $('out').innerHTML=h;$('back').onclick=()=>{location.hash=''};wire($('out'));
}

const BINS=[[0,26,'< 26'],[26,27,'26 – 27'],[27,28,'27 – 28'],[28,28.5,'28 – 28.5'],[28.5,29,'28.5 – 29'],[29,29.5,'29 – 29.5'],[29.5,31,'29.5 – 30']];
function judgeDetail(j){
  const rows=R.filter(r=>r[5]===j&&inScope(r[0])),decs=DEC.filter(d=>d[2]===j&&inScope(d[0]));
  const s=jStats(rows,decs);
  let h=`<button class="btn back" id="back">← Leaderboard</button><h2>${esc(JUD[j][0])}</h2><div class="muted">${esc(JUD[j][1]||'')}${JUD[j][1]?' · ':''}${scopeNote()}</div>`;
  h+=`<div class="stats">${stat(s.rooms,'Rounds with points')}${stat(s.n,'Speaker ballots')}${stat(f(s.avg),'Mean')}${stat(f(s.med,1),'Median')}${stat(f(s.sd),'Std dev')}${stat(f(s.lo,1)+' / '+f(s.hi,1),'Min / max')}
   ${stat(sg(s.oth),'Vs other judges')}${stat(f(s.gap),'Win–loss gap')}${stat(s.lp==null?'–':Math.round(100*s.lp)+'%','Low-point wins')}</div>`;
  h+='<h3>Decisions by side</h3>';
  if(s.dn){const pre=decs.filter(d=>!d[4]),el=decs.filter(d=>d[4]),a=x=>x.filter(d=>d[3]===1).length;
    h+=`<div class="split" role="img" aria-label="Aff ${Math.round(100*s.aff)} percent, Neg ${Math.round(100*s.neg)} percent"><i class="a" style="width:${100*s.aff}%"></i><i class="b" style="width:${100*s.neg}%"></i></div>
    <p><b>Aff ${pct(s.aw,s.dn)}</b> (${s.aw}) · <b>Neg ${pct(s.dn-s.aw,s.dn)}</b> (${s.dn-s.aw}) · ${s.dn} decisions</p>
    <p class="note">Prelims: Aff ${a(pre)} – Neg ${pre.length-a(pre)}${pre.length?` (${pct(a(pre),pre.length)} Aff)`:''} · Elims: Aff ${a(el)} – Neg ${el.length-a(el)}${el.length?` (${pct(a(el),el.length)} Aff)`:''}</p>`;
  }else h+='<p class="muted">No decisions in this view.</p>';
  if(rows.length){
    const p=rows.map(r=>r[8]),cnt=BINS.map(b=>p.filter(x=>x>=b[0]&&x<b[1]).length),mx=Math.max(...cnt,1);
    h+='<h3>Point distribution</h3><div class="bars">'+BINS.map((b,i)=>`<div>${b[2]}</div><div><div class="bar" style="width:${100*cnt[i]/mx}%"></div></div><div class="muted">${cnt[i]} (${pct(cnt[i],p.length)})</div>`).join('')+'</div>';
  }
  const seas=new Map();for(const r of rows){const k=T[r[0]][1];(seas.get(k)||seas.set(k,{r:[],d:[]}).get(k)).r.push(r)}
  for(const d of decs){const k=T[d[0]][1];(seas.get(k)||seas.set(k,{r:[],d:[]}).get(k)).d.push(d)}
  let prev=null;
  h+='<h3>Season by season</h3>'+simpleTable([['Season'],['Ballots',1],['Mean',1],['Change',1],['Median',1],['Std Dev',1],['Vs Others',1],['Decisions',1],['Aff %',1],['Neg %',1]],
    [...seas].sort((a,b)=>a[0]-b[0]).map(([k,g])=>{const x=jStats(g.r,g.d),ch=prev!=null&&x.avg!=null?x.avg-prev:null;if(x.avg!=null)prev=x.avg;
      return [esc(SEASONS[k]),x.n,f(x.avg),sg(ch),f(x.med,1),f(x.sd),sg(x.oth),x.dn,x.aff==null?'–':Math.round(100*x.aff)+'%',x.neg==null?'–':Math.round(100*x.neg)+'%']}));
  const team=g=>g.length?g.map(r=>`${linkC(r[2])} <b>${f(r[8],1)}</b>`).join(', ')+(g[0][7]>=0?' '+wl(g[0][7]):''):'<span class="muted">–</span>';
  const db=debates(rows).sort((a,b)=>tOrder(b.t)-tOrder(a.t)||a.round.localeCompare(b.round));
  if(db.length)h+='<h3>Round log</h3>'+simpleTable([['Tournament'],['Rd'],['Aff'],['Neg'],['Note']],db.map(d=>{
    const a=d.aff.reduce((x,r)=>x+r[8],0),n=d.neg.reduce((x,r)=>x+r[8],0);
    const low=d.aff.length&&d.neg.length&&d.aff.length===d.neg.length&&d.aff[0][7]>=0&&d.aff[0][7]!==d.neg[0][7]&&((d.aff[0][7]===1)?a<n:n<a);
    return [esc(T[d.t][0]),esc(d.round),team(d.aff),team(d.neg),(low?'<span class="tag">low-point win</span> ':'')+(d.unk?'<span class="tag">sides not recorded</span>':'')]}));
  $('out').innerHTML=h;$('back').onclick=()=>{location.hash=''};wire($('out'));
}

// ---- coverage
(function(){
  const st=['Included','No speaker points in export','Source file not available','Awaiting OCR'];
  const rows=T.map(t=>[esc(SEASONS[t[1]]),esc(t[0]),esc(t[3]),st[t[5]],t[6]||'',t[6]?(t[4]?'yes':'no'):'',t[7]||'']);
  const why=new Map(D.missing.map(m=>[m[1],m[3]]));
  $('covBody').innerHTML=`<p class="note">${D.meta.tournaments_with_speaks} of ${D.meta.tournaments_total} tournaments have speaker points. Nothing is estimated or filled in: a tournament without published points simply contributes none. Decisions (for Aff/Neg percentages) can exist even where points do not.</p>`+
   simpleTable([['Season'],['Tournament'],['Platform'],['Status'],['Speaker ballots',1],['Judges named'],['Decisions',1],['Note']],rows.map((r,i)=>r.concat([esc(why.get(T[i][0])||'')])));
})();

// ---- routing
function render(){
  document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('on',b.dataset.tab===S.tab));
  const m=/^#([cj])=(.*)$/.exec(location.hash);
  if(m){const name=decodeURIComponent(m[2]),kind=m[1],i=kind==='c'?DEB.indexOf(name):JUD.findIndex(j=>j[0]===name);
    if(i>=0){S.tab=kind;document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('on',b.dataset.tab===S.tab));filters();kind==='c'?competitorDetail(i):judgeDetail(i);window.scrollTo(0,0);return}}
  filters();table();
}
window.addEventListener('hashchange',render);
render();
}
})();
