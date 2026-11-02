// Head-to-Head + ELO pages. Data: data/elo.json, built by tools/elo/build.py.
(function(){
fetch('data/elo.json').then(r=>{if(!r.ok)throw new Error(r.status);return r.json()}).then(DATA=>{
const PAGE=document.body.dataset.page;

const M=DATA.m; // [season,tourn,round,type,aNames,aSchool,bNames,bSchool,sideA,winner,ballots,judges,status,note,torder,rorder,aPid,bPid]
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const COUNT={CONFIRMED:1,INFERRED:1};
const seasons=[...new Set(M.map(r=>r[0]))].sort();
$('sub').textContent=`${M.length.toLocaleString()} debates/meetings · ${seasons[0]} to ${seasons[seasons.length-1]} · byes excluded`;
const c=DATA.cfg;$('cfg').textContent=`ELO: start ${c.start}, K ${c.k} (elims ${c.kelim}), ballot weighting ${c.ballot_weight?'on':'off'}. Season ratings carry over with regression to the mean: start = ${c.start} + ${c.carry} × (last season's end − ${c.start}); a partnership starts each season at its debaters' average. Only CONFIRMED and INFERRED debates count; walkovers, byes, forfeits and unknown results do not.`;
$('dark').onclick=()=>{const d=document.documentElement.classList.toggle('dark');try{localStorage.setItem('npte-theme',d?'dark':'light')}catch(e){}};
// name lists
const debaters=new Set(),pships=new Set();
M.forEach(r=>{r[4].forEach(n=>debaters.add(n));r[6].forEach(n=>debaters.add(n));if(r[4].length)pships.add(r[16]);if(r[6].length)pships.add(r[17])});
function fillDL(){const set=$('mode').value==='d'?debaters:pships;$('dl').innerHTML=[...set].sort().map(n=>`<option value="${esc(n)}">`).join('')}
['hs','ls'].forEach(id=>{$(id).innerHTML=(id==='ls'?'<option value="all-time">All-time (continuous)</option>':'<option value="">All seasons</option>')+seasons.slice().reverse().map(s=>`<option>${s}</option>`).join('')});
$('ls').value=seasons[seasons.length-1];
const norm=s=>s.toLowerCase().normalize('NFKD').replace(/[^a-z& ]/g,'').replace(/\s+/g,' ').trim();
function sideOf(r,q,mode){ // returns 'a','b' or null
 if(mode==='d'){const qn=norm(q);if(r[4].some(n=>norm(n)===qn))return 'a';if(r[6].some(n=>norm(n)===qn))return 'b';return null}
 const qn=norm(q);if(norm(r[16])===qn)return 'a';if(norm(r[17])===qn)return 'b';
 const parts=qn.split('&').map(x=>x.trim()).filter(Boolean).sort().join('&');
 const pk=a=>a.map(norm).sort().join('&');if(pk(r[4])===parts)return 'a';if(pk(r[6])===parts)return 'b';return null}
function renderH2H(){
 const mode=$('mode').value,A=$('qa').value.trim(),B=$('qb').value.trim(),S=$('hs').value;
 if(!A){$('h2hOut').innerHTML='<span class="muted">Pick a debater or partnership.</span>';return}
 const rows=[];
 for(const r of M){if(S&&r[0]!==S)continue;const sa=sideOf(r,A,mode);if(!sa)continue;
  if(B){const sb=sideOf(r,B,mode);if(!sb||sb===sa)continue}rows.push([r,sa])}
 let w=0,l=0,other=0;rows.forEach(([r,s])=>{if(COUNT[r[12]]&&r[9]){r[9]===s?w++:l++}else other++});
 const opp=(r,s)=>s==='a'?[r[6],r[7],r[17]]:[r[4],r[5],r[16]], me=(r,s)=>s==='a'?[r[4],r[5]]:[r[6],r[7]];
 let h=`<div class="row" style="justify-content:space-between"><div><div class="big">${esc(A)}${B?' <span class="muted">vs</span> '+esc(B):''}</div>
 <div class="muted">${rows.length} meeting(s)${S?' in '+S:''}</div></div><div class="big"><span class="W">${w}</span> – <span class="L">${l}</span>${other?` <span class="tag">${other} not counted (walkover / unknown / forfeit)</span>`:''}</div></div>`;
 if(!rows.length){h+='<p class="muted">No meetings found. Check spelling (use the suggestions) or switch Debater/Partnership.</p>'}
 else{h+=`<div class="scroll" style="margin-top:12px"><table><thead><tr><th>Season</th><th>Tournament</th><th>Round</th>${mode==='d'?'<th>Partner / team</th>':''}<th>Opponent</th><th>Side</th><th>Result</th><th>Ballots</th><th>Judges</th><th>Status</th></tr></thead><tbody>`;
  rows.sort((x,y)=>y[0][14]-x[0][14]||y[0][15]-x[0][15]);
  for(const [r,s] of rows){const o=opp(r,s),m=me(r,s);const side=r[8]?(s==='a'?r[8]:(r[8]==='Aff'?'Neg':'Aff')):'—';
   const res=r[9]?(r[9]===s?'W':'L'):'?';const counted=COUNT[r[12]];
   h+=`<tr><td>${r[0]}</td><td>${esc(r[1])}</td><td>${r[2]}</td>${mode==='d'?`<td>${esc(m[0].join(' & '))}<div class="muted">${esc(m[1])}</div></td>`:''}
   <td><span class="clickable" data-p="${esc(o[2])}">${esc(o[0].join(' & ')||o[2])}</span><div class="muted">${esc(o[1])}</div></td><td>${side}</td>
   <td class="${counted?res:''}">${res}${counted?'':' <span class="tag">not a debate</span>'}</td><td>${esc(r[10])}</td><td>${esc(r[11])}</td>
   <td><span class="tag" title="${esc(r[13])}">${r[12]}</span></td></tr>`}
  h+='</tbody></table></div>'}
 $('h2hOut').innerHTML=h;
 $('h2hOut').querySelectorAll('[data-p]').forEach(e=>e.onclick=()=>{$('mode').value='p';fillDL();$('qb').value=e.dataset.p;if(mode==='d'){const r=rows[0];}renderH2H()});
}
['qa','qb','hs'].forEach(id=>$(id).addEventListener('input',renderH2H));
$('mode').onchange=()=>{fillDL();renderH2H()};$('swap').onclick=()=>{const t=$('qa').value;$('qa').value=$('qb').value;$('qb').value=t;renderH2H()};
let lbSort=[2,-1];
function renderLB(){const S=$('ls').value,T=$('lt').value,min=+$('lmin').value||0,f=norm($('lf').value||'');
 let L=S==='all-time'?(T==='p'?DATA.ap:DATA.ad):((T==='p'?DATA.bp:DATA.bd)[S]||[]);
 L=L.filter(x=>(f?true:x[4]>=min)&&(!f||norm(x[0]+' '+x[1]).includes(f)));
 const [k,dir]=lbSort;L=L.slice().sort((a,b)=>(a[k]>b[k]?1:a[k]<b[k]?-1:0)*dir);
 const hd=['#',T==='p'?'Partnership':'Debater','School(s)','Rating','Peak','Debates','W','L'];
 let h='<thead><tr>'+hd.map((x,i)=>`<th data-k="${i-1}">${x}</th>`).join('')+'</tr></thead><tbody>';
 L.forEach((x,i)=>{h+=`<tr class="${i<4&&lbSort[0]===2&&dir<0?'top':''}"><td>${i+1}</td><td><span class="clickable" data-n="${esc(x[0])}">${esc(x[0])}</span></td><td class="muted">${esc(x[1])}</td><td><b>${x[2].toFixed(1)}</b></td><td>${x[3].toFixed(1)}</td><td>${x[4]}</td><td class="W">${x[5]}</td><td class="L">${x[6]}</td></tr>`});
 $('lb').innerHTML=h+'</tbody>';
 $('lb').querySelectorAll('th').forEach(th=>th.onclick=()=>{const k=+th.dataset.k;if(k<0)return;lbSort=[k,lbSort[0]===k?-lbSort[1]:(k<=1?1:-1)];renderLB()});
 $('lb').querySelectorAll('[data-n]').forEach(e=>e.onclick=()=>{location.href='h2h.html?'+new URLSearchParams({mode:T,a:e.dataset.n,s:S==='all-time'?'':S})});
}
['ls','lt','lmin','lf'].forEach(id=>$(id).addEventListener('input',renderLB));

const q=new URLSearchParams(location.search);
if(q.get('mode'))$('mode').value=q.get('mode')==='p'?'p':'d';
fillDL();
if(q.get('a'))$('qa').value=q.get('a');if(q.get('b'))$('qb').value=q.get('b');if(q.has('s'))$('hs').value=q.get('s');
if(PAGE==='elo')renderLB();else renderH2H();
}).catch(e=>{document.getElementById(document.body.dataset.page==='elo'?'lb':'h2hOut').innerHTML='<tr><td>Could not load data/elo.json ('+e.message+').</td></tr>'});
})();
