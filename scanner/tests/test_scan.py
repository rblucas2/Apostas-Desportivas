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
