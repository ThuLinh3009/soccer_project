"""Yes flow on new matches (no labels needed): event spotting + dense captioning with the trained checkpoints.

The SoccerNet scripts (main.py, retune.py) only run on games listed in the SoccerNet splits and always score the
results against the labels. This script runs the same models and the same inference (sliding-window spotting + NMS,
then one GPT-2 caption per spot) on any folder with 1_<features> / 2_<features>, e.g. a 2026 match cut with
cut_halves.py, turned into TimeSformer features (timesformer_extract.py) and mapped to 8576 dims (feature_mapper.py).

Writes <out_dir>/<game>/results_spotting.json and results_dense_captioning.json (same format as main.py),
ready for no_flow_llm.py --yes_events.

usage:
    python infer_match.py --model_name gpt2-video60-mlp --features baidu_from_timesformer.npy \
        --game_dirs "dataset/new/fifa_world-cup/2026/2026-07-05 - Brazil 1 - 2 Norway" \
        --nms_threshold 0.4 --top_k 3 --out_dir outputs/yes
"""
import json
import os
from argparse import ArgumentParser, Namespace

import numpy as np
import tiktoken
import torch
from SoccerNet.Evaluation.utils import getMetaDataTask

from dataset import LazyClips, SoccerNetVideoProcessor
from retune import load_caption, load_spotting


def nms(scores, window, thresh):
    """Same greedy NMS as train.test_spotting: (frame, score) of every peak >= thresh, `window` frames apart."""
    scores, spots = np.copy(scores), []
    while scores.max() >= thresh:
        i = int(np.argmax(scores))
        spots.append((i, float(scores[i])))
        scores[max(0, i - window // 2):min(len(scores), i + window // 2)] = -1
    return spots


@torch.no_grad()
def spot_half(model, feats, clip_length, batch=256):
    """Event probability per frame (best non-background class), as in train.test_spotting."""
    clips, out = LazyClips(feats, clip_length), []
    for s in range(0, len(clips), batch):
        p = torch.softmax(model(clips[slice(s, min(s + batch, len(clips)))]), dim=1)
        out.append(p[:, 1:].max(dim=1).values.cpu().numpy())
    return np.concatenate(out)


def game_time(half, frame, framerate):
    sec = frame // framerate
    return f"{half} - {sec // 60:02d}:{sec % 60:02d}"


@torch.no_grad()
def run_game(game_dir, args, spot_model, cap_model, inv_dict):
    halves = [np.load(os.path.join(game_dir, f"{h}_{args.features}")).astype(np.float32) for h in (1, 2)]
    clip_length = args.window_size * args.framerate
    preds = []
    for h, feats in enumerate(halves, start=1):
        probs = spot_half(spot_model, torch.from_numpy(feats).cuda(), clip_length)
        for frame, conf in nms(probs, args.NMS_window * args.framerate, args.nms_threshold):
            preds.append({"gameTime": game_time(h, frame, args.framerate), "label": inv_dict[0],
                          "position": str(int(frame / args.framerate * 1000)), "half": str(h),
                          "confidence": str(conf), "_frame": frame})
    preds.sort(key=lambda p: (int(p["half"]), int(p["position"])))

    name = os.path.basename(os.path.normpath(game_dir))
    out = os.path.join(args.out_dir, name)
    os.makedirs(out, exist_ok=True)
    spotting = {"UrlLocal": game_dir, "predictions": [{k: v for k, v in p.items() if k != "_frame"} for p in preds]}
    json.dump(spotting, open(os.path.join(out, "results_spotting.json"), "w"), indent=4)
    if args.no_caption:
        print(f"{name}: {len(preds)} events ({sum(p['half'] == '1' for p in preds)} / "
              f"{sum(p['half'] == '2' for p in preds)} per half), spotting only -> {out}")
        return

    # one caption per spot, from the clip centred on it (same clips as dataset.PredictionCaptions)
    video = SoccerNetVideoProcessor(clip_length)
    feats_per_game = [(halves[0], halves[1])]
    enc = tiktoken.get_encoding("gpt2")
    for p in preds:
        clip = video((0, int(p["half"]) - 1, p.pop("_frame")), feats_per_game)
        tokens = cap_model.sample(torch.from_numpy(clip).cuda())[0].tolist()
        p["comment"] = enc.decode([t for t in tokens if t != enc.eot_token]).strip()
    json.dump({"UrlLocal": game_dir, "predictions": preds},
              open(os.path.join(out, "results_dense_captioning.json"), "w"), indent=4)
    n_unique = len({p["comment"] for p in preds})
    print(f"{name}: {len(preds)} events ({sum(p['half'] == '1' for p in preds)} / "
          f"{sum(p['half'] == '2' for p in preds)} per half), {n_unique} different captions -> {out}")
    for p in preds[:8]:
        print(f"  {p['gameTime']} | {p['comment']}")


def main(args):
    torch.manual_seed(args.seed)  # top_k > 1 samples: keep it reproducible
    _, num_classes, dict_event, inv_dict = getMetaDataTask("caption", "SoccerNet", 2)
    first = os.path.join(args.game_dirs[0], f"1_{args.features}")
    args.feature_dim = np.load(first, mmap_mode="r").shape[-1]
    print(f"features {args.features}: {args.feature_dim} dims | model {args.model_name} | "
          f"NMS {args.nms_threshold} | top_k {args.top_k}")
    spot_model = load_spotting(args, Namespace(dict_event=dict_event)).eval()
    cap_model = None if args.no_caption else load_caption(args, vocab_size=50257).eval()
    if cap_model is not None:
        cap_model.top_k = args.top_k
    for game_dir in args.game_dirs:
        run_game(game_dir, args, spot_model, cap_model, inv_dict)


if __name__ == "__main__":
    p = ArgumentParser(description="Spotting + dense captioning on new matches, without labels")
    p.add_argument("--model_name", required=True, help="folder in models/ with spotting/ and caption/ checkpoints")
    p.add_argument("--game_dirs", nargs="+", required=True, help="folders with 1_<features> and 2_<features>")
    p.add_argument("--features", default="baidu_from_timesformer.npy")
    p.add_argument("--out_dir", default=os.path.join("outputs", "yes"))
    p.add_argument("--nms_threshold", type=float, default=0.4, help="test: recall_loose 0.78, precision_loose 0.75, ~110 spots per game")
    p.add_argument("--top_k", type=int, default=3, help="best value from retune on valid")
    p.add_argument("--NMS_window", type=int, default=30)
    p.add_argument("--framerate", type=int, default=1)
    p.add_argument("--window_size", type=int, default=30)
    p.add_argument("--pool", default="QFormer")
    p.add_argument("--vlad_k", type=int, default=64)
    p.add_argument("--num_layers", type=int, default=2)
    p.add_argument("--gpt_type", default="gpt2")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--no_caption", action="store_true", help="spotting only (results_spotting.json), e.g. for eval_vs_fifa.py")
    main(p.parse_args())
