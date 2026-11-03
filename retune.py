"""Re-run spotting + dense captioning from trained checkpoints with other inference settings (no training).

Tries every NMS threshold x top_k combination on a split, prints METEOR / CIDEr / number of spots /
caption diversity, and leaves models/<name>/outputs/<split> with the results of the best combination.

Usage:
    # pick the settings on valid
    python retune.py --SoccerNet_path dataset/caption-2024 --model_name gpt2-30games --split valid \
        --nms_thresholds 0.3 0.4 0.5 0.7 --top_k 1 3
    # apply them on test
    python retune.py --SoccerNet_path dataset/caption-2024 --model_name gpt2-30games --split test \
        --nms_thresholds 0.4 --top_k 3
"""
import csv
import glob
import json
import logging
import os
from argparse import ArgumentParser

import torch

from dataset import SoccerNetClipsTesting, PredictionCaptions
from model import Video2Spot
from model_gpt import Video2CaptionGPT
from train import test_spotting, test_captioning

FEATURE_SIZE = {"gpt2": 768, "gpt2-medium": 1024, "gpt2-large": 1280, "gpt2-xl": 1600}


def load_spotting(args, dataset):
    model = Video2Spot(input_size=args.feature_dim, num_classes=len(dataset.dict_event),
                       window_size=args.window_size, vlad_k=args.vlad_k, framerate=args.framerate,
                       pool=args.pool, proj_size=FEATURE_SIZE[args.gpt_type]).cuda()
    checkpoint = torch.load(os.path.join("models", args.model_name, "spotting", "model.pth.tar"))
    model.load_state_dict(checkpoint["state_dict"])
    return model


def load_caption(args, vocab_size):
    model = Video2CaptionGPT(vocab_size=vocab_size, input_size=args.feature_dim, vlad_k=args.vlad_k,
                             window_size=args.window_size, framerate=args.framerate, pool=args.pool,
                             num_layers=args.num_layers, gpt_type=args.gpt_type, gpt_path=args.gpt_type).cuda()
    checkpoint = torch.load(os.path.join("models", args.model_name, "caption", "model.pth.tar"))
    model.load_state_dict(checkpoint["state_dict"])
    return model


def caption_diversity(output_dir):
    captions = [p.get("comment", "")
                for f in glob.glob(os.path.join(output_dir, "**", "results_dense_captioning.json"), recursive=True)
                for p in json.load(open(f))["predictions"]]
    return len(captions), len(set(captions))


def run(args, threshold, top_ks, spot_loader, spot_model, cap_model):
    """Spotting with one NMS threshold, then dense captioning with each top_k."""
    spot = test_spotting(spot_loader, model=spot_model, model_name=args.model_name,
                         NMS_window=args.NMS_window, NMS_threshold=threshold)
    output_dir = os.path.join("models", args.model_name, "outputs", args.split)
    dataset = PredictionCaptions(SoccerNetPath=args.SoccerNet_path, PredictionPath=output_dir, features=args.features,
                                 split=[args.split], framerate=args.framerate, window_size=args.window_size)
    loader = torch.utils.data.DataLoader(dataset, batch_size=args.batch_size, shuffle=False,
                                         num_workers=args.max_num_worker, pin_memory=True)
    rows = []
    for k in top_ks:
        cap_model.top_k = k
        torch.manual_seed(args.seed)  # top_k > 1 samples, keep it reproducible
        dvc = test_captioning(loader, cap_model, args.model_name) or {}
        n_captions, n_unique = caption_diversity(output_dir)
        row = {"nms_threshold": threshold, "top_k": k, "spots": n_captions, "unique_captions": n_unique,
               **{m: (spot or {}).get(m) for m in ("a_mAP_tight", "a_mAP_loose")},
               **{m: dvc.get(m) for m in ("METEOR_loose", "METEOR_tight", "CIDEr_loose", "Bleu_4_loose",
                                          "Recall_loose", "Precision_loose")}}
        logging.info(f"retune {row}")
        rows.append(row)
    return rows


def main(args):
    spot_dataset = SoccerNetClipsTesting(path=args.SoccerNet_path, features=args.features, split=[args.split],
                                         framerate=args.framerate, window_size=args.window_size)
    args.feature_dim = spot_dataset[0][1].shape[-1]
    spot_loader = torch.utils.data.DataLoader(spot_dataset, batch_size=1, shuffle=False, num_workers=1, pin_memory=True)
    spot_model = load_spotting(args, spot_dataset)
    cap_model = load_caption(args, vocab_size=50257)  # tiktoken GPT-2 vocabulary, see TikTokenTextProcessor

    rows = []
    for threshold in args.nms_thresholds:
        rows += run(args, threshold, args.top_k, spot_loader, spot_model, cap_model)

    keys = list(rows[0])
    fmt = lambda v: f"{v:.4f}" if isinstance(v, float) else str(v)
    print("\n" + " | ".join(keys))
    for r in rows:
        print(" | ".join(fmt(r[k]) for k in keys))
    out_csv = os.path.join("models", args.model_name, f"retune_{args.split}.csv")
    with open(out_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    print(f"saved {out_csv}")

    if len(rows) > 1 and rows[0].get("METEOR_loose") is not None:
        best = max(rows, key=lambda r: r["METEOR_loose"])
        print(f"best on {args.split}: NMS_threshold={best['nms_threshold']} top_k={best['top_k']} "
              f"(METEOR_loose {best['METEOR_loose']:.4f})")
        # leave the outputs folder with the best combination
        if best is not rows[-1]:
            run(args, best["nms_threshold"], [best["top_k"]], spot_loader, spot_model, cap_model)


if __name__ == "__main__":
    parser = ArgumentParser(description="Re-run spotting + dense captioning with other NMS / decoding settings")
    parser.add_argument("--SoccerNet_path", required=True)
    parser.add_argument("--model_name", required=True, help="folder in models/ with spotting/ and caption/ checkpoints")
    parser.add_argument("--split", default="valid")
    parser.add_argument("--nms_thresholds", type=float, nargs="+", default=[0.3, 0.4, 0.5, 0.7])
    parser.add_argument("--top_k", type=int, nargs="+", default=[1], help="1 = greedy, >1 = sample among the k best tokens")
    parser.add_argument("--NMS_window", type=int, default=30)
    parser.add_argument("--features", default="baidu_soccer_embeddings.npy")
    parser.add_argument("--framerate", type=int, default=1)
    parser.add_argument("--window_size", type=int, default=30)
    parser.add_argument("--pool", default="QFormer")
    parser.add_argument("--vlad_k", type=int, default=64)
    parser.add_argument("--num_layers", type=int, default=2)
    parser.add_argument("--gpt_type", default="gpt2")
    parser.add_argument("--batch_size", type=int, default=32)
    parser.add_argument("--max_num_worker", type=int, default=2)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)-5.5s]  %(message)s",
                        handlers=[logging.FileHandler(os.path.join("models", args.model_name, f"retune_{args.split}.log")),
                                  logging.StreamHandler()])
    main(args)
