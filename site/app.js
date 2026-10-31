"use strict";

const GIST_FILE = "boletim-apostas.json";
const LS = { slip: "slip.v1", token: "gh.token", gist: "gh.gist", filtros: "filtros.v1" };
const PICK_LABEL = { "1": "Vitória casa", "X": "Empate", "2": "Vitória fora" };
const CASAS = ["Betclic", "Betano"];

const $ = (s, el = document) => el.querySelector(s);
const ls = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* sem armazenamento */ } },
  del(k) { try { localStorage.removeItem(k); } catch { /* idem */ } },
};

let DATA = { jogos: [], ligas: [] };
let slip = ls.get(LS.slip, { updatedAt: 0, stake: 5, items: [] });

/* ------------------------------------------------------------------ util */
const fmtHora = d => d.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" });
const fmtDia = d => d.toLocaleDateString("pt-PT", { weekday: "long", day: "numeric", month: "long" });
const diaKey = d => d.toLocaleDateString("sv-SE"); // AAAA-MM-DD no fuso local
const num = v => (typeof v === "number" && isFinite(v) ? v : parseFloat(String(v).replace(",", ".")));
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function formaHTML(f) {
  return f ? `<span class="forma">${[...f].map(r => `<b class="${r}">${r}</b>`).join("")}</span>` : "";
}

/* ------------------------------------------------------------------ dados */
async function carregar() {
  try {
    const r = await fetch(`data/jogos.json?t=${Date.now()}`, { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    DATA = await r.json();
  } catch (e) {
    $("#meta").textContent = `Não foi possível carregar os dados (${e.message}).`;
    return;
  }
  const g = DATA.gerado_em ? new Date(DATA.gerado_em) : null;
  const okL = (DATA.ligas || []).filter(l => l.ok).length;
  $("#meta").textContent = g
    ? `Atualizado ${g.toLocaleString("pt-PT", { dateStyle: "short", timeStyle: "short" })} · ${okL} ligas · ${DATA.jogos.length} jogos`
    : "Ainda sem dados — o scanner ainda não correu.";
  preencherFiltros();
  render();
  renderLigas();
  carregarCreditos();
}

async function carregarCreditos() {
  try {
    const r = await fetch(`data/creditos.json?t=${Date.now()}`, { cache: "no-store" });
    if (!r.ok) return;
    const c = await r.json();
    const ren = c.dia_renovacao ? `renovação no dia ${c.dia_renovacao}` : "dia de renovação ainda por detetar (orçamento prudente)";
    $("#creditos").textContent = `Créditos de cotas: ${c.restantes ?? "?"} restantes · orçamento de hoje ${c.orcamento_hoje ?? "?"} ` +
      `(gastos ${c.gastos_hoje ?? 0}) · ${ren}.`;
  } catch { /* sem informação de créditos */ }
}

function preencherFiltros() {
  const paises = [...new Set(DATA.jogos.map(j => j.pais))].sort((a, b) => a.localeCompare(b, "pt"));
  const dias = [...new Set(DATA.jogos.map(j => diaKey(new Date(j.data))))].sort();
  const fp = $("#f-pais"), fd = $("#f-dia");
  fp.length = 1; fd.length = 1;
  paises.forEach(p => fp.add(new Option(p, p)));
  dias.forEach(d => fd.add(new Option(fmtDia(new Date(d + "T12:00")), d)));
  const f = ls.get(LS.filtros, {});
  for (const [id, v] of Object.entries(f)) {
    const el = $("#" + id);
    if (!el) continue;
    if (el.type === "checkbox") el.checked = !!v;
    else if ([...(el.options || [])].some(o => o.value === v) || el.tagName === "INPUT") el.value = v;
  }
}

function filtrar() {
  const crit = $("#f-criterio").value, pais = $("#f-pais").value, dia = $("#f-dia").value;
  const busca = $("#f-busca").value.trim().toLowerCase(), soCotas = $("#f-cotas").checked;
  ls.set(LS.filtros, { "f-criterio": crit, "f-pais": pais, "f-dia": dia, "f-cotas": soCotas });
  const agora = Date.now();
  return DATA.jogos.filter(j => {
    if (new Date(j.data).getTime() < agora - 2 * 3600e3) return false;
    const tipos = new Set(j.criterios.map(c => c.tipo));
    if (crit === "ambos" && tipos.size < 2) return false;
    if (crit && crit !== "ambos" && !tipos.has(crit)) return false;
    if (pais && j.pais !== pais) return false;
    if (dia && diaKey(new Date(j.data)) !== dia) return false;
    if (soCotas && !j.cotas) return false;
    if (busca && !`${j.casa.nome} ${j.fora.nome}`.toLowerCase().includes(busca)) return false;
    return true;
  });
}

/* ------------------------------------------------------------------ render jogos */
function render() {
  const lista = $("#lista");
  lista.innerHTML = "";
  const jogos = filtrar();
  if (!jogos.length) {
    const agora = Date.now();
    const total = DATA.jogos.filter(j => new Date(j.data).getTime() >= agora - 2 * 3600e3).length;
    const filtrosAtivos = ["#f-criterio", "#f-pais", "#f-dia", "#f-busca"].some(s => $(s).value) || $("#f-cotas").checked;
    lista.innerHTML = `<div class="vazio">${total && filtrosAtivos
      ? `Os filtros ativos escondem os ${total} jogos selecionados.<div class="row" style="justify-content:center">
           <button id="limpar-filtros" class="btn primary">Limpar filtros</button></div>`
      : "Não há jogos selecionados para os próximos 7 dias."}</div>`;
    const b = $("#limpar-filtros");
    if (b) b.onclick = () => {
      ["#f-criterio", "#f-pais", "#f-dia", "#f-busca"].forEach(s => { $(s).value = ""; });
      $("#f-cotas").checked = false;
      render();
    };
    return;
  }
  let diaAtual = "";
  const tpl = $("#tpl-jogo");
  for (const j of jogos) {
    const d = new Date(j.data);
    if (diaKey(d) !== diaAtual) {
      diaAtual = diaKey(d);
      const h = document.createElement("div");
      h.className = "dia-titulo";
      h.textContent = fmtDia(d);
      lista.appendChild(h);
    }
    const el = tpl.content.firstElementChild.cloneNode(true);
    $(".liga", el).textContent = `${j.pais} · ${j.liga}`;
    $("time", el).textContent = fmtHora(d);
    const favs = new Set(j.criterios.map(c => c.favorito));
    for (const lado of ["casa", "fora"]) {
      const t = j[lado], box = $("." + lado, el);
      $(".nome", box).textContent = t.nome;
      $(".info", box).innerHTML = `${t.posicao}.º/${t.total} · ${t.pontos} pts · ${t.jogos} J<br>${formaHTML(t.forma)}`;
      if (favs.has(lado)) box.classList.add("fav");
    }
    $(".criterios", el).innerHTML = j.criterios.map(c => `<span class="chip ${c.tipo}">${esc(c.texto)}</span>`).join("");

    const bc = j.cotas && (j.cotas.betclic_fr || j.cotas.betclic || Object.values(j.cotas)[0]);
    const cot = bc ? bc.cotas : {};
    const favPick = favs.has("casa") ? "1" : favs.has("fora") ? "2" : null;
    const cotasEl = $(".cotas", el);
    for (const p of ["1", "X", "2"]) {
      const b = document.createElement("button");
      b.className = "odd" + (p === favPick ? " fav" : "") + (cot[p] ? "" : " nd") + (naSlip(j.id, p) ? " sel" : "");
      b.innerHTML = `<small>${p}</small><strong>${cot[p] ? cot[p].toFixed(2) : "s/ cota"}</strong>`;
      b.title = PICK_LABEL[p];
      b.onclick = () => toggleSelecao(j, p, cot[p]);
      cotasEl.appendChild(b);
    }
    const fonte = document.createElement("div");
    fonte.className = "cotas-fonte";
    fonte.textContent = bc
      ? `${bc.titulo}${bc.atualizado ? " · " + new Date(bc.atualizado).toLocaleString("pt-PT", { dateStyle: "short", timeStyle: "short" }) : ""}${j.cotas_antigas ? " (cota anterior)" : ""}`
      : "Sem cota disponível — toca para adicionar e escreve a cota no boletim.";
    cotasEl.appendChild(fonte);
    const q = encodeURIComponent(`${j.casa.nome} ${j.fora.nome}`);
    $(".links", el).innerHTML =
      `<a href="https://www.betclic.pt/" target="_blank" rel="noopener">Abrir Betclic</a>` +
      `<a href="https://www.betano.pt/" target="_blank" rel="noopener">Abrir Betano</a>` +
      `<a href="https://www.google.com/search?q=${q}" target="_blank" rel="noopener">Pesquisar</a>`;
    lista.appendChild(el);
  }
}

function renderLigas() {
  const rows = (DATA.ligas || []).map(l =>
    `<tr><td>${esc(l.pais)}</td><td>${esc(l.liga)}</td>` +
    (l.ok ? `<td class="ok">OK</td><td>${l.jogos_agendados} agendados · ${l.selecionados} selecionados</td>`
          : `<td class="erro">Erro</td><td class="small">${esc(l.erro || "")}</td>`) + `</tr>`).join("");
  $("#ligas").innerHTML = `<table>${rows}</table>`;
}

/* ------------------------------------------------------------------ boletim */
const naSlip = (id, p) => slip.items.some(i => i.gameId === id && i.pick === p);

function toggleSelecao(j, pick, odd) {
  const idx = slip.items.findIndex(i => i.gameId === j.id);
  const mesmo = idx >= 0 && slip.items[idx].pick === pick;
  if (idx >= 0) slip.items.splice(idx, 1); // um palpite por jogo
  if (!mesmo) {
    slip.items.push({ gameId: j.id, pick, odd: odd || null, casa: "Betclic", data: j.data, liga: j.liga,
                      casaNome: j.casa.nome, foraNome: j.fora.nome });
  }
  alterado();
  render();
}

function alterado() {
  slip.updatedAt = Date.now();
  ls.set(LS.slip, slip);
  renderSlip();
  agendarPush();
}

function renderSlip() {
  $("#slip-count").textContent = slip.items.length;
  const box = $("#boletim");
  if (!slip.items.length) {
    box.innerHTML = `<div class="card vazio">O boletim está vazio. Toca numa cota (1, X ou 2) na lista de jogos para a adicionar.</div>`;
    return;
  }
  slip.items.sort((a, b) => a.data.localeCompare(b.data));
  let total = 1, completo = true;
  const itens = slip.items.map((i, n) => {
    const o = num(i.odd);
    if (o > 1) total *= o; else completo = false;
    const d = new Date(i.data);
    return `<div class="sel-item">
      <div class="desc"><strong>${esc(i.casaNome)} – ${esc(i.foraNome)}</strong><br>
        ${PICK_LABEL[i.pick]} (${i.pick}) <span class="muted">· ${esc(i.liga)} · ${fmtDia(d)} ${fmtHora(d)}</span></div>
      <div class="ctrl">
        <select data-n="${n}" data-f="casa">${CASAS.map(c => `<option${c === i.casa ? " selected" : ""}>${c}</option>`).join("")}</select>
        <input data-n="${n}" data-f="odd" type="text" inputmode="decimal" placeholder="cota" value="${i.odd ?? ""}">
        <button class="x" data-del="${n}" aria-label="Remover">✕</button>
      </div></div>`;
  }).join("");
  const stake = num(slip.stake) || 0;
  box.innerHTML = `<div class="card"><h2>Combinada (${slip.items.length} seleções)</h2>${itens}
    <div class="totais">
      <div><span class="small muted">Cota total</span><strong>${completo ? total.toFixed(2) : "—"}</strong></div>
      <div><span class="small muted">Retorno potencial</span><strong>${completo ? (total * stake).toFixed(2) + " €" : "—"}</strong></div>
    </div>
    <label class="field">Valor da aposta (€)<input id="stake" type="text" inputmode="decimal" value="${slip.stake ?? ""}"></label>
    ${completo ? "" : `<p class="small muted">Preenche a cota de todas as seleções para calcular o total.</p>`}
    <div class="row"><button id="limpar-slip" class="btn danger">Limpar boletim</button></div></div>`;

  box.querySelectorAll("[data-f]").forEach(el => el.onchange = () => {
    const it = slip.items[+el.dataset.n];
    it[el.dataset.f] = el.dataset.f === "odd" ? (num(el.value) || null) : el.value;
    alterado();
  });
  box.querySelectorAll("[data-del]").forEach(el => el.onclick = () => {
    slip.items.splice(+el.dataset.del, 1); alterado(); render();
  });
  $("#stake").onchange = e => { slip.stake = num(e.target.value) || 0; alterado(); };
  $("#limpar-slip").onclick = () => { if (confirm("Limpar todas as seleções?")) { slip.items = []; alterado(); render(); } };
}

/* ------------------------------------------------------------------ sincronização (GitHub Gist) */
let pushTimer = null, syncing = false;
const estado = t => { $("#s-estado").textContent = t; };

async function gh(path, opts = {}) {
  const token = ls.get(LS.token, "");
  const r = await fetch("https://api.github.com" + path, {
    ...opts, cache: "no-store",
    headers: { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json",
               ...(opts.body ? { "Content-Type": "application/json" } : {}) },
  });
  if (!r.ok) throw new Error(`GitHub ${r.status}`);
  return r.json();
}

async function encontrarGist() {
  let id = ls.get(LS.gist, "");
  if (id) return id;
  for (let page = 1; page <= 5; page++) {
    const list = await gh(`/gists?per_page=100&page=${page}`);
    const g = list.find(x => x.files && x.files[GIST_FILE]);
    if (g) { ls.set(LS.gist, g.id); return g.id; }
    if (list.length < 100) break;
  }
  return "";
}

async function pull() {
  if (!ls.get(LS.token, "") || syncing) return;
  syncing = true;
  try {
    const id = await encontrarGist();
    if (!id) { await push(true); return; }
    const g = await gh(`/gists/${id}`);
    const f = g.files[GIST_FILE];
    let remoto = null;
    if (f) remoto = JSON.parse(f.truncated ? await (await fetch(f.raw_url)).text() : f.content);
    if (remoto && remoto.updatedAt > slip.updatedAt) {
      slip = remoto; ls.set(LS.slip, slip); renderSlip(); render();
      estado(`Sincronizado (recebido) às ${fmtHora(new Date())}.`);
    } else if (!remoto || remoto.updatedAt < slip.updatedAt) {
      syncing = false; await push(true); return;
    } else {
      estado(`Sincronizado às ${fmtHora(new Date())}.`);
    }
  } catch (e) {
    if (String(e.message).includes("404")) ls.del(LS.gist);
    estado(`Erro de sincronização: ${e.message}`);
  } finally { syncing = false; }
}

async function push(direto = false) {
  if (!ls.get(LS.token, "")) return;
  try {
    const body = { files: { [GIST_FILE]: { content: JSON.stringify(slip) } } };
    let id = direto ? ls.get(LS.gist, "") : await encontrarGist();
    if (id) await gh(`/gists/${id}`, { method: "PATCH", body: JSON.stringify(body) });
    else {
      const g = await gh("/gists", { method: "POST", body: JSON.stringify({
        ...body, public: false, description: "Boletim do Scanner de Jogos (sincronização)" }) });
      ls.set(LS.gist, g.id);
    }
    estado(`Sincronizado (enviado) às ${fmtHora(new Date())}.`);
  } catch (e) { estado(`Erro ao enviar: ${e.message}`); }
}

function agendarPush() { clearTimeout(pushTimer); pushTimer = setTimeout(() => push(), 800); }

/* ------------------------------------------------------------------ arranque */
function init() {
  document.querySelectorAll(".tab").forEach(t => t.onclick = () => {
    document.querySelectorAll(".tab").forEach(x => x.classList.toggle("active", x === t));
    document.querySelectorAll(".view").forEach(v => v.classList.toggle("active", v.id === "view-" + t.dataset.view));
  });
  ["#f-criterio", "#f-pais", "#f-dia", "#f-cotas"].forEach(s => $(s).onchange = render);
  $("#f-busca").oninput = render;

  $("#s-token").value = ls.get(LS.token, "");
  $("#s-guardar").onclick = () => { ls.set(LS.token, $("#s-token").value.trim()); ls.del(LS.gist); estado("A sincronizar…"); pull(); };
  $("#s-sync").onclick = () => { estado("A sincronizar…"); pull(); };
  $("#s-limpar").onclick = () => { ls.del(LS.token); ls.del(LS.gist); $("#s-token").value = ""; estado("Sincronização desligada."); };
  estado(ls.get(LS.token, "") ? "Sincronização ativa." : "Sincronização desligada (boletim só neste dispositivo).");

  document.addEventListener("visibilitychange", () => { if (!document.hidden) { pull(); carregar(); } });
  setInterval(() => { if (!document.hidden) pull(); }, 60000);

  renderSlip();
  carregar();
  pull();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
}

init();
