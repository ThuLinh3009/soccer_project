"""Commentary script 2.0 (NO_FLOW_SCRIPT.md): variables, sentence templates and the schedule of the no-flow lines.

Works for any match crawled by fifa_crawl.py (match_info.csv, staff.csv, lineups.csv, form.csv, head_to_head.csv,
standings_before.csv, events.csv). Every line is a template with {variables} filled from that metadata; a template
whose variables are missing is skipped (another variant is used, or the line is dropped).

    ctx = MatchContext(metadata_dir)
    lines = build_schedule(ctx, yes_events, half_lens)   # [Line(half, second, phase, code, text, mandatory)]

The filled template is the fallback line, and the FACT given to the LLM (no_flow_v2.py) to say in its own words.
"""
import csv
import os
import random
import re
import string
from dataclasses import dataclass, field

# ---------------------------------------------------------------- small helpers

WORDS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
         "seventeen eighteen nineteen twenty").split()
TENS = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty"}


def num_word(n):
    n = int(n)
    if n < 20:
        return WORDS[n]
    if n < 60:
        return TENS[n // 10] + ("" if n % 10 == 0 else "-" + WORDS[n % 10])
    return str(n)


ORDINAL_WORDS = ("zeroth first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth "
                 "thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth").split()


def ordinal_word(n):
    """3 -> 'third' (up to 20, then '21st')."""
    n = int(n)
    return ORDINAL_WORDS[n] if n < len(ORDINAL_WORDS) else ordinal(n)


def ordinal(n):
    n = int(n)
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def thousands(v):
    try:
        return f"{int(float(v)):,}"
    except (TypeError, ValueError):
        return ""


def name_list(names):
    names = [n for n in names if n]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1] if names else ""


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def clean_name(s):
    return (s or "").replace("™", "").strip()


def game_minute(half, second):
    """FIFA style: 34:00 into the 2nd half = 79'."""
    minute = max(1, second // 60)
    if half == 1:
        return f"{minute}'" if minute <= 45 else f"45'+{minute - 45}'"
    minute += 45
    return f"{minute}'" if minute <= 90 else f"90'+{minute - 90}'"


def minute_words(minute):
    """79' -> 'the 79th minute', 90'+6' -> 'the 6th minute of stoppage time'."""
    m = re.match(r"(\d+)'(?:\+(\d+)')?", minute or "")
    if not m:
        return ""
    return f"the {ordinal(m.group(2))} minute of stoppage time" if m.group(2) else f"the {ordinal(m.group(1))} minute"


def next_stage(stage):
    s = (stage or "").lower()
    for key, nxt in (("32", "Round of 16"), ("16", "quarter-finals"), ("quarter", "semi-finals"), ("semi", "Final")):
        if key in s:
            return nxt
    return ""


# ---------------------------------------------------------------- match context

GOAL_TYPES = {"Goal!", "Penalty Goal", "Own goal"}
NEWS_TYPES = GOAL_TYPES | {"Penalty Awarded", "Penalty Missed", "Yellow card", "Red card", "Second yellow card",
                           "Substitution", "VAR", "Assist"}


@dataclass
class Goal:
    half: int
    second: int
    minute: str
    player: str
    side: str  # home / away: the team the goal counts for
    kind: str  # goal / pen / og
    home: int
    away: int


class MatchContext:
    def __init__(self, metadata_dir):
        d = metadata_dir
        self.info = {r["field"]: r["value"] for r in read_csv(os.path.join(d, "match_info.csv"))}
        self.staff = read_csv(os.path.join(d, "staff.csv"))
        self.lineups = read_csv(os.path.join(d, "lineups.csv"))
        self.form = read_csv(os.path.join(d, "form.csv"))
        self.h2h = read_csv(os.path.join(d, "head_to_head.csv"))
        self.standings = read_csv(os.path.join(d, "standings_before.csv"))
        self.events = []
        for r in read_csv(os.path.join(d, "events.csv")):
            if not r.get("half"):  # half-time rows (no time): before the second half
                if r.get("period") == "4":
                    r = dict(r, half="2", second="0", minute="45'")
                else:
                    continue
            r["half"], r["second"] = int(r["half"]), int(float(r["second"] or 0))
            self.events.append(r)
        self.events.sort(key=lambda r: (r["half"], r["second"]))
        self.home, self.away = self.info.get("home_team", ""), self.info.get("away_team", "")
        comp = self.info.get("competition", "")
        self.gender = "women" if re.search(r"women|wsl|féminine|frauen", comp, re.I) else "men"
        self.kind = self._kind()
        self.goals = self._goals()
        self.base = self._base_vars()

    # ---------------- static facts
    def _kind(self):
        i = self.info
        if i.get("matchday"):
            return "league"
        if i.get("group"):
            return "group"
        if (i.get("stage") or "").strip().lower() == "final":
            return "final"
        return "knockout" if next_stage(i.get("stage")) else "other"

    def coach(self, side):
        for r in self.staff:
            if r.get("side") == side and r.get("role") == "head_coach":
                return r["name"]
        return ""

    def captain(self, side):
        for r in self.lineups:
            if r.get("side") == side and r.get("captain") == "True":
                return r["name"]
        return ""

    def players(self, side, role="starter"):
        return [r for r in self.lineups if r.get("side") == side and r.get("role") == role]

    def form_of(self, team):
        rows = sorted((r for r in self.form if r.get("team") == team), key=lambda r: r.get("date", ""))[-5:]
        return " ".join(r["result"] for r in rows), sum(r["result"] == "W" for r in rows), len(rows)

    def standing(self, team):
        for r in self.standings:
            if r.get("team") == team:
                return ordinal(r["position"]), r.get("Pts", "")
        return "", ""

    def _base_vars(self):
        i, v = self.info, {}
        v.update(competition=clean_name(i.get("competition")), season=clean_name(i.get("season")),
                 stage=i.get("stage", ""), group=i.get("group", ""), matchday=i.get("matchday", ""),
                 stadium=i.get("stadium", ""), city=i.get("city", ""), referee=i.get("referee", ""),
                 attendance=thousands(i.get("attendance")), capacity=thousands(i.get("capacity")),
                 stadium_built=i.get("stadium_built", ""), home_team=self.home, away_team=self.away,
                 home_tactics=i.get("home_tactics", ""), away_tactics=i.get("away_tactics", ""),
                 home_coach=self.coach("home"), away_coach=self.coach("away"),
                 home_captain=self.captain("home"), away_captain=self.captain("away"),
                 next_stage=next_stage(i.get("stage")), pronoun="she" if self.gender == "women" else "he")
        v["matchday_word"] = num_word(v["matchday"]) if v["matchday"].isdigit() else ""
        v["round_phrase"] = (f"matchday {v['matchday_word']}" if v["matchday_word"] else
                             f"Group {v['group']}" if v["group"] else v["stage"])
        for side, team in (("home", self.home), ("away", self.away)):
            form, wins, n = self.form_of(team)
            v[f"{side}_form"] = form if n == 5 else ""
            v[f"{side}_wins_last5"] = num_word(wins) if n == 5 else ""
            v[f"{side}_position"], v[f"{side}_points"] = self.standing(team)
        rows = [r for r in self.h2h if r.get("team") == self.home]
        if rows:
            v.update(h2h_count=len(rows), h2h_home_wins=sum(r["result"] == "W" for r in rows),
                     h2h_away_wins=sum(r["result"] == "L" for r in rows),
                     h2h_draws=sum(r["result"] == "D" for r in rows))
        return v

    # ---------------- goals and score
    def _goals(self):
        goals, home, away = [], 0, 0
        for r in self.events:
            if r["type_name"] not in GOAL_TYPES or r.get("home_goals", "") == "":
                continue
            h, a = int(r["home_goals"]), int(r["away_goals"])
            if (h, a) == (home, away):  # same goal listed twice
                continue
            side = "home" if h > home else "away"
            kind = {"Penalty Goal": "pen", "Own goal": "og"}.get(r["type_name"], "goal")
            goals.append(Goal(r["half"], r["second"], r.get("minute", ""), r.get("player", ""), side, kind, h, a))
            home, away = h, a
        return goals

    def score(self, half, second):
        home = away = 0
        for g in self.goals:
            if (g.half, g.second) <= (half, second):
                home, away = g.home, g.away
        return home, away

    def scorers(self, half=9, second=10 ** 6):
        by_player = {}
        for g in self.goals:
            if (g.half, g.second) > (half, second):
                continue
            team = self.home if g.side == "home" else self.away
            key = (g.player, team, g.kind == "og")
            by_player.setdefault(key, []).append(g.minute + (" pen" if g.kind == "pen" else ""))
        parts = [f"{p} {', '.join(ms)}{' own goal' if og else ''} ({team})" for (p, team, og), ms in by_player.items()]
        return "; ".join(parts)

    def vars_at(self, half, second):
        v = dict(self.base)
        h, a = self.score(half, second)
        v.update(home_goals=h, away_goals=a, score=f"{self.home} {h}, {self.away} {a}",
                 minute=game_minute(half, second), margin=num_word(abs(h - a)),
                 lead_score=f"{max(h, a)}-{min(h, a)}", scorers=self.scorers(half, second))
        if h != a:
            v["leader"], v["trailer"] = (self.home, self.away) if h > a else (self.away, self.home)
            v["score_phrase"] = f"{v['leader']} lead {v['lead_score']}"
        else:
            v["leader"] = v["trailer"] = ""
            v["score_phrase"] = "still goalless" if h == 0 else f"all square at {v['lead_score']}"
        v["state"] = ("nil" if h == a == 0 else "draw" if h == a else "lead1" if abs(h - a) == 1 else "lead2")
        v["winner"], v["loser"] = v["leader"], v["trailer"]
        return v


# ---------------------------------------------------------------- templates (NO_FLOW_SCRIPT.md, section 2)
# code -> [(condition, template)]; condition: None (always) or a function of the variables

def kind_is(*kinds):
    return lambda v: v["kind"] in kinds


def state_is(*states):
    return lambda v: v["state"] in states


TEMPLATES = {
    "A1": [
        (kind_is("league"), "Hello and welcome to {stadium} in {city} for this {competition} matchday {matchday_word} "
                            "clash between {home_team} and {away_team}."),
        (kind_is("league"), "Welcome to {stadium}, {city}, where {home_team} host {away_team} on matchday "
                            "{matchday_word} of the {competition}."),
        (kind_is("group"), "Hello and welcome to {stadium} in {city} for this {competition} Group {group} match "
                           "between {home_team} and {away_team}."),
        (kind_is("knockout"), "Hello and welcome to {stadium} in {city} for this {competition} {stage} tie between "
                              "{home_team} and {away_team}."),
        (kind_is("knockout"), "Welcome to {stadium}, {city}: it's {home_team} against {away_team} in the {stage} of "
                              "the {competition}."),
        (kind_is("final"), "Hello and welcome to {stadium} in {city} for the {competition} Final between {home_team} "
                           "and {away_team}."),
        (None, "Hello and welcome to {stadium} for this {competition} {round_phrase} match between {home_team} and "
               "{away_team}."),
        (None, "Hello and welcome to this {competition} match between {home_team} and {away_team}."),
    ],
    "A2": [
        (None, "It's {home_coach}'s {home_team} against {away_coach}'s {away_team}."),
        (None, "{home_team}, led by {home_coach}, take on {away_coach}'s {away_team}."),
        (None, "{home_team} take on {away_team}."),
    ],
    "A3": [
        (kind_is("knockout"), "It's knockout football: the winner goes through to the {next_stage}."),
        (kind_is("knockout"), "Win today and you're in the {next_stage}; lose and you go home."),
        (kind_is("final"), "One game for the trophy: the winner is crowned {competition} champion."),
        (kind_is("group"), "{home_team} have {home_points} points in Group {group}, {away_team} have {away_points}."),
        (lambda v: v["kind"] == "league" and v["matchday"] == "1",
         "It's the opening day of the season, and both sides want to start with three points."),
        (lambda v: v["kind"] == "league" and v["matchday"] != "1",
         "{home_team} start the day {home_position} on {home_points} points, {away_team} are {away_position} on "
         "{away_points}."),
    ],
    # optional background, once per half each (section 2, "Tuỳ chọn")
    "form_home": [(None, "{home_team} have won {home_wins_last5} of their last five games.")],
    "form_away": [(None, "{away_team}'s last five results read {away_form}.")],
    "h2h": [(None, "These two sides have met {h2h_count} times: {h2h_home_wins} wins for {home_team}, "
                   "{h2h_away_wins} for {away_team} and {h2h_draws} draws.")],
    "tactics": [(None, "{home_team} line up in a {home_tactics}, {away_team} in a {away_tactics}.")],
    "captains": [(None, "{home_captain} captains {home_team}, {away_captain} leads {away_team}.")],
    "referee": [(None, "{referee} is the referee today.")],
    "attendance": [(None, "The attendance today is {attendance}.")],
    "stadium": [(None, "{stadium}, built in {stadium_built}, holds {capacity} spectators.")],
    # score update (B2)
    "B2": [
        (state_is("nil"), "Still goalless here between {home_team} and {away_team}."),
        (state_is("nil"), "No goals yet: {score}."),
        (state_is("draw"), "All square at {lead_score}."),
        (state_is("draw"), "It's level, {score}."),
        (state_is("lead1"), "{leader} lead {lead_score}."),
        (state_is("lead1"), "{score}, {leader} just in front."),
        (state_is("lead2"), "{leader} are {margin} goals to the good, {score}."),
    ],
    "C1": [
        (state_is("nil"), "The referee blows for half-time, and it's goalless: {score}."),
        (state_is("nil"), "Half-time here, no goals yet between {home_team} and {away_team}."),
        (state_is("draw"), "Half-time, and it's all square: {score}."),
        (state_is("lead1", "lead2"), "That's half-time. {leader} lead {lead_score}."),
        (state_is("lead1", "lead2"), "The whistle goes for the break with {leader} in front, {score}."),
    ],
    "C1b": [(lambda v: bool(v["scorers"]), "The goals so far: {scorers}.")],
    "C2": [(None, "Stay with us, the second half is coming up."),
           (None, "Don't go anywhere, we'll be back for the second half.")],
    "D1": [(None, "The second half is under way. {score}."),
           (None, "We're back under way for the second half, {score_phrase}.")],
    "F1": [
        (state_is("nil", "draw"), "Ten minutes to go, and it's still level: {score}."),
        (state_is("lead1"), "Ten minutes left. {leader} lead {lead_score}; can {trailer} find a reply?"),
        (state_is("lead2"), "Ten minutes to go, and {leader} lead {lead_score}."),
    ],
    "F2": [
        (state_is("nil", "draw"), "We're into stoppage time, and it's {score}."),
        (state_is("lead1"), "Into stoppage time: {leader} lead {lead_score}, and {trailer} are running out of time."),
        (state_is("lead2"), "Into stoppage time now, {score}."),
    ],
    "G1": [
        (state_is("lead1", "lead2"), "That's full-time! {score}."),
        (state_is("lead1", "lead2"), "The final whistle goes: {winner} win {lead_score}."),
        (state_is("nil"), "Full-time, and it finishes goalless: {score}."),
        (state_is("draw"), "Full-time, and the points are shared: {score}."),
    ],
    "G2": [(lambda v: bool(v["scorers"]), "The goals: {scorers}.")],
    "G3": [
        (lambda v: v["kind"] == "knockout" and v["winner"], "{winner} are through to the {next_stage}; {loser} are out."),
        (lambda v: v["kind"] == "final" and v["winner"], "{winner} are the {competition} champions!"),
        (lambda v: v["kind"] == "group" and v["winner"], "{winner} take the three points in Group {group}."),
        (lambda v: v["kind"] == "group" and not v["winner"], "A point each in Group {group}."),
        (lambda v: v["kind"] == "league" and v["winner"], "{winner} take the three points on matchday {matchday_word}."),
        (lambda v: v["kind"] == "league" and not v["winner"], "The points are shared on matchday {matchday_word}."),
    ],
    "G4": [(None, "Thanks for joining us from {stadium}. Goodbye."),
           (None, "That's all from {city}. Thank you for watching, and goodbye.")],
    "H1": [(None, "It's {score} after ninety minutes, so we're going to extra time.")],
}

PHASE_OF = {"A1": "welcome", "A2": "teams", "A3": "stakes", "B2": "score_update", "C1": "half_time",
            "C1b": "half_time", "C2": "half_time", "D1": "second_half", "D2": "second_half", "F1": "late_game",
            "F2": "late_game", "G1": "full_time", "G2": "full_time", "G3": "full_time", "G4": "full_time",
            "H1": "extra_time", "B1": "live_news"}
OPTIONAL = ["form_home", "form_away", "h2h", "tactics", "captains", "referee", "attendance", "stadium",
            "lineup_home", "lineup_away", "bench_home", "bench_away", "numbers_home", "numbers_away"]


def fill(template, v):
    """Template with every {field} filled, or None if a field is missing or empty."""
    fields = [f for _, f, _, _ in string.Formatter().parse(template) if f]
    if any(v.get(f) in (None, "") for f in fields):
        return None
    return template.format(**v)


def render(code, v, rng):
    """A filled variant: the ones made for this kind of match / score first, the generic ones (no condition) only
    when none of them can be filled."""
    specific = [fill(t, v) for cond, t in TEMPLATES.get(code, []) if cond is not None and cond(v)]
    specific = [o for o in specific if o]
    if specific:
        return rng.choice(specific)
    generic = [o for o in (fill(t, v) for cond, t in TEMPLATES.get(code, []) if cond is None) if o]
    return rng.choice(generic) if generic else None


# ---------------------------------------------------------------- live news (B1) from events.csv

def news_line(ctx, rows, half, second):
    """One sentence for all the FIFA events of the same minute (goal first)."""
    v = ctx.vars_at(half, second)
    by_type = {}
    for r in rows:
        by_type.setdefault(r["type_name"], []).append(r)
    minute = rows[0].get("minute") or game_minute(half, second)
    when = minute_words(minute)
    goal = next((g for g in ctx.goals if (g.half, g.second) == (half, second)), None)
    if goal:
        team = ctx.home if goal.side == "home" else ctx.away
        if goal.kind == "og":
            text = f"An own goal from {goal.player}, and it counts for {team}. {v['score']}."
        elif goal.kind == "pen":
            text = f"{goal.player} scores from the penalty spot for {team} in {when}! {v['score']}."
        else:
            assist = [r["player"] for r in by_type.get("Assist", []) if r.get("player")]
            text = (f"Goal for {team}! {goal.player} scores, set up by {assist[0]}, in {when}. {v['score']}."
                    if assist else f"Goal! {goal.player} scores for {team} in {when}. {v['score']}.")
        return "goal", text
    parts = []
    for r in by_type.get("Red card", []) + by_type.get("Second yellow card", []):
        parts.append(f"{r['player']} is sent off! {r['team']} are down to ten.")
    if "Penalty Awarded" in by_type:
        r = by_type["Penalty Awarded"][0]
        parts.append(f"Penalty to {r['team']}!" if r.get("team") else "Penalty!")
    if "Penalty Missed" in by_type:
        parts.append(f"{by_type['Penalty Missed'][0]['player']} misses the penalty! It stays {v['score']}.")
    for r in by_type.get("VAR", []):
        if r.get("description"):
            parts.append(f"The referee checks with VAR: {r['description'].rstrip('.').lower()}.")
    yellows = [r for r in by_type.get("Yellow card", []) if r.get("player")]
    if yellows:
        parts.append(name_list([f"{r['player']} ({r['team']})" for r in yellows]) +
                     (" is" if len(yellows) == 1 else " are") + " shown a yellow card.")
    subs = by_type.get("Substitution", [])
    for team in dict.fromkeys(r["team"] for r in subs):
        pairs = [f"{r['player']} comes on for {r['player_off']}" for r in subs if r["team"] == team and r["player_off"]]
        if pairs:
            label = "Change" if len(pairs) == 1 else "Double change" if len(pairs) == 2 else "Changes"
            when_txt = "at the break" if half == 2 and second == 0 else ""
            parts.append(f"{label} for {team}{' ' + when_txt if when_txt else ''}: {'; '.join(pairs)}.")
    if not parts:
        return None, None
    topic = ("card" if yellows or "Red card" in by_type or "Second yellow card" in by_type
             else "substitution" if subs else "penalty")
    return topic, " ".join(parts)


# ---------------------------------------------------------------- lines and schedule

@dataclass
class Line:
    half: int
    second: float
    code: str
    text: str
    mandatory: bool
    phase: str = ""
    topic: str = ""
    vars: dict = field(default_factory=dict, repr=False)

    slot: float = 0.0  # seconds until the next line (time_slots), set by no_flow_v2.py
    after: str = ""  # code of the line this one follows in a chain (A1 -> A2 -> A3...): said right after it

    def __post_init__(self):
        self.phase = self.phase or PHASE_OF.get(self.code, "background")
        self.topic = self.topic or self.code


WORDS_PER_SECOND = 2.6  # spoken words per second (English TV commentary; measured on Gemini TTS: 2.4-3.2).
# For Vietnamese a "word" is a syllable (split by spaces): about 4-5 per second. no_flow_v2.py --wps sets it.
LEAD = 0.5  # seconds of silence a TTS clip has before / after the words


def word_count(text):
    return len(re.findall(r"\S+", text or ""))


def speech_len(text):
    return 1.0 + word_count(text) / WORDS_PER_SECOND


def max_words(slot, wps=None):
    """Words that can be spoken in `slot` seconds."""
    return max(0, int((slot - LEAD) * (wps or WORDS_PER_SECOND)))


def time_slots(starts, half_lens, gap=0.3):
    """starts: [(half, second)] of every line that will be spoken (yes and no).
    -> {(half, second): seconds from this line to the next one, minus `gap`} (last line: to the end of the half)."""
    slots = {}
    for half in sorted({h for h, _ in starts}):
        times = sorted({s for h, s in starts if h == half})
        end = half_lens[half - 1] if half - 1 < len(half_lens) else times[-1] + 60
        for t, nxt in zip(times, times[1:] + [end]):
            slots[(half, t)] = max(0.0, nxt - t - gap)
    return slots


def end_time(ctx, half):
    for r in ctx.events:
        if r["half"] == half and r["type_name"] == "End Time":
            return r["second"]
    return None


def optional_text(ctx, code, v, rng, said_players):
    if code.startswith(("lineup_", "bench_", "numbers_")):
        kind, side = code.split("_")
        team = ctx.home if side == "home" else ctx.away
        if kind == "bench":
            names = [r["name"] for r in ctx.players(side, "substitute")][:5]
            return f"On the {team} bench: {name_list(names)}." if len(names) >= 3 else None
        pool = [r for r in ctx.players(side) if r["name"] not in said_players]
        if kind == "lineup":
            pool = [r for r in pool if r.get("position") != "GK"]
        group = pool[:4] if kind == "lineup" else pool[:3]
        if len(group) < 3:
            return None
        said_players.update(r["name"] for r in group)
        if kind == "lineup":
            return f"In the {team} line-up: {name_list([r['name'] for r in group])}."
        return f"For {team}, " + name_list([f"{r['name']} wears {r['shirt_number']}" for r in group]) + "."
    return render(code, v, rng)


def build_schedule(ctx, yes_events, half_lens, seed=0, after_event=15, before_event=10, min_gap=45,
                   score_every=600, score_quiet=180, optional_gap=120, goal_quiet=120, live_delay=30):
    """Lines of the no flow, sorted by time. yes_events: [(half, second, text)] of the yes flow.

    Mandatory lines are placed first (moved later to the first free spot, at most a short delay; if there is none
    they keep their time and the yes comments they overlap are muted). Optional lines fill the long gaps.
    Returns (lines, muted): muted = set of (half, second) of yes comments covered by a mandatory line.
    """
    rng = random.Random(seed)
    lines, muted = [], set()
    base_kind = ctx.kind

    def V(half, second):
        v = ctx.vars_at(half, second)
        v["kind"] = base_kind
        return v

    def busy(half):
        spans = [(s - before_event, s + speech_len(t) + 2) for h, s, t in yes_events
                 if h == half and (h, s) not in muted]
        spans += [(l.second - 2, l.second + speech_len(l.text) + 2) for l in lines if l.half == half]
        return sorted(spans)

    def place(half, t, text, max_delay):
        dur, limit = speech_len(text), half_lens[half - 1] - 1
        t = min(t, max(0, limit - dur))
        for cand in range(int(t), int(min(t + max_delay, limit - dur)) + 1):
            if all(cand + dur <= a or cand >= b for a, b in busy(half)):
                return float(cand)
        for h, s, txt in yes_events:  # no free spot: mandatory line wins, mute the yes comments under it
            if h == half and s < t + dur and s + speech_len(txt) > t:
                muted.add((h, s))
        return float(t)

    def add(half, t, code, text, max_delay=60, topic=""):
        if text:
            lines.append(Line(half, place(half, t, text, max_delay), code, text, True, topic=topic,
                              vars=V(half, t)))
            return lines[-1]

    def chain(half, t, codes, max_delay=60):
        prev = ""
        for code in codes:
            text = render(code, V(half, t), rng)
            line = add(half, t, code, text, max_delay)
            if line:
                line.after, prev = prev, code
                t = line.second + speech_len(line.text) + 0.5

    # A: opening (half 1, from second 5)
    chain(1, 5, ["A1", "A2", "A3"], max_delay=90)

    # B1: live news at the FIFA minute (grouped by minute)
    groups = {}
    for r in ctx.events:
        if r["type_name"] in NEWS_TYPES and r["half"] in (1, 2):
            groups.setdefault((r["half"], r["second"]), []).append(r)
    for (half, second), rows in sorted(groups.items()):
        topic, text = news_line(ctx, rows, half, second)
        if text and second < half_lens[half - 1]:
            add(half, second + (5 if second == 0 else 0), "B1", text, live_delay, topic=topic)
    for r in ctx.events:  # hydration breaks
        if r["type_name"] == "Delay" and r["half"] in (1, 2) and "hydration" in (r.get("description") or "").lower():
            add(r["half"], r["second"], "B3", "A short break for the players to take on water.", 60, topic="break")

    # C: half-time, D: second half, F: late game, G / H: full time
    ht = end_time(ctx, 1) or half_lens[0] - 30
    chain(1, min(ht, half_lens[0] - 30), ["C1", "C1b", "C2"], max_delay=20)
    chain(2, 5, ["D1"], max_delay=60)
    if half_lens[1] > 35 * 60 + 30:
        chain(2, 35 * 60, ["F1"], max_delay=60)
    if half_lens[1] > 45 * 60 + 30:
        chain(2, 45 * 60, ["F2"], max_delay=60)
    ft = end_time(ctx, 2) or half_lens[1] - 60
    extra_time = any(r["half"] in (3, 4, 5) for r in ctx.events)
    final_codes = ["H1"] if extra_time else ["G1", "G2", "G3", "G4"]
    chain(2, min(ft, half_lens[1] - 60), final_codes, max_delay=20)

    # B2: score update every ~10 minutes when no line gave the score recently
    for half in (1, 2):
        t = 600
        while t < half_lens[half - 1] - 120:
            last_score = max([l.second for l in lines if l.half == half and l.second <= t + 120 and
                              (l.code in ("B2", "C1", "D1", "F1", "F2") or l.topic == "goal")] + [-1e9])
            if t - last_score >= score_every - 60:
                text = render("B2", V(half, t), rng)
                line = add(half, t, "B2", text, 120)
                t = (line.second if line else t) + score_every
            else:
                t = last_score + score_every

    # optional background in the long gaps
    said_players, used = set(), {}  # each background topic once per match (line-up / numbers: twice)
    for half in (1, 2):
        t = 20.0
        while t < half_lens[half - 1] - optional_gap:
            spans = busy(half)
            nxt = min([a for a, b in spans if a > t] + [half_lens[half - 1]])
            inside = [b for a, b in spans if a <= t < b]
            if inside:
                t = max(inside) + 1
                continue
            free = nxt - t
            prev_lines = sorted((l for l in lines if l.half == half and l.second < t), key=lambda l: l.second)
            last_no = prev_lines[-1].second if prev_lines else -1e9
            last_goal = max([l.second for l in prev_lines if l.topic == "goal"] + [-1e9])
            if free >= optional_gap and t - last_no >= min_gap and t - last_goal >= goal_quiet:
                recent = [l.topic for l in prev_lines[-2:]]
                for code in OPTIONAL:
                    limit = 2 if code.startswith(("numbers_", "lineup_")) else 1
                    topic = code.split("_")[0]
                    if used.get(code, 0) >= limit or (len(recent) == 2 and recent[0] == recent[1] == topic):
                        continue
                    text = optional_text(ctx, code, V(half, t), rng, said_players)
                    if text and after_event + speech_len(text) + before_event <= free:
                        lines.append(Line(half, t + after_event, code, text, False, topic=topic,
                                          vars=V(half, t)))
                        used[code] = used.get(code, 0) + 1
                        break
                else:
                    t = nxt
                    continue
                t = lines[-1].second + speech_len(lines[-1].text) + min_gap
            else:
                t = nxt + 1
    lines.sort(key=lambda l: (l.half, l.second))
    return lines, muted


# ---------------------------------------------------------------- continuous commentary (v5.5)
# The no flow talks without stopping: every silence between two lines (yes or no) is filled with lines made from the
# metadata (players, units, coaches, form, head to head, venue, score and clock, recap of goals / cards / changes).

POSITION_WORDS = {"GK": "in goal", "DF": "in defence", "MF": "in midfield", "FW": "up front"}
UNIT_TEXT = {"DF": ["{team}'s back line: {names}.", "In defence for {team}: {names}."],
             "MF": ["In the {team} midfield: {names}.", "{team}'s midfield today: {names}."],
             "FW": ["Up front for {team}: {names}.", "Leading the line for {team}: {names}."]}
MONTHS = "January February March April May June July August September October November December".split()


def month_year(date):
    m = re.match(r"(\d{4})-(\d{2})", date or "")
    return f"{MONTHS[int(m.group(2)) - 1]} {m.group(1)}" if m else ""


def result_text(team, r, when=True):
    """One form / head-to-head row: 'Chelsea beat Crystal Palace 4-0 at home in April 2025.'"""
    try:
        gf, ga = int(r["goals_for"]), int(r["goals_against"])
    except (KeyError, ValueError):
        return None
    venue = {"home": " at home", "away": " away"}.get(r.get("venue", ""), "")
    date = f" in {month_year(r.get('date'))}" if when and month_year(r.get("date")) else ""
    opp = r.get("opponent", "")
    if not opp:
        return None
    if gf > ga:
        return f"{team} beat {opp} {gf}-{ga}{venue}{date}."
    if gf < ga:
        return f"{team} lost {ga}-{gf} to {opp}{venue}{date}."
    return f"{team} drew {gf}-{ga} with {opp}{venue}{date}."


@dataclass
class FillItem:
    key: str
    category: str
    variants: list
    uses: int = 0
    last: float = -1e9  # time of the last use (half * 10000 + second)


class Filler:
    """Lines to fill a silence of a given length, chosen so that the topics take turns and nothing is repeated
    soon. Static items (players, units, team facts, form, head to head, venue) are used once each first; when they
    are all used, the least recently used one comes back (after `reuse_after` seconds) with its next wording.
    Dynamic items (score, clock, recap) are made from the time of the line."""

    COOLDOWN = {"stats": 40, "score": 100, "clock": 300, "recap": 150, "player": 0, "unit": 45, "team": 45,
                "form": 45, "h2h": 60, "venue": 90, "bench": 90}
    ORDER = ["player", "team", "unit", "stats", "form", "venue", "h2h", "bench", "recap", "score", "clock"]
    # what the yes flow (or the FIFA stand-in) saw, counted per half: kind -> (keywords, singular, plural)
    ACTIONS = {"corner": (r"corner", "corner", "corners"), "foul": (r"\bfoul", "foul", "fouls"),
               "shot": (r"\bshot|attempt|effort|strike|header", "attempt on goal", "attempts on goal"),
               "save": (r"\bsave", "save", "saves"), "free_kick": (r"free[- ]kick", "free kick", "free kicks"),
               "offside": (r"offside", "offside", "offsides"), "yellow": (r"yellow card|booked", "yellow card",
                                                                          "yellow cards")}
    MIN_REUSE = 180  # a static item is never said twice within 3 minutes

    def __init__(self, ctx, yes_events=(), reuse_after=900, seed=0):
        self.ctx, self.reuse_after = ctx, reuse_after
        self.rng = random.Random(seed)
        self.items = self._static_items()
        self.last_cat = {c: -1e9 for c in self.COOLDOWN}
        self.last_cat.update(score=10000, clock=10000)  # not right after the welcome
        self.recap_last = {}
        self.yes = sorted((h, s, self.action_of(t)) for h, s, t in yes_events)
        self.stats_said = {}  # (half, kind) -> count already said

    @classmethod
    def action_of(cls, text):
        t = (text or "").lower()
        for kind, (pattern, _, _) in cls.ACTIONS.items():
            if re.search(pattern, t):
                return kind
        return ""

    def _stats(self, half, second, prefer=""):
        """'That's the third corner of the half.' from the yes events said before this time (counts that changed
        since they were last said). prefer: the kind of the yes event just said goes first."""
        counts = {}
        for h, s, kind in self.yes:
            if h == half and s < second and kind:
                counts[kind] = counts.get(kind, 0) + 1
        kinds = sorted(counts, key=lambda k: (k != prefer, -counts[k]))
        out = []
        for kind in kinds:
            n = counts[kind]
            if n < 2 or self.stats_said.get((half, kind)) == n:
                continue
            _, one, many = self.ACTIONS[kind]
            name = "first" if half == 1 else "second"
            out.append(((half, kind), n, [f"That's the {ordinal_word(n)} {one} of the {name} half.",
                                          f"{num_word(n).capitalize()} {many} so far in this half.",
                                          f"{num_word(n).capitalize()} {many} in the {name} half now."]))
        return out

    # ---------------- static items
    def _static_items(self):
        ctx, items = self.ctx, []
        sides = [("home", ctx.home), ("away", ctx.away)]

        def add(key, cat, *variants):
            variants = [v for v in variants if v]
            if variants:
                items.append(FillItem(key, cat, variants))

        starters = {side: ctx.players(side) for side, _ in sides}
        for i in range(max(len(p) for p in starters.values()) if starters else 0):  # home and away take turns
            for side, team in sides:
                if i >= len(starters[side]):
                    continue
                r = starters[side][i]
                name, n, pos = r["name"], r.get("shirt_number", ""), POSITION_WORDS.get(r.get("position", ""), "")
                add(f"player:{name}", "player",
                    f"{name} wears number {n} for {team}." if n else None,
                    f"Number {n} for {team} is {name}." if n else None,
                    f"{name} plays {pos} for {team}." if pos else None)
        for side, team in sides:
            cap, coach = ctx.captain(side), ctx.coach(side)
            tactics = ctx.info.get(f"{side}_tactics", "")
            if cap:
                add(f"captain:{side}", "team", f"{cap} wears the captain's armband for {team}.",
                    f"{team} are captained by {cap}.")
            if coach:
                add(f"coach:{side}", "team", f"{coach} is the {team} head coach.", f"{team} are coached by {coach}.")
            if tactics:
                add(f"tactics:{side}", "team", f"{team} set up in a {tactics}.", f"{team}'s formation today: {tactics}.")
            pos, pts = ctx.standing(team)
            if pos and pts:
                add(f"table:{side}", "team", f"{team} started the day {pos} on {pts} points.")
            for code, texts in UNIT_TEXT.items():
                names = [r["name"] for r in starters[side] if r.get("position") == code]
                if len(names) >= 2:
                    add(f"unit:{side}:{code}", "unit", *[t.format(team=team, names=name_list(names)) for t in texts])
            subs = [r["name"] for r in ctx.players(side, "substitute")]
            for j in range(0, len(subs) - 1, 3):
                group = name_list(subs[j:j + 3])
                add(f"bench:{side}:{j}", "bench", f"On the {team} bench: {group}.",
                    f"{team} have {group} among their substitutes.")
            form, wins, n = ctx.form_of(team)
            if n == 5:
                add(f"form:{side}", "form", f"{team} have won {num_word(wins)} of their last five games.",
                    f"{team}'s last five results read {form}.")
            rows = sorted((r for r in ctx.form if r.get("team") == team), key=lambda r: r.get("date", ""))[-5:]
            for k, r in enumerate(reversed(rows)):
                text, my = result_text(team, r), month_year(r.get("date"))
                if text:
                    add(f"form:{side}:{k}", "form", ("Last time out, " + text) if k == 0 else text,
                        f"In {my}, {result_text(team, r, when=False)}" if my else None)
        h2h = sorted((r for r in ctx.h2h if r.get("team") == ctx.home), key=lambda r: r.get("date", ""))
        v = ctx.base
        if h2h:
            add("h2h", "h2h", f"These two sides have met {v['h2h_count']} times: {v['h2h_home_wins']} wins for "
                              f"{ctx.home}, {v['h2h_away_wins']} for {ctx.away} and {v['h2h_draws']} draws.",
                f"In {v['h2h_count']} meetings, {ctx.home} have won {v['h2h_home_wins']}, {ctx.away} "
                f"{v['h2h_away_wins']}, with {v['h2h_draws']} draws.")
            for k, r in enumerate(reversed(h2h[-4:])):
                text, my = result_text(ctx.home, r), month_year(r.get("date"))
                if text:
                    comp = clean_name(r.get("competition"))
                    add(f"h2h:{k}", "h2h", ("When these two last met, " if k == 0 else "") + text,
                        f"In the {comp}, {text}" if comp else None,
                        f"In {my}, {result_text(ctx.home, r, when=False)}" if my else None)
        add("referee", "venue", f"{v['referee']} is the referee today." if v["referee"] else None,
            f"The match official today is {v['referee']}." if v["referee"] else None)
        add("attendance", "venue", f"The attendance today is {v['attendance']}." if v["attendance"] else None,
            f"{v['attendance']} fans are here today." if v["attendance"] else None)
        add("stadium", "venue", f"{v['stadium']}, built in {v['stadium_built']}, holds {v['capacity']} spectators."
            if v["stadium"] and v["stadium_built"] and v["capacity"] else None,
            f"We're at {v['stadium']} in {v['city']}." if v["stadium"] and v["city"] else None)
        add("competition", "venue", f"This is {v['competition']}, {v['round_phrase']}."
            if v["competition"] and v["round_phrase"] else None)
        return items

    # ---------------- dynamic items
    def _score(self, half, second):
        v = self.ctx.vars_at(half, second)
        when = minute_words(v["minute"]) or "this game"
        h, a = v["home_goals"], v["away_goals"]
        short = f"{self.ctx.home} {h}, {self.ctx.away} {a}."
        if v["state"] == "nil":
            texts = [f"Still goalless in {when}.", f"{when[0].upper() + when[1:]}, and it's {v['score']}.",
                     f"No goals yet: {v['score']}."]
        elif v["state"] == "draw":
            texts = [f"All square at {v['lead_score']} in {when}.", f"It's level, {v['score']}."]
        else:
            texts = [f"{v['leader']} lead {v['lead_score']} in {when}.", f"It's {v['score']}.",
                     f"{v['leader']} still in front, {v['score']}."]
        return texts + [short]

    def _clock(self, half, second, half_len):
        minute = second // 60
        name = "first" if half == 1 else "second"
        if minute >= 45:
            return [f"We're into stoppage time of the {name} half."]
        left = 45 - minute
        if left < 3 or minute < 5:
            return []
        return [f"About {num_word(left)} minutes left in the {name} half.",
                f"{num_word(left).capitalize()} minutes to play in the {name} half."]

    def _recap(self, half, second):
        """Goals, cards and changes that happened at least a minute before this time."""
        out, ctx = [], self.ctx
        for g in ctx.goals:
            if (g.half, g.second + 60) <= (half, second):
                team = ctx.home if g.side == "home" else ctx.away
                when = minute_words(g.minute)
                what = "own goal" if g.kind == "og" else "penalty" if g.kind == "pen" else "goal"
                out.append((f"goal:{g.player}:{g.minute}", [f"{g.player} scored for {team} in {when}."
                            if what == "goal" else f"{team}'s {what} came in {when}, from {g.player}."]))
        for r in ctx.events:
            if (r["half"], r["second"] + 60) > (half, second) or r["half"] not in (1, 2):
                continue
            when = minute_words(r.get("minute") or game_minute(r["half"], r["second"]))
            if r["type_name"] == "Yellow card" and r.get("player"):
                out.append((f"card:{r['player']}", [f"{r['player']} of {r['team']} was booked in {when}."]))
            elif r["type_name"] == "Substitution" and r.get("player") and r.get("player_off"):
                out.append((f"sub:{r['player']}", [f"{r['player']} came on for {r['player_off']} for {r['team']} "
                                                   f"in {when}."]))
        return out

    def gone_off(self, half, second):
        out = set()
        for r in self.ctx.events:
            if (r["half"], r["second"]) > (half, second):
                break
            if r["type_name"] == "Substitution" and r.get("player_off"):
                out.add(r["player_off"])
            elif r["type_name"] in ("Red card", "Second yellow card") and r.get("player"):
                out.add(r["player"])
        return out

    # ---------------- choose
    def _fits(self, texts, budget):
        return [t for t in texts if t and word_count(t) <= budget]

    def pick(self, half, second, budget, half_len, after_yes=""):
        """A line of at most `budget` words for this time, or (None, None).
        after_yes: text of the yes event just said; its count (third corner...) is said first when it changed."""
        now = half * 10000 + second
        prefer = self.action_of(after_yes)
        order = sorted(self.ORDER, key=lambda c: self.last_cat[c])  # the topic said longest ago first
        if prefer:
            order = ["stats"] + order
        for cat in dict.fromkeys(order):
            if now - self.last_cat[cat] < self.COOLDOWN[cat] and not (cat == "stats" and prefer):
                continue
            text = self._pick_cat(cat, half, second, budget, half_len, now, prefer)
            if text:
                self.last_cat[cat] = now
                return cat, text
        # every topic said recently: the static item said longest ago (at least MIN_REUSE seconds ago)
        # (a topic other than the one just said first, so that two bench lines do not follow each other)
        last = max(self.last_cat, key=self.last_cat.get)
        off = self.gone_off(half, second)
        old = sorted((it for it in self.items if it.uses and now - it.last >= self.MIN_REUSE and not (
                      it.category in ("player", "unit") and any(name in it.variants[0] for name in off))),
                     key=lambda it: (it.category == last, now - self.last_cat[it.category] < self.COOLDOWN[it.category],
                                     it.last))
        for it in old:
            fit = self._fits(it.variants[it.uses % len(it.variants):] + it.variants[:it.uses % len(it.variants)],
                             budget)
            if fit:
                it.uses, it.last = it.uses + 1, now
                self.last_cat[it.category] = now
                return it.category, fit[0]
        return None, None

    def _pick_cat(self, cat, half, second, budget, half_len, now, prefer=""):
        if cat == "stats":
            for key, n, texts in self._stats(half, second, prefer):
                texts = self._fits(texts, budget)
                if texts:
                    self.stats_said[key] = n
                    return self.rng.choice(texts)
            return None
        if cat == "score":
            texts = self._fits(self._score(half, second), budget)
            return self.rng.choice(texts) if texts else None
        if cat == "clock":
            texts = self._fits(self._clock(half, second, half_len), budget)
            return self.rng.choice(texts) if texts else None
        if cat == "recap":
            for key, texts in self._recap(half, second):
                if now - self.recap_last.get(key, -1e9) >= 480:
                    texts = self._fits(texts, budget)
                    if texts:
                        self.recap_last[key] = now
                        return texts[0]
            return None
        pool = [it for it in self.items if it.category == cat]
        if cat in ("player", "unit"):  # not a player who has already gone off (substitution, red card)
            off = self.gone_off(half, second)
            pool = [it for it in pool if not any(name in it.variants[0] for name in off)]
        fresh = [it for it in pool if it.uses == 0]
        again = sorted((it for it in pool if it.uses and now - it.last >= self.reuse_after), key=lambda it: it.last)
        text, budget_left, parts = None, budget, []
        for it in fresh + again:  # up to 2 items of the same topic in one line
            texts = it.variants[it.uses % len(it.variants):] + it.variants[:it.uses % len(it.variants)]
            fit = self._fits(texts, budget_left - (1 if parts else 0))
            if parts:  # not twice the same opening ("On the Chelsea bench: ... On the Chelsea bench: ...")
                fit = [f for f in fit if f.split()[:3] != parts[0].split()[:3]]
            if not fit:
                continue
            parts.append(fit[0])
            it.uses, it.last = it.uses + 1, now
            budget_left -= word_count(fit[0])
            if len(parts) == 2 or budget_left < 6:
                break
        if parts:
            text = " ".join(parts)
        return text


def fill_continuous(ctx, lines, yes_events, muted, half_lens, pause=0.7, margin=1.0, min_fill=3.0,
                    max_line_words=30, seed=0):
    """Fill every silence of the timeline with no-flow lines, so that the commentary never stops.

    yes_events: [(half, second, text)] (muted ones are not spoken); lines: the no-flow lines of build_schedule.
    A silence starts `pause` seconds after the estimated end of a line (speech_len) and ends `margin` seconds before
    the next line. Silences shorter than `min_fill` seconds are left. No filling after the half-time invitation (C2),
    the goodbye (G4) or the extra-time line (H1). Returns the new lines (code FILL, topic = what they talk about)."""
    said = [(h, s, t) for h, s, t in yes_events if (h, s) not in muted]
    filler = Filler(ctx, said, seed=seed)
    added = []
    for half in (1, 2):
        if half - 1 >= len(half_lens):
            continue
        half_len = half_lens[half - 1]
        spoken = [(s, speech_len(t), "YES", t) for h, s, t in said if h == half]
        spoken += [(l.second, speech_len(l.text), l.code, l.text) for l in lines if l.half == half]
        spoken.sort(key=lambda x: x[0])
        if not spoken:
            continue
        stop = min([s for s, _, code, _ in spoken if code in ("C2", "G4", "H1")] + [half_len])
        end, prev_code, prev_text = None, "", ""  # no filling before the first line of the half (welcome)
        for start, dur, code, text in spoken + [(half_len, 0.0, "END", "")]:
            t = None if end is None else end + pause
            limit = min(start, stop) - margin
            while t is not None and t < stop and limit - t >= min_fill:
                budget = min(max_line_words, max_words(limit - t))
                if budget < 3:
                    break
                cat, text_fill = filler.pick(half, int(t), budget, half_len,
                                             after_yes=prev_text if prev_code == "YES" else "")
                if not text_fill:
                    break
                line = Line(half, round(t, 1), "FILL", text_fill, False, phase="background", topic=cat,
                            vars=ctx.vars_at(half, int(t)))
                line.after = "" if prev_code == "YES" else prev_code
                line.vars["kind"] = ctx.kind
                added.append(line)
                prev_code = "FILL"
                t = line.second + speech_len(text_fill) + pause
            if start >= half_len:
                break
            end = start + dur if end is None else max(end, start + dur)
            prev_code, prev_text = code, text
    return added


# ---------------------------------------------------------------- yes captions without [PLAYER] / [TEAM]

def neutral_caption(text):
    """SoccerNet captions hide names: '[PLAYER] ([TEAM]) takes the corner' -> 'The player takes the corner'."""
    t = re.sub(r"\[PLAYER\]\s*\(\[TEAM\]\)", "[PLAYER]", text or "")
    first = [True]

    def player(_):
        if first[0]:
            first[0] = False
            return "the player"
        return "another player"

    t = re.sub(r"\[PLAYER\]", player, t)
    t = (t.replace("[TEAM]'s", "their").replace("[TEAM]", "the team").replace("[REFEREE]", "the referee")
         .replace("[COACH]", "the coach").replace("[STADIUM]", "the stadium"))
    t = re.sub(r"\[[A-Z]+\]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), t)
