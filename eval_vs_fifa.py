"""Recall of the YES flow on new matches, using the FIFA match events (events.csv from fifa_crawl.py) as reference.

New matches have no SoccerNet labels, so recall/precision cannot be computed like in retune.py. FIFA lists the main
actions of the match (goals, shots, corners, fouls, offsides, cards, substitutions...) with the minute only:
an event of minute "2'" (second = 120 in events.csv) happened between 1:00 and 2:00 of the half.

An event is "found" when a YES spot lies in [second - 60 - tolerance, second + tolerance] of the same half.
Events in the same half and minute are merged into one moment (e.g. penalty awarded + penalty goal).

- recall: share of FIFA moments with at least one YES spot nearby. This is the number to look at.
- FIFA overlap: share of YES spots near a FIFA moment. FIFA does not list every action (throw-ins, most crosses,
  goal kicks...), so this is a lower bound of the precision, not the precision.
- random: the same numbers for the same count of spots placed at random (mean of --trials draws). The FIFA window is
  wide (~90 s) so random spots already find many moments: the model is only useful by its margin over random.

usage:
    python eval_vs_fifa.py --yes_dir "video_test/output/yes/2026-07-05 - Brazil 1 - 2 Norway" \
        --events "video_test/metadata/2026-07-05 - Brazil 1 - 2 Norway/events.csv"
"""
import csv
import json
import os
import random
from argparse import ArgumentParser
from collections import defaultdict

# timing / bookkeeping rows, not actions on the pitch
SKIP_TYPES = {"Start Time", "End Time", "Pause Time", "Resume Time", "Match end", "Coin Toss", "Resume", "Delay",
              "Assist"}


def load_fifa(path):
    """{(half, second): [type_name, ...]} for the actions on the pitch."""
    moments = defaultdict(list)
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["type_name"] in SKIP_TYPES or not r["second"]:
                continue
            moments[(int(r["half"]), int(float(r["second"])))].append(r["type_name"])
    return moments


def load_yes(yes_dir):
    with open(os.path.join(yes_dir, "results_spotting.json")) as f:
        preds = json.load(f)["predictions"]
    return [(int(p["half"]), int(p["position"]) / 1000) for p in preds]


def match(moments, spots, tolerance):
    near = lambda half, sec, h, t: h == half and sec - 60 - tolerance <= t <= sec + tolerance
    found = {m for m in moments if any(near(*m, h, t) for h, t in spots)}
    used = [s for s in spots if any(near(*m, *s) for m in moments)]
    return found, used


def random_baseline(moments, spots, tolerance, trials, seed=0):
    """Mean recall / overlap of the same number of spots per half, uniform over the half."""
    rng = random.Random(seed)
    length = {h: max([t for hh, t in spots if hh == h] + [s for hh, s in moments if hh == h] + [60]) for h in (1, 2)}
    count = {h: sum(hh == h for hh, _ in spots) for h in (1, 2)}
    rec = ovl = 0.0
    for _ in range(trials):
        fake = [(h, rng.uniform(0, length[h])) for h in (1, 2) for _ in range(count[h])]
        found, used = match(moments, fake, tolerance)
        rec += len(found) / max(1, len(moments))
        ovl += len(used) / max(1, len(fake))
    return rec / trials, ovl / trials


def evaluate(yes_dir, events, tolerance, trials=200):
    moments, spots = load_fifa(events), load_yes(yes_dir)
    found, used = match(moments, spots, tolerance)
    rand_recall, rand_overlap = random_baseline(moments, spots, tolerance, trials)

    per_type = defaultdict(lambda: [0, 0])
    for m, types in moments.items():
        for t in set(types):
            per_type[t][0] += m in found
            per_type[t][1] += 1
    return {"spots": len(spots), "fifa_moments": len(moments), "found": len(found),
            "recall": len(found) / max(1, len(moments)),
            "fifa_overlap": len(used) / max(1, len(spots)),
            "random_recall": rand_recall, "random_overlap": rand_overlap,
            "per_type": {t: f"{a}/{b}" for t, (a, b) in sorted(per_type.items(), key=lambda kv: -kv[1][1])},
            "missed": [f"{h} - {s // 60:02d}:00 {'/'.join(moments[(h, s)])}" for h, s in sorted(set(moments) - found)]}


def main():
    p = ArgumentParser(description="Recall of YES spots against FIFA match events")
    p.add_argument("--yes_dir", required=True, help="folder with results_spotting.json (infer_match.py output)")
    p.add_argument("--events", required=True, help="events.csv from fifa_crawl.py")
    p.add_argument("--tolerance", type=int, default=15, help="seconds allowed outside the FIFA minute")
    p.add_argument("--trials", type=int, default=200, help="random draws for the baseline")
    p.add_argument("--show_missed", action="store_true")
    args = p.parse_args()
    r = evaluate(args.yes_dir, args.events, args.tolerance, args.trials)
    print(f"{os.path.basename(os.path.normpath(args.yes_dir))}: {r['spots']} spots | "
          f"recall {r['recall']:.3f} ({r['found']}/{r['fifa_moments']} FIFA moments) | "
          f"FIFA overlap {r['fifa_overlap']:.3f} | random: recall {r['random_recall']:.3f}, "
          f"overlap {r['random_overlap']:.3f}")
    print("  per type (found/total): " + ", ".join(f"{t} {v}" for t, v in r["per_type"].items()))
    if args.show_missed:
        print("  missed: " + "; ".join(r["missed"]))
    print("RESULT " + json.dumps({k: r[k] for k in ("spots", "fifa_moments", "found", "recall", "fifa_overlap",
                                                    "random_recall", "random_overlap")}))


if __name__ == "__main__":
    main()
