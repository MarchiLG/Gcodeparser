const $ = id => document.getElementById(id);
const FIELDS = ["text","font","align","size","width","line_spacing","letter_spacing","margin","travel_x","travel_y","rotation",
                "zmin","zmax","feed","travel_feed","zfeed","pen_up","pen_down","pen_dwell"];
let last = null, timer = null, seq = 0, quadrant = 4, spindleMax = 1000, rateX = 500, rateY = 500;
const penMode = () => document.querySelector('input[name=pen]:checked').value;

function params() {
  const p = {};
  for (const k of FIELDS) p[k] = $(k).value;
  p.zero = $("zero").checked;
  p.quadrant = quadrant;
  p.pen = penMode();
  p.spindle_max = spindleMax;
  p.rate_x = rateX; p.rate_y = rateY;
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

// Retângulo do curso no quadrante escolhido (coordenadas da máquina, vista de cima).
function workspace() {
  const tx = parseFloat($("travel_x").value) || 200, ty = parseFloat($("travel_y").value) || 200;
  const sx = (quadrant === 1 || quadrant === 4) ? 1 : -1, sy = (quadrant === 1 || quadrant === 2) ? 1 : -1;
  return [sx > 0 ? 0 : -tx, sy > 0 ? 0 : -ty, sx > 0 ? tx : 0, sy > 0 ? ty : 0];
}

function draw(strokes, bbox) {
  const cv = $("cv"), ctx = cv.getContext("2d");
  ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, cv.width, cv.height);
  const ws = workspace();
  // vista = curso ∪ desenho (se o desenho estourar o curso, dá para ver)
  const v = strokes.length ? [Math.min(ws[0], bbox[0]), Math.min(ws[1], bbox[1]), Math.max(ws[2], bbox[2]), Math.max(ws[3], bbox[3])] : ws;
  const pad = 24, vw = Math.max(v[2] - v[0], 1), vh = Math.max(v[3] - v[1], 1);
  const s = Math.min((cv.width - 2*pad) / vw, (cv.height - 2*pad) / vh);
  const ox = (cv.width - vw * s) / 2, oy = (cv.height - vh * s) / 2;
  const X = x => ox + (x - v[0]) * s, Y = y => oy + (v[3] - y) * s;
  // curso da máquina
  ctx.fillStyle = "#f7f7f2"; ctx.fillRect(X(ws[0]), Y(ws[3]), (ws[2]-ws[0]) * s, (ws[3]-ws[1]) * s);
  ctx.strokeStyle = "#999"; ctx.lineWidth = 1; ctx.setLineDash([]);
  ctx.strokeRect(X(ws[0]), Y(ws[3]), (ws[2]-ws[0]) * s, (ws[3]-ws[1]) * s);
  // origem e eixos
  ctx.strokeStyle = "#2e8b57"; ctx.fillStyle = "#2e8b57"; ctx.lineWidth = 2; ctx.font = "12px system-ui";
  const sx = (quadrant === 1 || quadrant === 4) ? 1 : -1, sy = (quadrant === 1 || quadrant === 2) ? 1 : -1;
  const L = Math.min(40, 0.2 * Math.min(ws[2]-ws[0], ws[3]-ws[1]) * s);
  ctx.beginPath(); ctx.moveTo(X(0), Y(0)); ctx.lineTo(X(0) + sx * L, Y(0)); ctx.moveTo(X(0), Y(0)); ctx.lineTo(X(0), Y(0) - sy * L); ctx.stroke();
  ctx.textBaseline = "middle"; ctx.textAlign = sx > 0 ? "left" : "right";
  ctx.fillText(sx > 0 ? "X+" : "X−", X(0) + sx * (L + 4), Y(0));
  ctx.textAlign = "center"; ctx.textBaseline = sy > 0 ? "bottom" : "top";
  ctx.fillText(sy > 0 ? "Y+" : "Y−", X(0), Y(0) - sy * (L + 4));
  ctx.beginPath(); ctx.arc(X(0), Y(0), 3.5, 0, 7); ctx.fill();
  if (!strokes.length) return;
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
const schedule = () => { clearTimeout(timer); timer = setTimeout(refresh, 250); queueAutosave(); };

for (const k of FIELDS) $(k).addEventListener("input", schedule);
$("zero").addEventListener("change", schedule);

// quadrante (abas)
function setQuadrant(q) {
  quadrant = q;
  document.querySelectorAll("[data-q]").forEach(b => b.setAttribute("aria-checked", String(+b.dataset.q === q)));
}
document.querySelectorAll("[data-q]").forEach(b => b.onclick = () => { setQuadrant(+b.dataset.q); schedule(); });
setQuadrant(quadrant);

// rotação da folha
const rotate = d => { const v = (((parseFloat($("rotation").value) || 0) + d) % 360 + 360) % 360; $("rotation").value = v > 180 ? v - 360 : v; schedule(); };
$("rotl").onclick = () => rotate(-90);
$("rotr").onclick = () => rotate(90);

// caneta: Z x servo
function syncPen() {
  const servo = penMode() === "servo";
  $("pen_z").hidden = servo; $("pen_servo").hidden = !servo; $("zfeed_wrap").hidden = servo;
  document.querySelector(".pad.z").hidden = servo;   // sem eixo Z, o jog Z não faz sentido
  schedule();
}
document.querySelectorAll("input[name=pen]").forEach(r => r.addEventListener("change", syncPen));

// abas de configuração
document.querySelectorAll("[data-tab]").forEach(t => t.onclick = () => {
  document.querySelectorAll("[data-tab]").forEach(o => {
    const on = o === t;
    o.setAttribute("aria-selected", String(on)); $("tab-" + o.dataset.tab).hidden = !on;
  });
});

// curso: preenche com $130/$131 da placa enquanto o usuário não mexer
const touched = new Set();
for (const k of ["travel_x", "travel_y"]) $(k).addEventListener("input", () => touched.add(k));
$("copy").onclick = async () => { if (last) { await navigator.clipboard.writeText(last.gcode); $("copy").textContent = "Copiado!"; setTimeout(() => $("copy").textContent = "Copiar G-code", 1200); } };
$("download").onclick = () => {
  if (!last) return;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([last.gcode], {type: "text/plain"}));
  a.download = "texto.gcode"; a.click(); URL.revokeObjectURL(a.href);
};

// ---------------- perfis: autosave + nomeados (guardados no servidor) ----------------
const PROFILE_KEYS = [...FIELDS.filter(k => k !== "text"), "jfeed", "step"];
let ready = false, saveTimer = null, lastSaved = "", DEFAULTS = {};
function collect() {
  const o = {};
  for (const k of PROFILE_KEYS) o[k] = $(k).value;
  o.zero = $("zero").checked; o.quadrant = quadrant; o.pen = penMode();
  return o;
}
function applySettings(o) {
  for (const k of PROFILE_KEYS) {
    if (!(k in o) || o[k] == null) continue;
    const el = $(k);
    if (el.tagName === "SELECT" && ![...el.options].some(op => op.value === String(o[k]))) continue;   // fonte/passo que não existe mais
    el.value = o[k];
    if (k === "travel_x" || k === "travel_y") touched.add(k);   // o que o perfil diz vence o $130/$131 da placa
  }
  if ("zero" in o) $("zero").checked = !!o.zero;
  if ([1, 2, 3, 4].includes(+o.quadrant)) setQuadrant(+o.quadrant);
  if (o.pen === "z" || o.pen === "servo") document.querySelector(`input[name=pen][value=${o.pen}]`).checked = true;
  syncPen();
}
function queueAutosave() {
  if (!ready) return;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    const o = collect(), j = JSON.stringify(o);
    if (j === lastSaved) return;
    try { await api("/api/profiles/autosave", {settings: o}); lastSaved = j; } catch (e) { /* servidor fora: tenta de novo na próxima alteração */ }
  }, 600);
}
document.addEventListener("change", e => { if (e.target.id === "jfeed" || e.target.id === "step") queueAutosave(); });

const pmsg = (t, err) => { $("profile_msg").textContent = t || ""; $("profile_msg").className = "hint" + (err ? " err" : ""); };
async function refreshProfiles(select) {
  const j = await api("/api/profiles");
  const sel = $("profile_list"), names = Object.keys(j.profiles).sort((a, b) => a.localeCompare(b));
  sel.innerHTML = names.length ? "" : "<option value=''>nenhum perfil salvo</option>";
  for (const n of names) { const o = document.createElement("option"); o.value = o.textContent = n; sel.appendChild(o); }
  if (select && names.includes(select)) sel.value = select;
  return j;
}
$("profile_list").onchange = () => { $("profile_name").value = $("profile_list").value; };
$("profile_load").onclick = async () => {
  const name = $("profile_list").value; if (!name) return;
  try {
    const j = await api("/api/profiles");
    if (!j.profiles[name]) throw new Error("perfil não encontrado");
    applySettings({...DEFAULTS, ...j.profiles[name]}); $("profile_name").value = name;
    schedule(); pmsg(`Perfil “${name}” carregado.`);
  } catch (e) { pmsg(e.message, true); }
};
$("profile_save").onclick = async () => {
  const name = $("profile_name").value.trim().replace(/\s+/g, " ");
  if (!name) return pmsg("Dê um nome ao perfil.", true);
  try {
    const j = await api("/api/profiles");
    if (j.profiles[name] && !confirm(`Sobrescrever o perfil “${name}”?`)) return;
    await api("/api/profiles/save", {name, settings: collect()});
    await refreshProfiles(name); pmsg(`Perfil “${name}” salvo.`);
  } catch (e) { pmsg(e.message, true); }
};
$("profile_delete").onclick = async () => {
  const name = $("profile_list").value; if (!name) return;
  if (!confirm(`Excluir o perfil “${name}”?`)) return;
  try { await api("/api/profiles/delete", {name}); await refreshProfiles(); pmsg(`Perfil “${name}” excluído.`); }
  catch (e) { pmsg(e.message, true); }
};
$("profile_defaults").onclick = () => { touched.clear(); applySettings(DEFAULTS); schedule(); pmsg("Padrões restaurados (o texto não muda)."); };

(async () => {
  await loadFonts();
  DEFAULTS = collect();
  try {
    const j = await refreshProfiles();
    if (j.autosave) applySettings({...DEFAULTS, ...j.autosave});
    lastSaved = JSON.stringify(collect());
  } catch (e) { /* sem perfis: segue com os padrões */ }
  ready = true;
  syncPen();
})();

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
    const cfg = j.settings || {};
    if (j.connected) {
      if (cfg["30"]) spindleMax = cfg["30"];
      if (cfg["110"]) rateX = cfg["110"];
      if (cfg["111"]) rateY = cfg["111"];
      let changed = false;
      for (const [k, id] of [["130", "travel_x"], ["131", "travel_y"]])
        if (cfg[k] && !touched.has(id) && +$(id).value !== cfg[k]) { $(id).value = cfg[k]; changed = true; }
      if (changed) schedule();
    }
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
// Jog: toque = 1 passo (como antes); segurar (>HOLD_MS) = movimento contínuo, renovado por keep-alive
// enquanto o botão estiver preso. Soltar manda jogstop (jog-cancel na placa); se o cliente sumir, o servidor para sozinho.
const HOLD_MS = 250, BEAT_MS = 250;
const jogFeed = () => parseFloat($("jfeed").value) || 500;
let jogChain = Promise.resolve();   // serializa keep-alives e o stop, para o stop nunca ultrapassar um start
document.querySelectorAll("[data-j]").forEach(b => {
  const k = b.dataset.j;
  if (k === "home") { b.onclick = () => act("send", {line: "G90 G0 X0 Y0"}); return; }   // vai à origem de trabalho
  const dir = {x: 0, y: 0, z: 0}; dir[k[0]] = k[1] === "+" ? 1 : -1;
  let down = false, holding = false, tmr = null, beat = null;
  const step = () => { const d = parseFloat($("step").value); return act("jog", {x: dir.x * d, y: dir.y * d, z: dir.z * d, feed: jogFeed()}); };
  const ping = () => { jogChain = jogChain.then(() => act("jogstart", {...dir, feed: jogFeed()})); };
  const end = () => {
    if (!down) return;
    down = false; clearTimeout(tmr); clearInterval(beat);
    if (holding) { holding = false; jogChain = jogChain.then(() => act("jogstop")); }
  };
  b.addEventListener("pointerdown", e => {
    if (e.button !== 0 || down) return;
    e.preventDefault(); b.setPointerCapture(e.pointerId);
    down = true; holding = false;
    step();
    tmr = setTimeout(() => { holding = true; ping(); beat = setInterval(ping, BEAT_MS); }, HOLD_MS);
  });
  for (const ev of ["pointerup", "pointercancel", "lostpointercapture"]) b.addEventListener(ev, end);
  b.addEventListener("contextmenu", e => e.preventDefault());
  b.addEventListener("click", e => { if (e.detail === 0) step(); });   // teclado (Enter/Espaço)
  window.addEventListener("blur", end);
});
document.querySelectorAll("[data-m]").forEach(b => b.onclick = () => {
  const k = b.dataset.m, p = params();
  if (k === "zeroxy") act("zero", {axes: "XY"});
  else if (k === "zeroz") act("zero", {axes: "Z"});
  else if (k === "penup") act("send", {line: p.pen === "servo" ? `M3 S${p.pen_up}` : `G90 G0 Z${p.zmax}`});
  else if (k === "pendown") act("send", {line: p.pen === "servo" ? `M3 S${p.pen_down}` : `G90 G1 Z${p.zmin} F${p.zfeed}`});
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
