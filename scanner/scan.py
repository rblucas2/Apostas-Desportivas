#!/usr/bin/env python3
"""Scanner de jogos de futebol para apostas combinadas.

Critérios:
  1. Top-N da classificação contra Bottom-N da mesma liga (por defeito 3 vs 3).
  2. Equipa com uma série de derrotas consecutivas (por defeito >= 4, ou seja,
     "mais de 3") que defronta um adversário melhor classificado.

Fontes:
  - Classificações, resultados e calendário: API pública (não oficial) da ESPN.
  - Cotas 1X2: The Odds API (requer a variável de ambiente ODDS_API_KEY).

Só usa a biblioteca padrão do Python.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ESPN_STANDINGS = "https://site.api.espn.com/apis/v2/sports/soccer/{slug}/standings"
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
ESPN_TEAM_SCHEDULE = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/teams/{team}/schedule"
ODDS_URL = "https://api.the-odds-api.com/v4/sports/{sport}/odds"

ROOT = Path(__file__).resolve().parent
UTC = dt.timezone.utc


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def http_json(url: str, params: dict | None = None, retries: int = 3):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (scanner-apostas)"})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp), resp.headers
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403, 404, 422):
                raise
            last = e
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
        time.sleep(2 ** attempt)
    raise last


# ---------------------------------------------------------------- ESPN parsing

def _stat(entry: dict, name: str):
    for s in entry.get("stats", []):
        if s.get("name") == name or s.get("type") == name:
            return s.get("value")
    return None


def parse_standings(data: dict) -> dict:
    """Devolve {team_id: {...}} com posição calculada dentro de cada grupo."""
    groups = data.get("children") or [data]
    table = {}
    for g in groups:
        entries = (g.get("standings") or {}).get("entries") or []
        rows = []
        for e in entries:
            team = e.get("team") or {}
            if not team.get("id"):
                continue
            rows.append({
                "id": str(team["id"]),
                "nome": team.get("displayName") or team.get("name") or "?",
                "rank": _stat(e, "rank"),
                "pontos": _stat(e, "points") or 0,
                "jogos": int(_stat(e, "gamesPlayed") or 0),
                "dg": _stat(e, "pointDifferential") or 0,
                "golos": _stat(e, "pointsFor") or 0,
            })
        if not rows:
            continue
        if all(r["rank"] for r in rows):
            rows.sort(key=lambda r: r["rank"])
        else:
            rows.sort(key=lambda r: (-r["pontos"], -r["dg"], -r["golos"]))
        n = len(rows)
        for i, r in enumerate(rows, start=1):
            table[r["id"]] = {
                "nome": r["nome"],
                "posicao": i,
                "total": n,
                "pontos": int(r["pontos"]),
                "jogos": r["jogos"],
                "grupo": g.get("name") or "",
            }
    return table


def _score(c: dict):
    s = c.get("score")
    if isinstance(s, dict):
        s = s.get("value", s.get("displayValue"))
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def parse_events(data: dict) -> list[dict]:
    out = []
    for ev in data.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        cs = comp.get("competitors") or []
        home = next((c for c in cs if c.get("homeAway") == "home"), None)
        away = next((c for c in cs if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        st = ((ev.get("status") or comp.get("status") or {}).get("type") or {})
        hs, as_ = _score(home), _score(away)
        terminado = (bool(st.get("completed")) or st.get("state") == "post") and hs is not None and as_ is not None
        out.append({
            "id": str(ev.get("id")),
            "data": ev.get("date"),
            "estado": st.get("state") or "",
            "estado_nome": st.get("name") or "",
            "terminado": terminado,
            "casa_id": str((home.get("team") or {}).get("id")),
            "fora_id": str((away.get("team") or {}).get("id")),
            "casa": (home.get("team") or {}).get("displayName") or "?",
            "fora": (away.get("team") or {}).get("displayName") or "?",
            "golos_casa": hs,
            "golos_fora": as_,
        })
    return out


def parse_date(s: str) -> dt.datetime:
    s = s.replace("Z", "+00:00")
    # ESPN às vezes devolve "2026-10-18T14:00+00:00" (sem segundos)
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}[+-]", s):
        s = s[:16] + ":00" + s[16:]
    d = dt.datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def team_results(events: list[dict]) -> dict:
    """{team_id: [ 'V'|'E'|'D', ... ] do mais recente para o mais antigo}."""
    done = sorted((e for e in events if e["terminado"]), key=lambda e: parse_date(e["data"]), reverse=True)
    res: dict[str, list[str]] = {}
    for e in done:
        gc, gf = e["golos_casa"], e["golos_fora"]
        rc = "V" if gc > gf else "D" if gc < gf else "E"
        rf = {"V": "D", "D": "V", "E": "E"}[rc]
        res.setdefault(e["casa_id"], []).append(rc)
        res.setdefault(e["fora_id"], []).append(rf)
    return res


def loss_streak(results: list[str]) -> int:
    n = 0
    for r in results:
        if r != "D":
            break
        n += 1
    return n


# ---------------------------------------------------------------- critérios

def evaluate(fixtures, table, results, cfg) -> list[dict]:
    top_n, bottom_n, min_l = cfg["top_n"], cfg["bottom_n"], cfg["derrotas_minimas"]
    out = []
    for f in fixtures:
        h, a = table.get(f["casa_id"]), table.get(f["fora_id"])
        if not h or not a:
            continue
        crit = []
        if h["grupo"] == a["grupo"]:
            total = h["total"]
            is_top = lambda t: t["posicao"] <= top_n
            is_bot = lambda t: t["posicao"] > total - bottom_n
            if (is_top(h) and is_bot(a)) or (is_top(a) and is_bot(h)):
                fav = "casa" if is_top(h) else "fora"
                crit.append({"tipo": "top_vs_bottom", "favorito": fav,
                             "texto": f"{top_n} primeiros vs {bottom_n} últimos"})
        sh = loss_streak(results.get(f["casa_id"], []))
        sa = loss_streak(results.get(f["fora_id"], []))
        if sh >= min_l and a["posicao"] < h["posicao"]:
            crit.append({"tipo": "serie_derrotas", "equipa": "casa", "derrotas": sh, "favorito": "fora",
                         "texto": f"{f['casa']} com {sh} derrotas seguidas vs melhor classificado"})
        if sa >= min_l and h["posicao"] < a["posicao"]:
            crit.append({"tipo": "serie_derrotas", "equipa": "fora", "derrotas": sa, "favorito": "casa",
                         "texto": f"{f['fora']} com {sa} derrotas seguidas vs melhor classificado"})
        if not crit:
            continue

        def info(t, tid):
            r = results.get(tid, [])
            return {"nome": t["nome"], "posicao": t["posicao"], "total": t["total"], "pontos": t["pontos"],
                    "jogos": t["jogos"], "forma": "".join(r[:5]), "serie_derrotas": loss_streak(r)}

        out.append({
            "id": f["id"],
            "data": f["data"],
            "casa": {**info(h, f["casa_id"]), "nome": f["casa"]},
            "fora": {**info(a, f["fora_id"]), "nome": f["fora"]},
            "criterios": crit,
        })
    return out


# ---------------------------------------------------------------- cotas

_STOP = {"fc", "cf", "sc", "ac", "afc", "cd", "ud", "sd", "rc", "rcd", "sv", "vfb", "vfl", "tsg", "fk", "sk",
         "bk", "if", "ff", "aik", "club", "clube", "de", "da", "do", "futebol", "football", "calcio", "the",
         "as", "ss", "us", "ssc", "acf", "ogc", "losc", "stade", "real", "1", "04", "05", "1899", "1900", "1909",
         "1846", "1907", "1910", "1913", "kv", "krc", "rsc", "royal", "cp", "fsv", "bsc", "hsv", "spvgg"}


def norm_team(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    toks = [t for t in s.split() if t not in _STOP]
    return " ".join(toks) or s.strip()


def team_sim(a: str, b: str) -> float:
    na, nb = norm_team(a), norm_team(b)
    if na == nb:
        return 1.0
    if na and nb and (na in nb or nb in na):
        return 0.9
    ratio = difflib.SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    jacc = len(ta & tb) / max(1, len(ta | tb))
    return max(ratio, jacc)


def match_odds(game: dict, odds_events: list[dict], bookmakers: list[str]) -> dict | None:
    gdate = parse_date(game["data"])
    best, best_score = None, 0.0
    for oe in odds_events:
        try:
            odate = parse_date(oe["commence_time"])
        except (KeyError, ValueError):
            continue
        if abs((odate - gdate).total_seconds()) > 36 * 3600:
            continue
        sc = team_sim(game["casa"]["nome"], oe.get("home_team", "")) + team_sim(game["fora"]["nome"], oe.get("away_team", ""))
        if sc > best_score:
            best, best_score = oe, sc
    if not best or best_score < 1.2:
        return None
    result = {}
    for bm in best.get("bookmakers", []):
        if bm.get("key") not in bookmakers:
            continue
        for m in bm.get("markets", []):
            if m.get("key") != "h2h":
                continue
            o = {}
            for oc in m.get("outcomes", []):
                if oc.get("name") == best.get("home_team"):
                    o["1"] = oc.get("price")
                elif oc.get("name") == best.get("away_team"):
                    o["2"] = oc.get("price")
                elif str(oc.get("name", "")).lower() == "draw":
                    o["X"] = oc.get("price")
            if o:
                result[bm["key"]] = {"titulo": bm.get("title", bm["key"]), "cotas": o,
                                     "atualizado": bm.get("last_update") or m.get("last_update")}
    return result or None


def fetch_odds(sport: str, api_key: str, bookmakers: list[str]) -> list[dict]:
    data, headers = http_json(ODDS_URL.format(sport=sport), {
        "apiKey": api_key, "bookmakers": ",".join(bookmakers), "markets": "h2h", "oddsFormat": "decimal",
    })
    rem = headers.get("x-requests-remaining")
    if rem is not None:
        log(f"    The Odds API: pedidos restantes = {rem}")
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------- execução

def fetch_fixtures(slug: str, start: dt.date, days: int) -> list[dict]:
    """Jogos dos próximos dias. A ESPN só aceita uma data por pedido (intervalos dão 400)."""
    events = []
    for i in range(days + 1):
        d = start + dt.timedelta(days=i)
        data, _ = http_json(ESPN_SCOREBOARD.format(slug=slug), {"dates": f"{d:%Y%m%d}"})
        events.extend(parse_events(data))
    return list({e["id"]: e for e in events}.values())


def fetch_results(slug: str, team_ids) -> list[dict]:
    """Resultados da época, a partir do calendário de cada equipa."""
    events = {}
    for tid in team_ids:
        try:
            data, _ = http_json(ESPN_TEAM_SCHEDULE.format(slug=slug, team=tid))
        except Exception as e:
            log(f"    aviso: calendário da equipa {tid} indisponível ({e})")
            continue
        for e in parse_events(data):
            events[e["id"]] = e
    return list(events.values())


def scan_league(liga: dict, cfg: dict, now: dt.datetime) -> tuple[list[dict], dict]:
    slug = liga["espn"]
    st, _ = http_json(ESPN_STANDINGS.format(slug=slug))
    table = parse_standings(st)
    if not table:
        raise ValueError("classificação vazia (a ESPN não tem a época atual desta liga)")
    results = team_results(fetch_results(slug, table.keys()))
    limit = now + dt.timedelta(days=cfg["dias_a_frente"])
    fixtures = [e for e in fetch_fixtures(slug, now.date(), cfg["dias_a_frente"])
                if e["estado"] == "pre" and now <= parse_date(e["data"]) <= limit
                and "POSTPONED" not in e["estado_nome"]]
    games = evaluate(fixtures, table, results, cfg)
    for g in games:
        g["liga"] = liga["nome"]
        g["pais"] = liga["pais"]
        g["liga_id"] = slug
    resumo = {"equipas": len(table), "jogos_agendados": len(fixtures), "selecionados": len(games),
              "com_resultados": sum(1 for t in table if results.get(t))}
    return games, resumo


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=str(ROOT / "config.json"))
    ap.add_argument("--out", default=str(ROOT.parent / "site" / "data" / "jogos.json"))
    ap.add_argument("--odds", choices=["auto", "sim", "nao"], default="auto",
                    help="auto = obtém cotas se ODDS_API_KEY estiver definida")
    ap.add_argument("--ligas", help="lista de códigos ESPN separados por vírgula (opcional)")
    args = ap.parse_args(argv)

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    ligas = cfg["ligas"]
    if args.ligas:
        wanted = set(args.ligas.split(","))
        ligas = [l for l in ligas if l["espn"] in wanted]
    now = dt.datetime.now(UTC)

    out_path = Path(args.out)
    previous = {}
    if out_path.exists():
        try:
            previous = {g["id"]: g for g in json.loads(out_path.read_text(encoding="utf-8")).get("jogos", [])}
        except (ValueError, KeyError):
            pass

    all_games, estado_ligas = [], []
    for liga in ligas:
        log(f"[{liga['espn']}] {liga['pais']} - {liga['nome']}")
        try:
            games, resumo = scan_league(liga, cfg, now)
            estado_ligas.append({"liga": liga["nome"], "pais": liga["pais"], "ok": True, **resumo})
            all_games.extend(games)
            log(f"    {resumo}")
        except Exception as e:  # uma liga com erro não pode parar o scan
            log(f"    ERRO: {e}")
            estado_ligas.append({"liga": liga["nome"], "pais": liga["pais"], "ok": False, "erro": str(e)[:200]})

    api_key = os.environ.get("ODDS_API_KEY", "").strip()
    want_odds = args.odds == "sim" or (args.odds == "auto" and api_key)
    bookmakers = cfg.get("casas_odds", ["betclic"])
    odds_ok = False
    if want_odds and api_key:
        sports = {}
        for l in ligas:
            if l.get("odds"):
                sports[l["espn"]] = l["odds"]
        needed = sorted({g["liga_id"] for g in all_games if g["liga_id"] in sports})
        for slug in needed:
            log(f"[cotas] {sports[slug]}")
            try:
                oev = fetch_odds(sports[slug], api_key, bookmakers)
                odds_ok = True
            except Exception as e:
                log(f"    ERRO cotas: {e}")
                continue
            for g in all_games:
                if g["liga_id"] == slug:
                    o = match_odds(g, oev, bookmakers)
                    if o:
                        g["cotas"] = o
    # mantém cotas antigas quando não foram atualizadas nesta execução
    for g in all_games:
        if "cotas" not in g and g["id"] in previous and previous[g["id"]].get("cotas"):
            g["cotas"] = previous[g["id"]]["cotas"]
            g["cotas_antigas"] = True

    all_games.sort(key=lambda g: (g["data"], g["pais"], g["liga"]))
    payload = {
        "gerado_em": now.isoformat(timespec="seconds"),
        "cotas_atualizadas": odds_ok,
        "parametros": {k: cfg[k] for k in ("top_n", "bottom_n", "derrotas_minimas", "dias_a_frente")},
        "ligas": estado_ligas,
        "jogos": all_games,
    }
    ok = sum(1 for l in estado_ligas if l["ok"])
    if not ok:
        log("Nenhuma liga foi lida com sucesso: os dados anteriores são mantidos.")
        return 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"Concluído: {len(all_games)} jogos, {ok}/{len(estado_ligas)} ligas OK -> {out_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
