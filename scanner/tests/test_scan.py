import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scan  # noqa: E402

CFG = {"top_n": 3, "bottom_n": 3, "derrotas_minimas": 4}
NAMES = ["Benfica", "Porto", "Sporting CP", "Braga", "Vitória", "Famalicão", "Rio Ave", "Estoril", "AVS", "Tondela"]


def standings_json(order):
    entries = []
    for i, tid in enumerate(order, start=1):
        entries.append({"team": {"id": str(tid), "displayName": NAMES[tid - 1]},
                        "stats": [{"name": "rank", "value": i}, {"name": "points", "value": 30 - i},
                                  {"name": "gamesPlayed", "value": 8}, {"name": "pointDifferential", "value": 10 - i}]})
    return {"children": [{"name": "Liga", "standings": {"entries": entries}}]}


def event(eid, date, home, away, hs=None, as_=None, state="post"):
    comp = lambda tid, side, sc: {"homeAway": side, "team": {"id": str(tid), "displayName": NAMES[tid - 1]},
                                  "score": None if sc is None else str(sc)}
    return {"id": str(eid), "date": date,
            "status": {"type": {"state": state, "completed": state == "post", "name": "STATUS_FULL_TIME"}},
            "competitions": [{"competitors": [comp(home, "home", hs), comp(away, "away", as_)]}]}


class TestScan(unittest.TestCase):
    def setUp(self):
        self.table = scan.parse_standings(standings_json(range(1, 11)))
        # Equipa 7 (Rio Ave) perde 4 seguidas; equipa 5 perde 3 seguidas
        evs = [
            event(1, "2026-09-01T18:00Z", 7, 1, 2, 0),
            event(2, "2026-09-08T18:00Z", 7, 2, 0, 1),
            event(3, "2026-09-15T18:00Z", 3, 7, 2, 1),
            event(4, "2026-09-22T18:00Z", 7, 4, 0, 3),
            event(5, "2026-09-29T18:00Z", 6, 7, 1, 0),
            event(6, "2026-09-29T18:00Z", 5, 6, 0, 1),
            event(7, "2026-09-22T18:00Z", 5, 4, 0, 2),
            event(8, "2026-09-15T18:00Z", 2, 5, 3, 3),
            event(9, "2026-09-08T18:00Z", 5, 3, 0, 1),
        ]
        self.results = scan.team_results(scan.parse_events({"events": evs}))

    def test_standings_positions(self):
        self.assertEqual(self.table["1"]["posicao"], 1)
        self.assertEqual(self.table["10"]["posicao"], 10)
        self.assertEqual(self.table["10"]["total"], 10)

    def test_loss_streak(self):
        self.assertEqual(scan.loss_streak(self.results["7"]), 4)
        self.assertEqual(scan.loss_streak(self.results["5"]), 2)  # o empate interrompe a série
        self.assertEqual(self.results["7"][0], "D")

    def fixtures(self, pairs):
        return scan.parse_events({"events": [event(100 + i, "2026-10-18T15:00Z", h, a, state="pre")
                                             for i, (h, a) in enumerate(pairs)]})

    def test_top_vs_bottom(self):
        games = scan.evaluate(self.fixtures([(10, 1), (2, 9), (3, 8), (4, 10), (1, 7)]),
                              self.table, self.results, CFG)
        tipos = {(g["casa"]["nome"], g["fora"]["nome"]): [c["tipo"] for c in g["criterios"]] for g in games}
        self.assertIn(("Tondela", "Benfica"), tipos)
        self.assertIn(("Porto", "AVS"), tipos)
        self.assertIn(("Sporting CP", "Estoril"), tipos)
        self.assertNotIn(("Braga", "Tondela"), tipos)  # 4.º não é top 3
        self.assertEqual(tipos[("Tondela", "Benfica")], ["top_vs_bottom"])

    def test_losing_streak_vs_better(self):
        games = scan.evaluate(self.fixtures([(7, 1), (7, 9)]), self.table, self.results, CFG)
        self.assertEqual(len(games), 1)  # contra o 9.º (pior classificado) não conta
        c = games[0]["criterios"][0]
        self.assertEqual((c["tipo"], c["equipa"], c["derrotas"], c["favorito"]), ("serie_derrotas", "casa", 4, "fora"))
        self.assertEqual(games[0]["casa"]["forma"], "DDDDV")

    def test_three_losses_not_enough(self):
        cfg = dict(CFG, derrotas_minimas=4)
        res = {"6": ["D", "D", "D", "V"]}
        games = scan.evaluate(self.fixtures([(6, 1)]), self.table, res, cfg)
        self.assertEqual(games, [])

    def test_unranked_fallback(self):
        data = standings_json([3, 1, 2])
        for e in data["children"][0]["standings"]["entries"]:
            e["stats"] = [s for s in e["stats"] if s["name"] != "rank"]
        t = scan.parse_standings(data)
        self.assertEqual(t["3"]["posicao"], 1)

    def test_parse_date_variants(self):
        a = scan.parse_date("2026-10-18T15:00Z")
        b = scan.parse_date("2026-10-18T15:00:00+00:00")
        self.assertEqual(a, b)

    def test_match_odds(self):
        games = scan.evaluate(self.fixtures([(10, 1)]), self.table, self.results, CFG)
        odds = [{"commence_time": "2026-10-18T15:00:00Z", "home_team": "CD Tondela", "away_team": "SL Benfica",
                 "bookmakers": [{"key": "betclic", "title": "Betclic", "last_update": "2026-10-14T10:00:00Z",
                                 "markets": [{"key": "h2h", "outcomes": [
                                     {"name": "CD Tondela", "price": 7.5}, {"name": "SL Benfica", "price": 1.36},
                                     {"name": "Draw", "price": 4.6}]}]}]},
                {"commence_time": "2026-10-18T15:00:00Z", "home_team": "Porto", "away_team": "AVS",
                 "bookmakers": []}]
        o = scan.match_odds(games[0], odds, ["betclic"])
        self.assertEqual(o["betclic"]["cotas"], {"1": 7.5, "2": 1.36, "X": 4.6})

    def test_match_odds_rejects_other_day(self):
        games = scan.evaluate(self.fixtures([(10, 1)]), self.table, self.results, CFG)
        odds = [{"commence_time": "2026-10-25T15:00:00Z", "home_team": "Tondela", "away_team": "Benfica",
                 "bookmakers": []}]
        self.assertIsNone(scan.match_odds(games[0], odds, ["betclic"]))

    def test_team_similarity(self):
        self.assertGreater(scan.team_sim("Sporting CP", "Sporting Lisbon"), 0.6)
        self.assertLess(scan.team_sim("Sporting CP", "Benfica"), 0.5)


if __name__ == "__main__":
    unittest.main()


class TestHistorico(unittest.TestCase):
    BM = ["betclic_fr"]
    NOW = dt.datetime(2026, 10, 15, 12, 0, tzinfo=dt.timezone.utc)

    def jogo(self, gid="100", data="2026-10-18T15:00Z", fav="fora", cotas=None):
        g = {"id": gid, "data": data, "liga": "Liga", "pais": "Portugal", "liga_id": "por.1",
             "casa": {"nome": "Tondela", "posicao": 18, "total": 18},
             "fora": {"nome": "Benfica", "posicao": 1, "total": 18},
             "criterios": [{"tipo": "top_vs_bottom", "favorito": fav}]}
        if cotas:
            g["cotas"] = {"betclic_fr": {"cotas": cotas}}
        return g

    def ev(self, gid="100", data="2026-10-18T15:00Z", hs=0, as_=2, estado="post", nome="STATUS_FULL_TIME"):
        return {"id": gid, "data": data, "estado": estado, "estado_nome": nome, "terminado": estado == "post",
                "golos_casa": hs, "golos_fora": as_}

    def test_regista_e_liquida_vitoria(self):
        h = scan.update_history({}, [self.jogo(cotas={"1": 7.5, "X": 4.6, "2": 1.4})], {"por.1": {}},
                                {"por.1"}, self.BM, self.NOW)
        e = h["jogos"][0]
        self.assertEqual((e["estado"], e["aposta"], e["cota"]), ("pendente", "2", 1.4))
        depois = self.NOW + dt.timedelta(days=4)
        h = scan.update_history(h, [], {"por.1": {"100": self.ev()}}, {"por.1"}, self.BM, depois)
        e = h["jogos"][0]
        self.assertEqual((e["estado"], e["resultado"], e["acertou"], e["lucro"]), ("terminado", "2", True, 0.4))

    def test_derrota_e_empate_perdem_uma_unidade(self):
        for hs, as_ in ((2, 0), (1, 1)):
            h = scan.update_history({}, [self.jogo(cotas={"2": 1.4})], {}, set(), self.BM, self.NOW)
            h = scan.update_history(h, [], {"por.1": {"100": self.ev(hs=hs, as_=as_)}}, {"por.1"}, self.BM,
                                    self.NOW + dt.timedelta(days=4))
            self.assertEqual((h["jogos"][0]["acertou"], h["jogos"][0]["lucro"]), (False, -1.0))

    def test_sem_cota_nao_conta_para_lucro(self):
        h = scan.update_history({}, [self.jogo()], {}, set(), self.BM, self.NOW)
        h = scan.update_history(h, [], {"por.1": {"100": self.ev()}}, {"por.1"}, self.BM,
                                self.NOW + dt.timedelta(days=4))
        self.assertTrue(h["jogos"][0]["acertou"])
        self.assertIsNone(h["jogos"][0]["lucro"])

    def test_mantem_cota_anterior_se_nao_houver_nova(self):
        h = scan.update_history({}, [self.jogo(cotas={"2": 1.5})], {}, set(), self.BM, self.NOW)
        h = scan.update_history(h, [self.jogo()], {"por.1": {}}, {"por.1"}, self.BM, self.NOW)
        self.assertEqual(h["jogos"][0]["cota"], 1.5)

    def test_sai_do_historico_se_deixar_de_cumprir_antes_do_jogo(self):
        h = scan.update_history({}, [self.jogo()], {}, set(), self.BM, self.NOW)
        h = scan.update_history(h, [], {"por.1": {}}, {"por.1"}, self.BM, self.NOW + dt.timedelta(hours=6))
        self.assertEqual(h["jogos"], [])

    def test_liga_com_erro_nao_remove_nem_liquida(self):
        h = scan.update_history({}, [self.jogo()], {}, set(), self.BM, self.NOW)
        h = scan.update_history(h, [], {}, set(), self.BM, self.NOW + dt.timedelta(hours=6))
        self.assertEqual(h["jogos"][0]["estado"], "pendente")

    def test_adiado_fica_anulado(self):
        h = scan.update_history({}, [self.jogo()], {}, set(), self.BM, self.NOW)
        ev = self.ev(estado="post", nome="STATUS_POSTPONED", hs=None, as_=None)
        ev["terminado"] = False
        h = scan.update_history(h, [], {"por.1": {"100": ev}}, {"por.1"}, self.BM, self.NOW + dt.timedelta(days=4))
        self.assertEqual(h["jogos"][0]["estado"], "anulado")

    def test_terminado_nao_e_alterado(self):
        h = scan.update_history({}, [self.jogo(cotas={"2": 1.4})], {}, set(), self.BM, self.NOW)
        h = scan.update_history(h, [], {"por.1": {"100": self.ev()}}, {"por.1"}, self.BM,
                                self.NOW + dt.timedelta(days=4))
        h2 = scan.update_history(h, [self.jogo(cotas={"2": 9.9})], {}, set(), self.BM,
                                 self.NOW + dt.timedelta(days=5))
        self.assertEqual(h2["jogos"][0]["cota"], 1.4)


class TestOrcamento(unittest.TestCase):
    def test_dias_ate_renovacao(self):
        d = dt.date(2026, 10, 14)
        self.assertEqual(scan.days_until_reset(d, 1), 18)        # 14/10 .. 31/10
        self.assertEqual(scan.days_until_reset(d, 14), 31)       # hoje é dia de renovação
        self.assertEqual(scan.days_until_reset(d, 20), 6)
        self.assertEqual(scan.days_until_reset(dt.date(2026, 12, 30), 1), 2)
        self.assertEqual(scan.days_until_reset(d, None), scan.HORIZONTE_SEM_RENOVACAO)

    def test_orcamento_nunca_esgota_antes_da_renovacao(self):
        # simula 60 dias a gastar sempre todo o orçamento disponível, com renovação no dia 1
        st, restantes, dia = {}, 460, dt.date(2026, 10, 14)
        for _ in range(60):
            if dia.day == 1:
                restantes = 500
            st = scan.update_budget_state(st, restantes, dia, 1)
            gasto = st["disponivel_agora"]
            self.assertLessEqual(gasto, restantes)
            restantes -= gasto
            st["gastos_hoje"] += gasto
            st["restantes"] = restantes
            if (dia + dt.timedelta(days=1)).day == 1:
                self.assertGreaterEqual(restantes, 0)
            else:
                self.assertGreater(st["orcamento_hoje"], 0)  # ainda há orçamento todos os dias
            dia += dt.timedelta(days=1)

    def test_sem_dia_conhecido_e_conservador(self):
        st, restantes, dia = {}, 460, dt.date(2026, 10, 14)
        for _ in range(45):  # renovação real só a 14/11, que o código não conhece à partida
            if dia == dt.date(2026, 11, 14):
                restantes = 500
            st = scan.update_budget_state(st, restantes, dia, None)
            self.assertGreater(st["orcamento_hoje"], 0)
            restantes -= st["disponivel_agora"]
            st["gastos_hoje"] += st["disponivel_agora"]
            st["restantes"] = restantes
            dia += dt.timedelta(days=1)
        self.assertEqual(st["dia_renovacao_detetado"], 14)

    def test_varias_execucoes_no_mesmo_dia_respeitam_o_orcamento(self):
        st = scan.update_budget_state({}, 300, dt.date(2026, 10, 14), 1)  # 18 dias -> 16/dia
        self.assertEqual(st["orcamento_hoje"], 16)
        st["gastos_hoje"], st["restantes"] = 10, 290
        st = scan.update_budget_state(st, 290, dt.date(2026, 10, 14), 1)
        self.assertEqual((st["orcamento_hoje"], st["disponivel_agora"]), (16, 6))

    def test_prioridade_das_ligas(self):
        now = dt.datetime(2026, 10, 14, 6, tzinfo=dt.timezone.utc)
        g = lambda liga, horas, cotas=True: {"liga_id": liga, "data": (now + dt.timedelta(hours=horas)).isoformat(),
                                            **({"cotas": {"betclic_fr": {}}} if cotas else {})}
        jogos = [g("a", 100), g("b", 20), g("c", 120, cotas=False), g("d", 10), g("x", 5, cotas=False)]
        sports = {"a": 1, "b": 1, "c": 1, "d": 1}
        recente = {"d": (now - dt.timedelta(hours=2)).isoformat()}
        # a: longe e já com cota -> não; b: perto -> sim; c: sem cota -> sim; d: perto mas consultada há 2 h -> não
        self.assertEqual(scan.leagues_needing_odds(jogos, sports, recente, now), ["b", "c"])


class TestGrupos(unittest.TestCase):
    def test_grupos_diferentes_usam_pontos_por_jogo(self):
        a = {"grupo": "Zona A", "posicao": 8, "pontos": 20, "jogos": 10}
        b = {"grupo": "Zona B", "posicao": 2, "pontos": 15, "jogos": 10}
        self.assertTrue(scan.better(a, b))   # 2,0 pts/jogo > 1,5, apesar de 8.º vs 2.º
        self.assertFalse(scan.better(b, a))
        c = {"grupo": "Zona A", "posicao": 3, "pontos": 18, "jogos": 10}
        self.assertTrue(scan.better(c, a))   # mesmo grupo: conta a posição
