const $ = s => document.querySelector(s);
let results = [];
let selectedResumes = [];
const MAX_RESUMES = 25;
const escapeHTML = value => String(value).replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
const formatBytes = bytes => bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
const sameFile = (a, b) => a.name === b.name && a.size === b.size && a.lastModified === b.lastModified;
function renderResumeList() {
  $('#fileStatus').textContent = selectedResumes.length ? `${selectedResumes.length} of ${MAX_RESUMES} resumes ready to analyze` : 'No resumes selected yet.';
  $('#resumeList').innerHTML = selectedResumes.map((file, index) => `<li><span title="${escapeHTML(file.name)}">${escapeHTML(file.name)}</span><small>${formatBytes(file.size)}</small><button type="button" class="remove-file" data-index="${index}" aria-label="Remove ${escapeHTML(file.name)}">Remove</button></li>`).join('');
}
$('#resumes').addEventListener('change', event => {
  const newFiles = [...event.target.files].filter(file => !selectedResumes.some(existing => sameFile(existing, file)));
  const slots = MAX_RESUMES - selectedResumes.length;
  selectedResumes.push(...newFiles.slice(0, Math.max(slots, 0)));
  event.target.value = '';
  $('#error').textContent = newFiles.length > slots ? `You can rank up to ${MAX_RESUMES} resumes. Remove a file before adding more.` : '';
  renderResumeList();
});
$('#resumeList').addEventListener('click', event => {
  const button = event.target.closest('.remove-file');
  if (!button) return;
  selectedResumes.splice(Number(button.dataset.index), 1);
  $('#error').textContent = '';
  renderResumeList();
});

function tags(items, missing = false) { return items.length ? items.slice(0, 6).map(x => `<span class="tag ${missing ? 'missing' : ''}">${x}</span>`).join('') : '<span class="muted">No explicit evidence found</span>'; }
function show(data) {
  results = data.results;
  $('#results').hidden = false;
  $('#results').scrollIntoView({behavior:'smooth', block:'start'});
  const average = results.reduce((total, candidate) => total + candidate.score, 0) / results.length;
  const matchedConcepts = new Set(results.flatMap(candidate => candidate.matched)).size;
  $('#summary').innerHTML = `<span><strong>${results.length}</strong> candidates ranked</span><span><strong>${average.toFixed(1)}</strong> average fit</span><span><strong>${matchedConcepts}</strong> JD concepts evidenced</span>`;
  $('#top3').innerHTML = results.slice(0,3).map((r,i) => `<article class="winner"><div class="rank-badge">0${i+1}</div><div><h3>${escapeHTML(r.name)}</h3><div class="score">${r.score}<small>/100</small></div></div><p><strong>Why they rank here</strong>${tags(r.matched)}<strong>Missing / weaker evidence</strong>${tags(r.missing,true)}</p></article>`).join('');
  const audit = $('#audit'); audit.hidden = !data.audit?.length; audit.innerHTML = data.audit?.length ? `<strong>JD wording review</strong><span>${data.audit.join(' ')}</span>` : '';
  $('#ranking').innerHTML = results.map(r => `<tr><td><span class="rank-num">${r.rank}</span></td><td><strong>${escapeHTML(r.name)}</strong></td><td><strong class="fit">${r.score}</strong><small>/100</small></td><td><div class="bar"><i style="width:${r.semantic}%"></i><b style="width:${r.keyword}%"></b></div><small>Semantic ${r.semantic} · Keyword ${r.keyword}</small></td><td>${tags(r.matched)}</td></tr>`).join('');
  const options = results.map((r,i) => `<option value="${i}">${escapeHTML(r.name)}</option>`).join('');
  $('#candidateA').innerHTML = options; $('#candidateB').innerHTML = options; if(results[1]) $('#candidateB').value = 1;
}
async function fetchRank(form) { const res = await fetch('/api/rank', {method:'POST',body:form}); const data = await res.json(); if(!res.ok) throw Error(data.error); return data; }
$('#rank').addEventListener('click', async () => { $('#error').textContent=''; const button=$('#rank'); button.disabled=true; button.textContent='Analyzing applications…'; try { const form=new FormData(); form.append('jd',$('#jd').value); if($('#jdPdf').files[0]) form.append('jd_pdf',$('#jdPdf').files[0]); selectedResumes.forEach(f=>form.append('resumes',f)); show(await fetchRank(form)); } catch(e) { $('#error').textContent=e.message; } finally { button.disabled=false; button.innerHTML='Rank candidates <span>→</span>'; } });
$('#sample').addEventListener('click', async () => { const d=await (await fetch('/api/sample',{method:'POST'})).json(); $('#jd').value=d.jd; $('#fileStatus').textContent='Demo candidates loaded'; show(d); });
$('#compareBtn').addEventListener('click', async () => {
  const comparison = $('#comparison');
  comparison.textContent = 'Building comparison…';
  try {
    const response = await fetch('/api/compare', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({a:results[$('#candidateA').value], b:results[$('#candidateB').value]})});
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'Could not compare these candidates.');
    const section = (title, points) => `<section class="comparison-card"><h4>${title}</h4><ul>${points.map(point => `<li>${escapeHTML(point)}</li>`).join('')}</ul></section>`;
    comparison.innerHTML = `<p class="comparison-headline">${escapeHTML(data.headline)}</p><div class="comparison-grid">${section('Skill coverage', data.skills)}${section('Experience evidence', data.experience)}${section('Score breakdown', data.scores)}</div><p class="comparison-note">${escapeHTML(data.note)}</p>`;
  } catch (error) { comparison.textContent = error.message; }
});
$('#export').addEventListener('click', () => {
  const columns = ['Rank', 'Candidate', 'Final fit', 'Semantic score', 'Keyword score', 'Matched evidence', 'Missing evidence'];
  const quote = value => `"${String(value).replace(/"/g, '""')}"`;
  const rows = results.map(r => [r.rank, r.name, r.score, r.semantic, r.keyword, r.matched.join('; '), r.missing.join('; ')]);
  const csv = [columns, ...rows].map(row => row.map(quote).join(',')).join('\n');
  const link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob([csv], {type: 'text/csv;charset=utf-8'}));
  link.download = 'internloom-shortlist.csv';
  link.click();
  URL.revokeObjectURL(link.href);
});
