"use strict";
/* Separador Histórico: desempenho dos critérios com uma aposta simulada de 1 unidade no favorito. */

const H = { dados: null };
const CRIT_NOME = { top_vs_bottom: "Top 3 vs Últimos 3", serie_derrotas: "Série de derrotas", ambos: "Os dois critérios" };
const FAIXAS = [[0, 1.4, "< 1,40"], [1.4, 1.7, "1,40 – 1,69"], [1.7, 2.2, "1,70 – 2,19"], [2.2, 99, "≥ 2,20"]];

const fmtU = v => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2).replace(".", ",")} u`;
const fmtPct = v => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(1).replace(".", ",")} %`;
const fmtPct0 = v => `${(v * 100).toFixed(1).replace(".", ",")} %`;
const fmtCota = v => v ? v.toFixed(2).replace(".", ",") : "—";
const sinal = v => v > 0 ? "pos" : v < 0 ? "neg" : "";

async function carregarHistorico() {
  try {
    const r = await fetch(`data/historico.json?t=${Date.now()}`, { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    H.dados = await r.json();
  } catch (e) {
    H.dados = { jogos: [], erro: e.message };
  }
  renderHistorico();
}

function filtrarHistorico() {
  const dias = +$("#h-periodo").value || 0, crit = $("#h-criterio").value;
  const desde = dias ? Date.now() - dias * 864e5 : 0;
  return (H.dados.jogos || []).filter(e => {
    if (dias && new Date(e.data).getTime() < desde) return false;
    if (crit === "ambos") return e.criterios.length > 1;
    if (crit) return e.criterios.includes(crit);
    return true;
  });
}

/* Estatísticas de um conjunto de apostas terminadas. Lucro e ROI só contam apostas com cota. */
function stats(lista) {
  const term = lista.filter(e => e.estado === "terminado");
  const comCota = term.filter(e => e.lucro != null);
  const lucro = comCota.reduce((s, e) => s + e.lucro, 0);
  const acertos = term.filter(e => e.acertou).length;
  const cotaMedia = comCota.length ? comCota.reduce((s, e) => s + e.cota, 0) / comCota.length : 0;
  return {
    n: term.length, acertos, taxa: term.length ? acertos / term.length : 0,
    nCota: comCota.length, lucro, roi: comCota.length ? lucro / comCota.length : 0, cotaMedia,
  };
}

function renderHistorico() {
  const box = $("#h-conteudo");
  if (!H.dados) return;
  const todos = filtrarHistorico();
  const pend = todos.filter(e => e.estado === "pendente");
  const term = todos.filter(e => e.estado === "terminado").sort((a, b) => a.data.localeCompare(b.data));
  const s = stats(term);

  const inicio = (H.dados.jogos || []).map(e => e.selecionado_em || e.data).sort()[0];
  const intro = `<p class="small muted">Aposta simulada de <strong>1 unidade</strong> no favorito (o melhor classificado),
    à última cota da Betclic antes do jogo. Lucro = cota − 1 se ganhar; −1 se empatar ou perder.
    ${inicio ? `Registo desde ${new Date(inicio).toLocaleDateString("pt-PT")}.` : ""}</p>`;

  if (!term.length) {
    const prox = pend.map(e => e.data).sort()[0];
    box.innerHTML = intro + `<div class="card vazio">Ainda não há jogos terminados${H.dados.erro ? "" : " nestes filtros"}.
      ${pend.length ? `Há <strong>${pend.length}</strong> apostas a aguardar resultado${prox ? `; o primeiro jogo é ${fmtDia(new Date(prox))}` : ""}.` : ""}
      Os resultados são registados automaticamente depois de cada jogo.</div>` + listaHTML(todos);
    H.grafico = null;
    ligarMostrarTodas();
    return;
  }

  const breakEven = s.cotaMedia ? 1 / s.cotaMedia : 0;
  box.innerHTML = intro + `
    <div class="kpis">
      <div class="kpi"><span>Lucro</span><strong class="${sinal(s.lucro)}">${fmtU(s.lucro)}</strong>
        <small>${s.nCota} apostas com cota</small></div>
      <div class="kpi"><span>ROI</span><strong class="${sinal(s.roi)}">${fmtPct(s.roi)}</strong>
        <small>lucro por unidade apostada</small></div>
      <div class="kpi"><span>Taxa de acerto</span><strong>${fmtPct0(s.taxa)}</strong>
        <small>${s.acertos} de ${s.n}${breakEven ? ` · precisa de ${fmtPct0(breakEven)}` : ""}</small></div>
      <div class="kpi"><span>Cota média</span><strong>${fmtCota(s.cotaMedia)}</strong>
        <small>${pend.length} a aguardar resultado</small></div>
    </div>
    <div class="card"><h2>Lucro acumulado (unidades)</h2><div id="h-grafico" class="grafico"></div>
      <p class="small muted">Cada ponto é uma aposta terminada, por ordem de data do jogo.</p></div>
    ${tabelaHTML("Por critério", gruposCriterio(term))}
    ${tabelaHTML("Por intervalo de cota", gruposFaixa(term))}
    ${tabelaHTML("Por liga", gruposLiga(term))}
    ${listaHTML(todos)}`;
  H.grafico = term.filter(e => e.lucro != null);
  larguraAnterior = 0;
  desenharGrafico($("#h-grafico"), H.grafico);
  ligarMostrarTodas();
}

function gruposCriterio(term) {
  return ["top_vs_bottom", "serie_derrotas", "ambos"].map(k => [CRIT_NOME[k],
    term.filter(e => k === "ambos" ? e.criterios.length > 1 : e.criterios.includes(k))]);
}
function gruposFaixa(term) {
  return FAIXAS.map(([a, b, nome]) => [nome, term.filter(e => e.cota && e.cota >= a && e.cota < b)]);
}
function gruposLiga(term) {
  const m = new Map();
  term.forEach(e => { const k = `${e.pais} · ${e.liga}`; m.set(k, [...(m.get(k) || []), e]); });
  return [...m.entries()].sort((a, b) => stats(b[1]).lucro - stats(a[1]).lucro);
}

function tabelaHTML(titulo, grupos) {
  const linhas = grupos.filter(([, l]) => l.length).map(([nome, l]) => {
    const s = stats(l);
    return `<tr><th scope="row">${esc(nome)}</th><td>${s.n}</td><td>${fmtPct0(s.taxa)}</td><td class="col-cota">${fmtCota(s.cotaMedia)}</td>
      <td class="${sinal(s.lucro)}">${fmtU(s.lucro)}</td><td class="${sinal(s.roi)}">${s.nCota ? fmtPct(s.roi) : "—"}</td></tr>`;
  }).join("");
  if (!linhas) return "";
  return `<div class="card"><h2>${titulo}</h2><div class="tabela-wrap"><table class="tabela">
    <thead><tr><th></th><th>Apostas</th><th>Acerto</th><th class="col-cota">Cota méd.</th><th>Lucro</th><th>ROI</th></tr></thead>
    <tbody>${linhas}</tbody></table></div></div>`;
}

function listaHTML(lista) {
  if (!lista.length) return "";
  const est = e => e.estado === "terminado" ? (e.acertou ? `<span class="res pos">✓ Ganhou</span>` : `<span class="res neg">✗ Perdeu</span>`)
    : e.estado === "anulado" ? `<span class="res muted">Anulado</span>` : `<span class="res muted">⏳ Pendente</span>`;
  const ordenada = [...lista].sort((a, b) => b.data.localeCompare(a.data));
  const LIM = 15;
  const linhas = ordenada.map((e, n) => {
    const fav = e.aposta === "1" ? e.casa.nome : e.fora.nome;
    const placar = e.estado === "terminado" ? ` <strong>${e.golos_casa}–${e.golos_fora}</strong> ` : " vs ";
    return `<div class="h-item${n >= LIM ? " h-extra" : ""}"${n >= LIM ? " hidden" : ""}>
      <div><strong>${esc(e.casa.nome)}</strong>${placar}<strong>${esc(e.fora.nome)}</strong><br>
        <span class="muted small">${new Date(e.data).toLocaleDateString("pt-PT")} · ${esc(e.liga)} ·
        ${e.criterios.map(c => CRIT_NOME[c]).join(" + ")}</span><br>
        <span class="small">Aposta: ${esc(fav)} (${e.aposta}) @ ${fmtCota(e.cota)}</span></div>
      <div class="h-dir">${est(e)}${e.lucro != null ? `<span class="${sinal(e.lucro)}">${fmtU(e.lucro)}</span>` : ""}</div>
    </div>`;
  }).join("");
  const mais = ordenada.length > LIM ? `<div class="row"><button id="h-todas" class="btn">Mostrar todas (${ordenada.length})</button></div>` : "";
  return `<div class="card"><h2>Apostas registadas (${lista.length})</h2>${linhas}${mais}</div>`;
}

/* Gráfico de linha (SVG) com linha do zero, cruz de leitura e tooltip. */
function desenharGrafico(el, apostas) {
  if (!el) return;
  if (apostas.length < 2) {
    el.innerHTML = `<p class="small muted">O gráfico aparece a partir de 2 apostas terminadas com cota.</p>`;
    return;
  }
  let acc = 0;
  const pts = apostas.map((e, i) => ({ i, e, v: (acc += e.lucro) }));
  const W = Math.max(280, Math.round(el.clientWidth || 640)), Hh = W < 500 ? 200 : 240;
  const m = { t: 12, r: 12, b: 26, l: 40 };
  const vals = pts.map(p => p.v).concat(0);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi - lo < 1) { hi += 0.5; lo -= 0.5; }
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const x = i => m.l + (i / (pts.length - 1)) * (W - m.l - m.r);
  const y = v => m.t + (1 - (v - lo) / (hi - lo)) * (Hh - m.t - m.b);
  const ticks = niceTicks(lo, hi, 4);
  const path = pts.map((p, k) => `${k ? "L" : "M"}${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join("");
  const ult = pts[pts.length - 1];

  el.innerHTML = `<svg viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Lucro acumulado: ${fmtU(ult.v)} após ${pts.length} apostas">
    ${ticks.map(t => `<line class="g-grid" x1="${m.l}" x2="${W - m.r}" y1="${y(t)}" y2="${y(t)}"/>
      <text class="g-eixo" x="${m.l - 6}" y="${y(t) + 4}" text-anchor="end">${t.toFixed(Math.abs(hi - lo) < 4 ? 1 : 0).replace(".", ",")}</text>`).join("")}
    <line class="g-zero" x1="${m.l}" x2="${W - m.r}" y1="${y(0)}" y2="${y(0)}"/>
    <text class="g-eixo" x="${m.l}" y="${Hh - 6}">${new Date(pts[0].e.data).toLocaleDateString("pt-PT")}</text>
    <text class="g-eixo" x="${W - m.r}" y="${Hh - 6}" text-anchor="end">${new Date(ult.e.data).toLocaleDateString("pt-PT")}</text>
    <path class="g-linha" d="${path}"/>
    <circle class="g-ponto" cx="${x(ult.i)}" cy="${y(ult.v)}" r="4"/>
    <line class="g-cruz" y1="${m.t}" y2="${Hh - m.b}" visibility="hidden"/>
    <circle class="g-foco" r="5" visibility="hidden"/>
    <rect class="g-hit" x="${m.l}" y="0" width="${W - m.l - m.r}" height="${Hh}" tabindex="0"/>
  </svg><div class="g-tip" hidden></div>`;

  const svg = el.querySelector("svg"), cruz = el.querySelector(".g-cruz"), foco = el.querySelector(".g-foco");
  const tip = el.querySelector(".g-tip"), hit = el.querySelector(".g-hit");
  const mostrar = k => {
    const p = pts[k], px = x(p.i), py = y(p.v);
    cruz.setAttribute("x1", px); cruz.setAttribute("x2", px); cruz.setAttribute("visibility", "visible");
    foco.setAttribute("cx", px); foco.setAttribute("cy", py); foco.setAttribute("visibility", "visible");
    tip.textContent = "";
    const linha = (t, cls) => { const d = document.createElement("div"); d.textContent = t; if (cls) d.className = cls; tip.appendChild(d); };
    linha(`Aposta ${k + 1} · ${new Date(p.e.data).toLocaleDateString("pt-PT")}`, "muted");
    linha(`${p.e.casa.nome} ${p.e.golos_casa}–${p.e.golos_fora} ${p.e.fora.nome}`);
    linha(`Esta aposta: ${fmtU(p.e.lucro)} (cota ${fmtCota(p.e.cota)})`);
    linha(`Acumulado: ${fmtU(p.v)}`, "forte");
    tip.hidden = false;
    const r = svg.getBoundingClientRect(), escala = r.width / W;
    const left = Math.min(Math.max(px * escala - tip.offsetWidth / 2, 0), r.width - tip.offsetWidth);
    tip.style.left = `${left}px`;
    tip.style.top = `${Math.max(py * escala - tip.offsetHeight - 12, 0)}px`;
  };
  const esconder = () => { tip.hidden = true; cruz.setAttribute("visibility", "hidden"); foco.setAttribute("visibility", "hidden"); };
  let atual = pts.length - 1;
  hit.addEventListener("pointermove", ev => {
    const r = svg.getBoundingClientRect(), vx = (ev.clientX - r.left) * (W / r.width);
    atual = Math.round(((vx - m.l) / (W - m.l - m.r)) * (pts.length - 1));
    mostrar(Math.max(0, Math.min(pts.length - 1, atual)));
  });
  hit.addEventListener("pointerleave", esconder);
  hit.addEventListener("focus", () => mostrar(atual));
  hit.addEventListener("blur", esconder);
  hit.addEventListener("keydown", ev => {
    if (ev.key === "ArrowLeft" || ev.key === "ArrowRight") {
      atual = Math.max(0, Math.min(pts.length - 1, atual + (ev.key === "ArrowRight" ? 1 : -1)));
      mostrar(atual); ev.preventDefault();
    }
  });
}

function ligarMostrarTodas() {
  const b = $("#h-todas");
  if (b) b.onclick = () => { document.querySelectorAll(".h-extra").forEach(x => { x.hidden = false; }); b.remove(); };
}

function niceTicks(lo, hi, n) {
  const raw = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map(f => f * mag).find(s => s >= raw) || 10 * mag;
  const out = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step) out.push(+t.toFixed(10));
  return out;
}

["#h-periodo", "#h-criterio"].forEach(s => $(s).addEventListener("change", renderHistorico));
/* O gráfico é desenhado à largura real: redesenha ao abrir o separador e ao mudar o tamanho da janela. */
let larguraAnterior = 0;
function redesenhar() {
  const el = $("#h-grafico");
  if (!el || !H.grafico || !el.clientWidth || el.clientWidth === larguraAnterior) return;
  larguraAnterior = el.clientWidth;
  desenharGrafico(el, H.grafico);
}
window.addEventListener("resize", redesenhar);
$('[data-view="historico"]').addEventListener("click", () => requestAnimationFrame(redesenhar));
document.addEventListener("visibilitychange", () => { if (!document.hidden) carregarHistorico(); });
carregarHistorico();
