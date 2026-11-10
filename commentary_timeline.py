"""Full commentary timeline: event comments ("yes" flow) + background comments in the gaps ("no" flow).

Yes flow: the dense captions produced by the model (results_dense_captioning.json, from main.py / dvc).
No flow:  wherever no event is commented for a while, a fact about the match is said instead
          (lineups, coaches, live score, standings, form, head-to-head...), see match_facts.py.

Usage:
    # after main.py: use the model's predictions
    python commentary_timeline.py --soccernet_path dataset/caption-2024 --predictions models/<name>/outputs/test
    # without a model: use the ground-truth captions as the event comments (to try the no flow)
    python commentary_timeline.py --soccernet_path dataset/caption-2024 --events_from_labels --split test
"""
import json
import os
from argparse import ArgumentParser

import numpy as np

from match_facts import build_facts
from utils import get_list_games, DEFAULT_FEATURES

FEATURES = DEFAULT_FEATURES  # SN_FEATURES, used to read the half lengths
EVENT_LABELS = {"corner", "substitution", "y-card", "whistle", "soccer-ball", "injury", "penalty",
                "yr-card", "r-card", "soccer-ball-own", "penalty-missed", "", "comments"}


def parse_game_time(game_time):
    """"2 - 17:45" -> (2, 1065)"""
    half, clock = game_time.split(" - ")
    minutes, seconds = clock.split(":")
    return int(half), int(minutes) * 60 + int(seconds)


def format_game_time(half, sec):
    return f"{half} - {sec // 60:02d}:{sec % 60:02d}"


def half_lengths(soccernet_path, game):
    lengths = []
    for half in (1, 2):
        path = os.path.join(soccernet_path, game, f"{half}_{FEATURES}")
        # features are 1 per second
        lengths.append(np.load(path, mmap_mode="r").shape[0] if os.path.exists(path) else 48 * 60)
    return lengths


def load_events(game, soccernet_path, predictions, labels):
    """Yes-flow comments of one game: model predictions, or ground-truth captions when predictions is None."""
    if predictions is not None:
        path = os.path.join(predictions, game, "results_dense_captioning.json")
        items = json.load(open(path))["predictions"]
        events = [(parse_game_time(p["gameTime"]), p.get("comment", ""), p.get("label", ""), p.get("confidence"))
                  for p in items]
    else:
        events = [(parse_game_time(a["gameTime"]), a["description"], a["label"], None)
                  for a in labels["annotations"] if a["label"] in EVENT_LABELS]
    return sorted((e for e in events if e[0][0] in (1, 2)), key=lambda e: e[0])


def filler_slots(event_seconds, half_len, args):
    """(time, gap length) where a background comment fits: regular slots in the gaps between event comments."""
    anchors = [None] + sorted(event_seconds) + [None]
    slots = []
    for prev, nxt in zip(anchors[:-1], anchors[1:]):
        start = args.kickoff_delay if prev is None else prev + args.after_event
        end = half_len if nxt is None else nxt - args.before_event
        gap_start = 0 if prev is None else prev
        gap_end = half_len if nxt is None else nxt
        if gap_end - gap_start < args.min_gap:
            continue
        t = start
        while t <= end:
            slots.append((t, gap_end - gap_start))
            t += args.spacing
    return slots


def outside_events(t, event_seconds, args):
    """Push t after any event comment it would overlap."""
    moved = True
    while moved:
        moved = False
        for e in event_seconds:
            if e - args.before_event <= t < e + args.after_event:
                t, moved = e + args.after_event, True
    return t


def live_slots(facts, half, event_seconds, half_len, args):
    """One slot right when each goal, card or substitution becomes known (gap length 0: only important facts)."""
    slots = []
    for f in sorted((f for f in facts if f.live and f.valid_from[0] == half), key=lambda f: f.valid_from):
        t = outside_events(max(f.valid_from[1], args.kickoff_delay), event_seconds, args)
        if slots and t < slots[-1][0] + args.min_info_gap:
            t = outside_events(slots[-1][0] + args.min_info_gap, event_seconds, args)
        if t <= half_len:
            slots.append((t, 0))
    return slots


def build_timeline(game, soccernet_path, predictions, args):
    if args.events_only:
        # yes flow only: no metadata facts (the no flow is done later, at test time)
        labels = None if predictions is not None else json.load(
            open(os.path.join(soccernet_path, game, "Labels-caption.json"), encoding="utf-8"))
        facts = []
    else:
        labels, facts = build_facts(soccernet_path, game, cache_dir=args.cache_dir, crawl=not args.no_crawl)
    events = load_events(game, soccernet_path, predictions, labels)
    timeline = [{"half": h, "second": s, "gameTime": format_game_time(h, s), "flow": "yes",
                 "topic": label or "comment", "text": text, "confidence": conf}
                for (h, s), text, label, conf in events]
    if args.events_only:
        return sorted(timeline, key=lambda c: (c["half"], c["second"]))
    clock_of = lambda half, sec: (half - 1) * 45 * 60 + sec
    goal_clocks = [clock_of(*f.valid_from) for f in facts if f.topic == "goal"]

    last_said = {}  # fact index -> match second when it was last said
    for half, half_len in zip((1, 2), half_lengths(soccernet_path, game)):
        event_seconds = [s for (h, s), *_ in events if h == half]
        live = live_slots(facts, half, event_seconds, half_len, args)
        regular = [(t, gap) for t, gap in filler_slots(event_seconds, half_len, args)
                   if all(abs(t - lt) >= args.min_info_gap for lt, _ in live)]
        for t, gap in sorted(live + regular):
            now, clock = (half, t), clock_of(half, t)
            # small talk (low priority) only in long silences, and not just after a goal
            small_talk_ok = gap >= args.long_gap and not any(g <= clock < g + args.goal_cooldown for g in goal_clocks)
            candidates = [i for i, f in enumerate(facts) if f.valid_at(now)
                          and (f.priority >= args.low_priority or small_talk_ok)
                          and (i not in last_said or (f.repeat_every and clock - last_said[i] >= f.repeat_every))]
            if gap == 0:
                # slot opened for a goal / card / substitution: say that news first
                news = [i for i in candidates if facts[i].live and i not in last_said]
                candidates = news or candidates
            if not candidates:
                continue
            # highest priority first; on ties the fact listed first
            best = max(candidates, key=lambda i: (facts[i].priority, -i))
            fact = facts[best]
            text = fact.repeat_text if best in last_said else fact.text
            last_said[best] = clock
            timeline.append({"half": half, "second": t, "gameTime": format_game_time(half, t), "flow": "no",
                             "topic": fact.topic, "text": text, "confidence": None})
    return sorted(timeline, key=lambda c: (c["half"], c["second"]))


def write_outputs(game, timeline, out_dir):
    os.makedirs(os.path.join(out_dir, game), exist_ok=True)
    with open(os.path.join(out_dir, game, "commentary_timeline.json"), "w", encoding="utf-8") as f:
        json.dump({"game": game, "comments": timeline}, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, game, "commentary_timeline.txt"), "w", encoding="utf-8") as f:
        for c in timeline:
            tag = "EVENT" if c["flow"] == "yes" else "INFO "
            f.write(f"{c['gameTime']}  [{tag}] ({c['topic']}) {c['text']}\n")


def main(args):
    if args.events_from_labels:
        games = [g.replace("\\", "/") for g in get_list_games(args.soccernet_path, [args.split])]
        predictions = None
        out_dir = args.out_dir or os.path.join("timelines", args.split)
    else:
        games = sorted(os.path.relpath(os.path.dirname(p), args.predictions).replace("\\", "/")
                       for p in _find(args.predictions, "results_dense_captioning.json"))
        predictions = args.predictions
        out_dir = args.out_dir or args.predictions
    for game in games:
        timeline = build_timeline(game, args.soccernet_path, predictions, args)
        write_outputs(game, timeline, out_dir)
        n_yes = sum(c["flow"] == "yes" for c in timeline)
        print(f"{game}: {n_yes} event comments + {len(timeline) - n_yes} background comments "
              f"-> {os.path.join(out_dir, game, 'commentary_timeline.txt')}")


def _find(root, filename):
    for dirpath, _, files in os.walk(root):
        if filename in files:
            yield os.path.join(dirpath, filename)


if __name__ == "__main__":
    parser = ArgumentParser(description="Merge event comments with background comments into one timeline")
    parser.add_argument("--soccernet_path", required=True, help="caption-2024 folder (features + labels)")
    parser.add_argument("--predictions", default=None, help="models/<name>/outputs/<split> with results_dense_captioning.json")
    parser.add_argument("--events_from_labels", action="store_true", help="use ground-truth captions as event comments")
    parser.add_argument("--split", default="test", help="split to use with --events_from_labels")
    parser.add_argument("--events_only", action="store_true",
                        help="only the event comments (yes flow), no background facts (no flow)")
    parser.add_argument("--out_dir", default=None, help="where to write commentary_timeline.json/.txt")
    parser.add_argument("--cache_dir", default="metadata/football-data", help="cache for football-data.co.uk CSVs")
    parser.add_argument("--no_crawl", action="store_true", help="only use the SoccerNet metadata, no internet")
    parser.add_argument("--min_gap", type=int, default=45, help="only fill silences of at least this many seconds")
    parser.add_argument("--after_event", type=int, default=15, help="seconds to wait after an event comment")
    parser.add_argument("--before_event", type=int, default=10, help="seconds to keep free before the next event comment")
    parser.add_argument("--spacing", type=int, default=90, help="seconds between two background comments")
    parser.add_argument("--min_info_gap", type=int, default=30, help="minimum seconds between two background comments")
    parser.add_argument("--long_gap", type=int, default=120, help="small talk only in silences at least this long")
    parser.add_argument("--low_priority", type=int, default=50, help="facts below this priority count as small talk")
    parser.add_argument("--goal_cooldown", type=int, default=120, help="no small talk for this many seconds after a goal")
    parser.add_argument("--kickoff_delay", type=int, default=5, help="first background comment after kick-off")
    args = parser.parse_args()
    if args.predictions is None and not args.events_from_labels:
        parser.error("give --predictions or --events_from_labels")
    main(args)
