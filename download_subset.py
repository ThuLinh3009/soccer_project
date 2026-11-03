"""Download caption-2024 features and labels for a subset of games per split.

Usage:
    python download_subset.py dataset/caption-2024 --train 5 --valid 2 --test 2 --list_only   # show the games only
    python download_subset.py dataset/caption-2024 --train 5 --valid 2 --test 2               # download them

Then run training with SN_LOCAL_SUBSET=1 so only the downloaded games are used.
"""
import os
import re
from argparse import ArgumentParser

from SoccerNet.utils import getListGames

FEATS = ["1_baidu_soccer_embeddings.npy", "2_baidu_soccer_embeddings.npy"]
LABELS = "Labels-caption.json"
SPLITS = ["train", "valid", "test", "challenge"]
# "2015-08-08 - 19-30 Chelsea 2 - 2 Swansea"
GAME_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2}) - (\d{2})-(\d{2}) (.+?) (\d+) - (\d+) (.+)$")


def select_games(path, split, n):
    games = [g.replace("\\", "/") for g in getListGames(split, "caption")]
    # prefer games whose features are already on disk
    have = [g for g in games if all(os.path.exists(os.path.join(path, g, f)) for f in FEATS)]
    return (have + [g for g in games if g not in have])[:n if n > 0 else None]


def describe(game):
    league, season, name = game.split("/")
    m = GAME_RE.match(name)
    if m is None:
        return league, season, "", name, "", ""
    y, mo, d, hh, mm, home, hs, as_, away = m.groups()
    return league, season, f"{d}/{mo}/{y} {hh}:{mm}", home, f"{hs} - {as_}", away


def print_games(selected):
    print(f"{'split':6} {'#':>3}  {'league':30} {'season':9} {'date':16}  match")
    for split, games in selected.items():
        for i, g in enumerate(games, 1):
            league, season, date, home, score, away = describe(g)
            print(f"{split:6} {i:3d}  {league:30} {season:9} {date:16}  {home} {score} {away}")
    print("total: " + ", ".join(f"{s} {len(g)}" for s, g in selected.items())
          + f" -> {sum(len(g) for g in selected.values())} games")


def download(path, split, games):
    from huggingface_hub import snapshot_download
    snapshot_download("SoccerNet/SN-Features", repo_type="dataset", revision="baidu-soccer-embeddings",
                      local_dir=path, allow_patterns=[g + "/" + f for g in games for f in FEATS])
    if split != "challenge":  # challenge games have no labels
        snapshot_download("SoccerNet/SN-Labels", repo_type="dataset", revision="main",
                          local_dir=path, allow_patterns=[g + "/" + LABELS for g in games])


def main(args):
    selected = {s: select_games(args.path, s, getattr(args, s)) for s in SPLITS if getattr(args, s) != 0}
    print_games(selected)
    if args.list_only:
        return
    for split, games in selected.items():
        print(f"downloading {split}: {len(games)} games", flush=True)
        download(args.path, split, games)
    print("DONE")


if __name__ == "__main__":
    parser = ArgumentParser(description="Download a subset of SoccerNet caption-2024 games")
    parser.add_argument("path", type=str, help="Local folder for caption-2024 data")
    parser.add_argument("--train", type=int, default=5, help="Number of train games (-1 for all)")
    parser.add_argument("--valid", type=int, default=2, help="Number of valid games (-1 for all)")
    parser.add_argument("--test", type=int, default=2, help="Number of test games (-1 for all)")
    parser.add_argument("--challenge", type=int, default=0, help="Number of challenge games (-1 for all)")
    parser.add_argument("--list_only", action="store_true", help="Only print the selected games, do not download")
    main(parser.parse_args())
