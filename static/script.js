// Cornerstone setup
cornerstoneWADOImageLoader.external.cornerstone = cornerstone;
cornerstoneWADOImageLoader.external.dicomParser = dicomParser;
cornerstoneWADOImageLoader.configure({ useWebWorkers: false });

const els = {
  orig: document.getElementById('viewer-original'),
  proc: document.getElementById('viewer-processed'),
  metaOrig: document.getElementById('metadata-original'),
  metaProc: document.getElementById('metadata-processed'),
  input: document.getElementById('fileInput'),
  uploadBtn: document.getElementById('uploadBtn'),
  tableBody: document.getElementById('resultsBody'),
  toast: document.getElementById('snackbar')
};

cornerstone.enable(els.orig);
cornerstone.enable(els.proc);

// Utils
function toast(msg, err=false){
  els.toast.textContent = msg;
  els.toast.className = 'snackbar show' + (err?' error':'');
  setTimeout(()=> els.toast.className = 'snackbar', 2500);
}

function fit(id){ const vp = cornerstone.getViewport(id); cornerstone.fitToWindow(id); cornerstone.setViewport(id, vp); }
function zoom(id, delta){
  const vp = cornerstone.getViewport(id);
  vp.scale = Math.max(0.1, vp.scale + delta);
  cornerstone.setViewport(id, vp);
}
function reset(id){ cornerstone.reset(id); }

document.addEventListener('click', (e)=>{
  const btn = e.target.closest('button[data-target]');
  if(!btn) return;
  const target = document.getElementById(btn.dataset.target);
  const action = btn.dataset.action;
  if(action==='zoom-in') return zoom(target, 0.15);
  if(action==='zoom-out') return zoom(target, -0.15);
  if(action==='fit') return fit(target);
  if(action==='reset') return reset(target);
});

function fillMetadata(ds, panel){
  panel.innerHTML = '';
  for(const tag in ds.elements){
    try{
      let val = '[Binary/Empty]';
      try { val = ds.string(tag) || val; } catch(_){}
      const row = document.createElement('div');
      row.innerHTML = `<strong>${tag}:</strong> ${val}`;
      panel.appendChild(row);
    }catch(_){}
  }
}

// Load local file preview (original)
els.input.addEventListener('change', async (e)=>{
  const file = e.target.files?.[0];
  if(!file) return;
  if(!file.name.toLowerCase().endsWith('.dcm')){ toast('Select a .dcm file', true); return; }

  const id = cornerstoneWADOImageLoader.wadouri.fileManager.add(file);
  const img = await cornerstone.loadAndCacheImage(id);
  cornerstone.displayImage(els.orig, img);
  fit(els.orig);

  // Metadata from the file
  const arrayBuf = await file.arrayBuffer();
  const ds = dicomParser.parseDicom(new Uint8Array(arrayBuf));
  fillMetadata(ds, els.metaOrig);
});

els.uploadBtn.addEventListener('click', async ()=>{
  const file = els.input.files?.[0];
  if(!file){ toast('Choose a .dcm first', true); return; }
  if(!file.name.toLowerCase().endsWith('.dcm')){ toast('Select a .dcm file', true); return; }
  toast('Uploading…');

  const fd = new FormData();
  fd.append('dicom_file', file);

  try{
    const r = await fetch('/upload_dicom', { method:'POST', body: fd });
    const data = await r.json();
    if(!r.ok || data.error){ throw new Error(data.error || `HTTP ${r.status}`); }

    // Row
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${file.name}</td>
      <td>${data.message || 'Processed'}</td>
      <td><a href="${data.download_url}" download>Download</a></td>
      <td><button class="view-btn">View</button></td>
    `;
    const viewBtn = tr.querySelector('.view-btn');
    viewBtn.addEventListener('click', ()=> loadProcessed(data.processed_url));
    els.tableBody.appendChild(tr);

    // Auto-load processed preview
    loadProcessed(data.processed_url);
    els.input.value = '';
    toast('Done');
  }catch(err){
    console.error(err);
    toast(`Failed: ${err.message}`, true);
  }
});

async function loadProcessed(absUrl){
  const u = new URL(absUrl);
  const path = u.pathname;
  const cb = `cb=${Date.now()}`;

  // Cornerstone: add cache-buster to the wadouri URL
  const imageId = `wadouri:${window.location.origin}${path}?${cb}`;
  const img = await cornerstone.loadAndCacheImage(imageId);
  cornerstone.displayImage(els.proc, img);
  fit(els.proc);

  // Metadata: also fetch with cache-buster
  const buf = await (await fetch(`${path}?${cb}`, { cache: 'no-store' })).arrayBuffer();
  const ds = dicomParser.parseDicom(new Uint8Array(buf));
  fillMetadata(ds, els.metaProc);
}