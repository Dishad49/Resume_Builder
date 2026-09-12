const $ = s => document.querySelector(s);
let results = [];
const files = () => { const f = $('#resumes').files; $('#fileStatus').textContent = f.length ? `${f.length} resume${f.length === 1 ? '' : 's'} ready to analyze` : ''; };
$('#resumes').addEventListener('change', files);

function tags(items, missing = false) { return items.length ? items.slice(0, 6).map(x => `<span class="tag ${missing ? 'missing' : ''}">${x}</span>`).join('') : '<span class="muted">No explicit evidence found</span>'; }
function show(data) {
  results = data.results;
  $('#results').hidden = false;
  $('#results').scrollIntoView({behavior:'smooth', block:'start'});
  $('#top3').innerHTML = results.slice(0,3).map((r,i) => `<article class="winner"><div class="rank-badge">0${i+1}</div><div><h3>${r.name}</h3><div class="score">${r.score}<small>/100</small></div></div><p><strong>Why they rank here</strong>${tags(r.matched)}<strong>Missing / weaker evidence</strong>${tags(r.missing,true)}</p></article>`).join('');
  const audit = $('#audit'); audit.hidden = !data.audit?.length; audit.innerHTML = data.audit?.length ? `<strong>JD wording review</strong><span>${data.audit.join(' ')}</span>` : '';
  $('#ranking').innerHTML = results.map(r => `<tr><td><span class="rank-num">${r.rank}</span></td><td><strong>${r.name}</strong></td><td><strong class="fit">${r.score}</strong><small>/100</small></td><td><div class="bar"><i style="width:${r.semantic}%"></i><b style="width:${r.keyword}%"></b></div><small>Semantic ${r.semantic} · Keyword ${r.keyword}</small></td><td>${tags(r.matched)}</td></tr>`).join('');
  const options = results.map((r,i) => `<option value="${i}">${r.name}</option>`).join('');
  $('#candidateA').innerHTML = options; $('#candidateB').innerHTML = options; if(results[1]) $('#candidateB').value = 1;
}
async function fetchRank(form) { const res = await fetch('/api/rank', {method:'POST',body:form}); const data = await res.json(); if(!res.ok) throw Error(data.error); return data; }
$('#rank').addEventListener('click', async () => { $('#error').textContent=''; const button=$('#rank'); button.disabled=true; button.textContent='Analyzing applications…'; try { const form=new FormData(); form.append('jd',$('#jd').value); if($('#jdPdf').files[0]) form.append('jd_pdf',$('#jdPdf').files[0]); [...$('#resumes').files].forEach(f=>form.append('resumes',f)); show(await fetchRank(form)); } catch(e) { $('#error').textContent=e.message; } finally { button.disabled=false; button.innerHTML='Rank candidates <span>→</span>'; } });
$('#sample').addEventListener('click', async () => { const d=await (await fetch('/api/sample',{method:'POST'})).json(); $('#jd').value=d.jd; $('#fileStatus').textContent='Demo candidates loaded'; show(d); });
$('#compareBtn').addEventListener('click', async () => { const data=await (await fetch('/api/compare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({a:results[$('#candidateA').value],b:results[$('#candidateB').value]})})).json(); $('#comparison').textContent=data.message; });
