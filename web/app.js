const $ = id => document.getElementById(id);
const FIELDS = ["text","font","align","size","width","line_spacing","letter_spacing","zmin","zmax","feed","zfeed"];
let last = null, timer = null, seq = 0;

function params() {
  const p = {};
  for (const k of FIELDS) p[k] = $(k).value;
  p.zero = $("zero").checked;
  return p;
}

async function api(path, body) {
  const r = await fetch(path, body ? {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)} : undefined);
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

async function loadFonts() {
  const j = await api("/api/fonts");
  const sel = $("font");
  const grp = (label, items, prefix) => {
    if (!items.length) return;
    const g = document.createElement("optgroup"); g.label = label;
    for (const n of items) { const o = document.createElement("option"); o.value = prefix + n; o.textContent = n; g.appendChild(o); }
    sel.appendChild(g);
  };
  grp("Traço único (Hershey) — melhor p/ caneta", j.hershey, "");
  grp("Fontes do sistema (contorno)", j.system, "sys:");
  sel.value = j.default;
}

function draw(strokes, bbox) {
  const cv = $("cv"), ctx = cv.getContext("2d");
  ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, cv.width, cv.height);
  if (!strokes.length) return;
  const pad = 20;
  const [x0, y0, x1, y1] = bbox;
  const w = Math.max(x1, 1), h = Math.max(y1, 1);
  const s = Math.min((cv.width - 2*pad) / w, (cv.height - 2*pad) / h);
  const X = x => pad + x * s, Y = y => pad + (h - y) * s;
  ctx.lineJoin = ctx.lineCap = "round";
  // deslocamentos
  ctx.strokeStyle = "#c0392b"; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
  ctx.beginPath(); let px = 0, py = 0; ctx.moveTo(X(px), Y(py));
  for (const st of strokes) { ctx.lineTo(X(st[0][0]), Y(st[0][1])); ctx.moveTo(X(st[0][0]), Y(st[0][1])); const e = st[st.length-1]; ctx.moveTo(X(e[0]), Y(e[1])); px = e[0]; py = e[1]; }
  ctx.stroke();
  // linhas de escrita
  ctx.setLineDash([]); ctx.strokeStyle = "#1f5fbf"; ctx.lineWidth = Math.max(1, 0.35 * s);
  ctx.beginPath();
  for (const st of strokes) { ctx.moveTo(X(st[0][0]), Y(st[0][1])); for (let i = 1; i < st.length; i++) ctx.lineTo(X(st[i][0]), Y(st[i][1])); }
  ctx.stroke();
}

function fmtTime(s) { return s >= 60 ? `${Math.floor(s/60)} min ${s%60} s` : `${s} s`; }

async function refresh() {
  const my = ++seq;
  try {
    const j = await api("/api/generate", params());
    if (my !== seq) return;
    last = j;
    $("gcode").textContent = j.gcode;
    const st = j.stats;
    $("stats").textContent = `${st.strokes} traços · escrita ${st.draw_mm} mm · deslocamento ${st.travel_mm} mm · ~${fmtTime(st.est_seconds)} · ${st.lines} linhas · ${(st.bbox[2]-st.bbox[0]).toFixed(1)}×${(st.bbox[3]-st.bbox[1]).toFixed(1)} mm`;
    $("msgs").innerHTML = j.warnings.map(w => `<div class="warn">⚠ ${w}</div>`).join("");
    draw(j.strokes, st.bbox);
  } catch (e) {
    if (my !== seq) return;
    $("msgs").innerHTML = `<div class="err">${e.message}</div>`;
  }
}
const schedule = () => { clearTimeout(timer); timer = setTimeout(refresh, 250); };

for (const k of FIELDS) $(k).addEventListener("input", schedule);
$("zero").addEventListener("change", schedule);
$("copy").onclick = async () => { if (last) { await navigator.clipboard.writeText(last.gcode); $("copy").textContent = "Copiado!"; setTimeout(() => $("copy").textContent = "Copiar G-code", 1200); } };
$("download").onclick = () => {
  if (!last) return;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([last.gcode], {type: "text/plain"}));
  a.download = "texto.gcode"; a.click(); URL.revokeObjectURL(a.href);
};
loadFonts().then(refresh);

// ---------------- máquina (GRBL) ----------------
let seqLog = 0, poll = null, connected = false;
const mmsg = t => $("mmsg").textContent = t || "";
async function act(name, body = {}) {
  try { mmsg(""); return await api("/api/serial/" + name, body); }
  catch (e) { mmsg(e.message); }
}
async function loadPorts() {
  const j = await api("/api/serial/ports");
  const sel = $("port"); sel.innerHTML = "";
  for (const p of j.ports) { const o = document.createElement("option"); o.value = p.device; o.textContent = `${p.device} — ${p.description}`; sel.appendChild(o); }
  if (!j.ports.length) sel.innerHTML = "<option value=''>nenhuma porta serial encontrada</option>";
}
function logLine(kind, text) {
  const c = $("console"), d = document.createElement("div");
  d.className = kind; d.textContent = (kind === "tx" ? "> " : "") + text; c.appendChild(d);
  while (c.childNodes.length > 400) c.removeChild(c.firstChild);
  c.scrollTop = c.scrollHeight;
}
async function pollStatus() {
  try {
    const j = await api("/api/serial/status?since=" + seqLog);
    seqLog = j.seq;
    for (const [, k, t] of j.log) logLine(k, t);
    setConnected(j.connected);
    const st = j.status || {};
    const w = st.wpos || st.mpos;
    if (w) { $("px").textContent = w[0].toFixed(3); $("py").textContent = w[1].toFixed(3); $("pz").textContent = w[2].toFixed(3); }
    $("mstate").textContent = j.connected ? `${j.banner || "conectado"} · ${st.state || "?"}` : "desconectado";
    const p = j.progress;
    $("prog").max = Math.max(p.total, 1); $("prog").value = p.acked;
    $("progtxt").textContent = p.total ? `${p.acked}/${p.total}${p.paused ? " (pausado)" : p.running ? "" : " — fim"}${p.errors.length ? " · " + p.errors.length + " erro(s)" : ""}` : "";
  } catch (e) { /* servidor fora */ }
}
function setConnected(c) {
  connected = c;
  $("mctl").hidden = !c;
  $("connect").textContent = c ? "Desconectar" : "Conectar";
}
$("refreshPorts").onclick = loadPorts;
$("connect").onclick = async () => {
  if (connected) { await act("disconnect"); setConnected(false); return; }
  $("connect").textContent = "Conectando…";
  const r = await act("connect", {device: $("port").value});
  setConnected(!!r);
  if (!r) $("connect").textContent = "Conectar";
};
document.querySelectorAll("[data-j]").forEach(b => b.onclick = () => {
  const k = b.dataset.j, d = parseFloat($("step").value), feed = parseFloat($("jfeed").value) || 500;
  if (k === "home") return act("send", {line: "G90 G0 X0 Y0"});   // vai à origem de trabalho
  const v = {x:0, y:0, z:0}; v[k[0]] = k[1] === "+" ? d : -d;
  act("jog", {...v, feed});
});
document.querySelectorAll("[data-m]").forEach(b => b.onclick = () => {
  const k = b.dataset.m, p = params();
  if (k === "zeroxy") act("zero", {axes: "XY"});
  else if (k === "zeroz") act("zero", {axes: "Z"});
  else if (k === "penup") act("send", {line: `G90 G0 Z${p.zmax}`});
  else if (k === "pendown") act("send", {line: `G90 G1 Z${p.zmin} F${p.zfeed}`});
  else act(k);
});
$("run").onclick = async () => { if (last) { logLine("tx", "— job iniciado —"); await act("stream", {gcode: last.gcode}); } };
$("pause").onclick = () => act("pause");
$("resume").onclick = () => act("resume");
$("stop").onclick = () => act("stop");
const sendCmd = async () => { const v = $("cmd").value.trim(); if (v) { await act("send", {line: v}); $("cmd").value = ""; } };
$("sendcmd").onclick = sendCmd;
$("cmd").addEventListener("keydown", e => { if (e.key === "Enter") sendCmd(); });
loadPorts();
poll = setInterval(pollStatus, 400);

// ---------------- PDF ----------------
let pdfPages = [], pdfIdx = 0;
function showPdfPage() {
  $("text").value = pdfPages[pdfIdx] || "";
  $("pgn").textContent = pdfIdx + 1; $("pgt").textContent = pdfPages.length;
  $("pdfinfo").hidden = !pdfPages.length;
  refresh();
}
$("pdf").addEventListener("change", async e => {
  const f = e.target.files[0]; if (!f) return;
  try {
    const bytes = new Uint8Array(await f.arrayBuffer());
    let bin = ""; for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    const j = await api("/api/pdf", {data: btoa(bin)});
    pdfPages = j.pages; pdfIdx = 0;
    if (!$("width").value) $("width").value = 180;   // PDFs precisam de quebra de linha
    showPdfPage();
    if (!pdfPages.some(p => p.trim())) $("msgs").innerHTML = '<div class="warn">⚠ PDF sem texto extraível (escaneado?).</div>';
  } catch (err) { $("msgs").innerHTML = `<div class="err">${err.message}</div>`; }
  e.target.value = "";
});
$("pgprev").onclick = () => { if (pdfIdx > 0) { pdfIdx--; showPdfPage(); } };
$("pgnext").onclick = () => { if (pdfIdx < pdfPages.length - 1) { pdfIdx++; showPdfPage(); } };

// ---------------- voz / desenho (Gemini) ----------------
function encodeWav(float32, rate) {
  const buf = new ArrayBuffer(44 + float32.length * 2), v = new DataView(buf);
  const w = (o, t) => { for (let i = 0; i < t.length; i++) v.setUint8(o + i, t.charCodeAt(i)); };
  w(0, "RIFF"); v.setUint32(4, 36 + float32.length * 2, true); w(8, "WAVEfmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  w(36, "data"); v.setUint32(40, float32.length * 2, true);
  for (let i = 0; i < float32.length; i++) v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, float32[i])) * 0x7fff, true);
  return new Uint8Array(buf);
}
async function blobToWav16k(blob) {
  const ctx = new AudioContext();
  const src = await ctx.decodeAudioData(await blob.arrayBuffer());
  const len = Math.ceil(src.duration * 16000);
  const off = new OfflineAudioContext(1, len, 16000);
  const node = off.createBufferSource(); node.buffer = src; node.connect(off.destination); node.start();
  const out = await off.startRendering(); ctx.close();
  return encodeWav(out.getChannelData(0), 16000);
}
const b64 = bytes => { let s = ""; for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000)); return btoa(s); };

let rec = null, chunks = [];
$("mic").onclick = async () => {
  if (rec) { rec.stop(); return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({audio: true});
    rec = new MediaRecorder(stream); chunks = [];
    rec.ondataavailable = e => chunks.push(e.data);
    rec.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      rec = null; $("mic").classList.remove("rec"); $("mic").textContent = "🎤 Transcrevendo…"; $("mic").disabled = true;
      try {
        const wav = await blobToWav16k(new Blob(chunks));
        const j = await api("/api/transcribe", {data: b64(wav), mime: "audio/wav"});
        if (j.text) { $("text").value = ($("text").value.trim() ? $("text").value.trim() + " " : "") + j.text; refresh(); }
        else $("msgs").innerHTML = '<div class="warn">⚠ Nenhuma fala detectada.</div>';
      } catch (e) { $("msgs").innerHTML = `<div class="err">${e.message}</div>`; }
      $("mic").textContent = "🎤 Falar"; $("mic").disabled = false;
    };
    rec.start(); $("mic").classList.add("rec"); $("mic").textContent = "⏹ Parar gravação";
  } catch (e) { $("msgs").innerHTML = `<div class="err">Microfone indisponível: ${e.message}</div>`; }
};
$("draw").onclick = async () => {
  const prompt = $("text").value.trim(); if (!prompt) return;
  $("draw").disabled = true; $("draw").textContent = "✏️ Desenhando…";
  try {
    seq++;  // invalida refresh pendente
    const j = await api("/api/draw", {...params(), prompt, draw_size: $("draw_size").value});
    last = j; $("gcode").textContent = j.gcode;
    const st = j.stats;
    $("stats").textContent = `desenho IA · ${st.strokes} traços · escrita ${st.draw_mm} mm · ~${fmtTime(st.est_seconds)} · ${(st.bbox[2]-st.bbox[0]).toFixed(1)}×${(st.bbox[3]-st.bbox[1]).toFixed(1)} mm`;
    $("msgs").innerHTML = j.warnings.map(w => `<div class="warn">⚠ ${w}</div>`).join("") + '<div class="warn">Desenho gerado pela IA — confira o preview. Editar qualquer campo volta ao modo texto.</div>';
    draw(j.strokes, st.bbox);
  } catch (e) { $("msgs").innerHTML = `<div class="err">${e.message}</div>`; }
  $("draw").disabled = false; $("draw").textContent = "✏️ Desenhar (IA, experimental)";
};
api("/api/ai/status").then(j => {
  if (!j.enabled) return;
  for (const id of ["mic", "draw"]) { $(id).disabled = false; $(id).title = ""; }
}).catch(() => {});
