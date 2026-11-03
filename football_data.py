"""Historical results from football-data.co.uk (free CSVs, one file per league and season).

Used by match_facts.py for standings, recent form and head-to-head, always computed
from matches played strictly before the game date so nothing from the future leaks in.
"""
import csv
import io
import os
import re
import urllib.request
from datetime import datetime
from difflib import get_close_matches

BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/{division}.csv"
# SoccerNet league folder -> football-data division code (Champions League is not covered)
DIVISIONS = {
    "england_epl": "E0",
    "spain_laliga": "SP1",
    "italy_serie-a": "I1",
    "germany_bundesliga": "D1",
    "france_ligue-1": "F1",
}
# SoccerNet team name -> football-data team name, for names difflib does not match well
ALIASES = {
    "manchester united": "Man United",
    "manchester utd": "Man United",
    "manchester city": "Man City",
    "newcastle utd": "Newcastle",
    "newcastle united": "Newcastle",
    "west bromwich albion": "West Brom",
    "atletico madrid": "Ath Madrid",
    "atl. madrid": "Ath Madrid",
    "athletic bilbao": "Ath Bilbao",
    "real sociedad": "Sociedad",
    "espanyol": "Espanol",
    "deportivo la coruna": "La Coruna",
    "rayo vallecano": "Vallecano",
    "sporting gijon": "Sp Gijon",
    "bayern munich": "Bayern Munich",
    "borussia dortmund": "Dortmund",
    "b. monchengladbach": "M'gladbach",
    "borussia monchengladbach": "M'gladbach",
    "bayer leverkusen": "Leverkusen",
    "paris saint germain": "Paris SG",
    "paris sg": "Paris SG",
    "inter": "Inter",
    "ac milan": "Milan",
}


def season_code(season):
    """'2015-2016' -> '1516'"""
    start, end = season.split("-")
    return start[-2:] + end[-2:]


def previous_seasons(season, n):
    start = int(season.split("-")[0])
    return [f"{y}-{y + 1}" for y in range(start - n + 1, start + 1)]


def _parse_date(s):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def load_season(division, season, cache_dir):
    """Download (once) and parse one league season. Returns a list of finished matches."""
    os.makedirs(cache_dir, exist_ok=True)
    code = season_code(season)
    path = os.path.join(cache_dir, f"{division}_{code}.csv")
    if not os.path.exists(path):
        url = BASE_URL.format(season=code, division=division)
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()
        with open(path, "wb") as f:
            f.write(data)
    text = open(path, encoding="latin-1").read()
    matches = []
    for row in csv.DictReader(io.StringIO(text)):
        date = _parse_date(row.get("Date", ""))
        if date is None or not row.get("FTHG") or not row.get("FTAG"):
            continue
        matches.append({
            "date": date,
            "season": season,
            "home": row["HomeTeam"],
            "away": row["AwayTeam"],
            "hg": int(row["FTHG"]),
            "ag": int(row["FTAG"]),
        })
    return matches


def _norm(name):
    name = name.lower().replace("fc ", "").replace(" fc", "")
    return re.sub(r"\s+", " ", name).strip()


def match_team(names, candidates):
    """Map a SoccerNet team (list of its known names) to a football-data team name."""
    by_norm = {_norm(c): c for c in candidates}
    for n in names:
        key = _norm(n)
        if key in ALIASES and ALIASES[key] in candidates:
            return ALIASES[key]
        if key in by_norm:
            return by_norm[key]
    for n in names:
        close = get_close_matches(_norm(n), list(by_norm), n=1, cutoff=0.6)
        if close:
            return by_norm[close[0]]
    return None


class LeagueHistory:
    """Results of one league over several seasons, queried relative to a game date."""

    def __init__(self, league_folder, season, cache_dir, n_seasons=5):
        self.division = DIVISIONS.get(league_folder)
        self.season = season
        self.matches = []
        if self.division is None:
            return
        for s in previous_seasons(season, n_seasons):
            try:
                self.matches += load_season(self.division, s, cache_dir)
            except Exception as e:  # missing season or no network: keep what we have
                print(f"football-data: could not load {self.division} {s}: {e}")
        self.matches.sort(key=lambda m: m["date"])

    @property
    def available(self):
        return bool(self.matches)

    def teams(self, season=None):
        season = season or self.season
        return sorted({t for m in self.matches if m["season"] == season for t in (m["home"], m["away"])})

    def standings(self, before):
        """League table of the current season using matches before `before`."""
        table = {t: {"team": t, "played": 0, "won": 0, "drawn": 0, "lost": 0, "gf": 0, "ga": 0, "points": 0}
                 for t in self.teams()}
        for m in self.matches:
            if m["season"] != self.season or m["date"] >= before:
                continue
            for team, gf, ga in ((m["home"], m["hg"], m["ag"]), (m["away"], m["ag"], m["hg"])):
                row = table[team]
                row["played"] += 1
                row["gf"] += gf
                row["ga"] += ga
                if gf > ga:
                    row["won"] += 1
                    row["points"] += 3
                elif gf == ga:
                    row["drawn"] += 1
                    row["points"] += 1
                else:
                    row["lost"] += 1
        rows = sorted(table.values(), key=lambda r: (-r["points"], -(r["gf"] - r["ga"]), -r["gf"], r["team"]))
        for i, r in enumerate(rows, 1):
            r["position"] = i
        return {r["team"]: r for r in rows}

    def form(self, team, before, n=5):
        """Last n league results of `team` before the date, oldest first."""
        games = [m for m in self.matches if m["date"] < before and team in (m["home"], m["away"])][-n:]
        out = []
        for m in games:
            home = m["home"] == team
            gf, ga = (m["hg"], m["ag"]) if home else (m["ag"], m["hg"])
            out.append({"date": m["date"], "opponent": m["away"] if home else m["home"], "home": home,
                        "gf": gf, "ga": ga, "result": "W" if gf > ga else "D" if gf == ga else "L"})
        return out

    def head_to_head(self, team_a, team_b, before, n=5):
        """Last n league meetings between the two teams before the date, oldest first."""
        return [m for m in self.matches
                if m["date"] < before and {m["home"], m["away"]} == {team_a, team_b}][-n:]
