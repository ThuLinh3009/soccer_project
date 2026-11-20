"""(v7.6) Put the metadata of a match where the pipeline reads it (video_test/metadata/<game>/), from the FIFA crawl
plus the extra sources, keeping only facts known before kick-off.

    <out>/                      FIFA crawl (crawler/fifa_crawl.py): match_info.csv, lineups.csv, events.csv, form.csv...
    <out>/wikipedia/lineups.csv detailed positions (RB, CB, DM, LF...): team, role, position, shirt_number, name, captain
                                (minutes of substitutions and cards are dropped: they would tell the future)
    <out>/wikipedia/squads.csv  club, caps and goals before the tournament
    <out>/tournament_path.csv   the team's games in the tournament (the commentary uses those before this match)

Not copied: Wikipedia match summary / match info and the FIFA post-match PDFs (they give the result and the stats).
The folder already there is kept as <out>_backup_<date> (nothing is deleted).

usage (from the repo root):
    python -m crawler.prepare_metadata --fifa "metadata/brazil_norway_2026/fifa/2026-07-05 - Brazil 1 - 2 Norway" \
        --extra metadata/brazil_norway_2026 --out "../video_test/metadata/2026-07-05 - Brazil 1 - 2 Norway"
"""
import csv
import datetime
import os
import shutil
import sys
from argparse import ArgumentParser

POSITION_COLUMNS = ["team", "role", "position", "shirt_number", "name", "captain"]


def read(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write(path, rows, fields):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main(args):
    if not os.path.isfile(os.path.join(args.fifa, "match_info.csv")):
        sys.exit(f"no match_info.csv in {args.fifa}: give the FIFA crawl folder of the match")
    if os.path.exists(args.out):
        backup = f"{os.path.normpath(args.out)}_backup_{datetime.date.today():%Y%m%d}"
        n = 2
        while os.path.exists(backup):
            backup = f"{os.path.normpath(args.out)}_backup_{datetime.date.today():%Y%m%d}_{n}"
            n += 1
        shutil.move(args.out, backup)
        print(f"old folder kept as {backup}")
    shutil.copytree(args.fifa, args.out)
    print(f"FIFA crawl -> {args.out} ({len(os.listdir(args.out))} files)")
    if args.extra:
        src = os.path.join(args.extra, "wikipedia", "lineups.csv")
        if os.path.exists(src):
            write(os.path.join(args.out, "wikipedia", "lineups.csv"), read(src), POSITION_COLUMNS)
            print("wikipedia/lineups.csv: positions only (no substitution / card minutes)")
        src = os.path.join(args.extra, "wikipedia", "squads.csv")
        if os.path.exists(src):
            rows = read(src)
            write(os.path.join(args.out, "wikipedia", "squads.csv"), rows, list(rows[0].keys()) if rows else ["team"])
            print(f"wikipedia/squads.csv: {len(rows)} players (club, caps before the tournament)")
        src = os.path.join(args.extra, "tournament_path.csv")
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(args.out, "tournament_path.csv"))
            print("tournament_path.csv")
    print("done: upload this folder to Drive (soccer_project/video_test/metadata/), replacing the old one")


if __name__ == "__main__":
    p = ArgumentParser(description="FIFA crawl + extra sources -> the metadata folder the pipeline reads")
    p.add_argument("--fifa", required=True, help="crawler/fifa_crawl.py output folder of the match")
    p.add_argument("--extra", default=None, help="folder with wikipedia/ and tournament_path.csv (multi-source crawl)")
    p.add_argument("--out", required=True, help="video_test/metadata/<game> (same name as the video folder)")
    main(p.parse_args())
