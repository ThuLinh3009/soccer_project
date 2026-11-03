"""Download caption-2024 features and labels for a subset of games per split.

Usage:
    python download_subset.py dataset/caption-2024 --train 5 --valid 2 --test 2

Then run training with SN_LOCAL_SUBSET=1 so only the downloaded games are used.
"""
import os
from argparse import ArgumentParser

from huggingface_hub import snapshot_download
from SoccerNet.utils import getListGames

FEATS = ["1_baidu_soccer_embeddings.npy", "2_baidu_soccer_embeddings.npy"]
LABELS = "Labels-caption.json"


def main(args):
    for split in ["train", "valid", "test", "challenge"]:
        n = getattr(args, split)
        if n == 0:
            continue
        games = [g.replace("\\", "/") for g in getListGames(split, "caption")]
        # prefer games whose features are already on disk
        have = [g for g in games if all(os.path.exists(os.path.join(args.path, g, f)) for f in FEATS)]
        chosen = (have + [g for g in games if g not in have])[:n if n > 0 else None]
        print(f"{split}: {len(chosen)} games", flush=True)
        snapshot_download("SoccerNet/SN-Features", repo_type="dataset", revision="baidu-soccer-embeddings",
                          local_dir=args.path, allow_patterns=[g + "/" + f for g in chosen for f in FEATS])
        if split != "challenge":  # challenge games have no labels
            snapshot_download("SoccerNet/SN-Labels", repo_type="dataset", revision="main",
                              local_dir=args.path, allow_patterns=[g + "/" + LABELS for g in chosen])
    print("DONE")


if __name__ == "__main__":
    parser = ArgumentParser(description="Download a subset of SoccerNet caption-2024 games")
    parser.add_argument("path", type=str, help="Local folder for caption-2024 data")
    parser.add_argument("--train", type=int, default=5, help="Number of train games (-1 for all)")
    parser.add_argument("--valid", type=int, default=2, help="Number of valid games (-1 for all)")
    parser.add_argument("--test", type=int, default=2, help="Number of test games (-1 for all)")
    parser.add_argument("--challenge", type=int, default=0, help="Number of challenge games (-1 for all)")
    main(parser.parse_args())
