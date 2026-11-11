"""Learn a mapping from TimeSformer features (768-d) to Baidu soccer embeddings (8576-d), then apply it,
so the models already trained on Baidu features can run on features extracted from any video.

    train: pairs (src[t + offset], baidu[t]) from games that have both files
           - finds the time offset between the two feature files
           - ridge regression (default) or a small MLP, input = src rows t-context..t+context
           - lambda / epochs picked on --val_splits, final numbers on --test_splits
    apply: writes 1_/2_<out_name> (8576-d, same rows as src) for every game of --splits that has src

Usage:
    python feature_mapper.py train --soccernet_path dataset/caption-2024 --out models/mapper_timesformer.pt
    python feature_mapper.py apply --soccernet_path dataset/caption-2024 --mapper models/mapper_timesformer.pt \
        --splits test --out_name baidu_from_timesformer.npy --ref_name baidu_ref.npy
"""
import argparse
import json
import os
import shutil

import numpy as np
import torch
import torch.nn as nn
from SoccerNet.utils import getListGames

# column blocks of the Baidu embedding (TPN, GTA, VTN, irCSN, I3D-Slow)
BLOCKS = [("TPN", 0, 2048), ("GTA", 2048, 4096), ("VTN", 4096, 4480), ("irCSN", 4480, 6528), ("I3D-Slow", 6528, 8576)]


def games_with(path, splits, files):
    games = []
    for s in splits:
        for g in getListGames([s], task="caption"):
            g = g.replace("\\", "/")
            if all(os.path.exists(os.path.join(path, g, f"{h}_{f}")) for h in (1, 2) for f in files):
                games.append(g)
    return games


def load_halves(path, games, src, tgt=None):
    halves = []
    for g in games:
        for h in (1, 2):
            s = np.load(os.path.join(path, g, f"{h}_{src}")).astype(np.float32)
            t = np.load(os.path.join(path, g, f"{h}_{tgt}"), mmap_mode="r") if tgt else None
            halves.append((g, h, s, t))
    return halves


def context_rows(s, n, offset, context):
    """Rows src[t + offset + j], j in [-context, context], for t < n, clamped at the ends: [n, (2c+1)*768]."""
    t = np.arange(n)[:, None] + offset + np.arange(-context, context + 1)[None, :]
    return s[np.clip(t, 0, len(s) - 1)].reshape(n, -1)


def pairs(half, offset, context):
    _, _, s, t = half
    n = min(len(s), len(t))
    return context_rows(s, n, offset, context), np.asarray(t[:n], dtype=np.float32)


# ----------------------------------------------------------------------------- ridge
class Stats:
    """Running sums for ridge regression without keeping every row in memory."""

    def __init__(self, dx, dy, device):
        z = lambda *s: torch.zeros(*s, dtype=torch.float64, device=device)
        self.n, self.sx, self.sy, self.xx, self.xy = 0, z(dx), z(dy), z(dx, dx), z(dx, dy)
        self.sxx_diag, self.ymin, self.ymax = z(dx), None, None
        self.device = device

    def add(self, x, y):
        x = torch.from_numpy(x).to(self.device, torch.float64)
        y = torch.from_numpy(y).to(self.device, torch.float64)
        self.n += len(x)
        self.sx += x.sum(0)
        self.sy += y.sum(0)
        self.xx += x.T @ x
        self.xy += x.T @ y
        lo, hi = y.min(0).values, y.max(0).values
        self.ymin = lo if self.ymin is None else torch.minimum(self.ymin, lo)
        self.ymax = hi if self.ymax is None else torch.maximum(self.ymax, hi)

    def solve(self, lambdas):
        """Ridge on standardized inputs. Returns {lambda: (W, b)} with y = x @ W + b in raw units."""
        mx, my = self.sx / self.n, self.sy / self.n
        cxx = self.xx - self.n * torch.outer(mx, mx)
        cxy = self.xy - self.n * torch.outer(mx, my)
        sd = (torch.diag(cxx) / self.n).clamp_min(1e-12).sqrt()
        cxx = cxx / torch.outer(sd, sd)
        cxy = cxy / sd[:, None]
        e, q = torch.linalg.eigh(cxx)
        qtxy = q.T @ cxy
        out = {}
        for lam in lambdas:
            ws = q @ (qtxy / (e.clamp_min(0) + lam * self.n)[:, None])  # standardized-x weights
            w = ws / sd[:, None]
            out[lam] = (w.float(), (my - mx @ w).float())
        return out


class Mapper:
    def __init__(self, cfg, w=None, b=None, mlp=None):
        self.cfg, self.w, self.b, self.mlp = cfg, w, b, mlp
        self.ymin, self.ymax = cfg["ymin"], cfg["ymax"]

    @torch.no_grad()
    def __call__(self, s, device="cpu"):
        """s: src features [N, 768] -> [N, 8576] (one output row per src row)."""
        x = torch.from_numpy(context_rows(s, len(s), self.cfg["offset"], self.cfg["context"])).to(device)
        if self.cfg["kind"] == "ridge":
            y = x @ self.w.to(device) + self.b.to(device)
        else:
            m = self.mlp.to(device).eval()
            xs = (x - self.cfg["x_mean"].to(device)) / self.cfg["x_std"].to(device)
            y = torch.cat([m(xs[i:i + 4096]) for i in range(0, len(xs), 4096)])
            y = y * self.cfg["y_std"].to(device) + self.cfg["y_mean"].to(device)
        y = torch.maximum(torch.minimum(y, self.ymax.to(device)), self.ymin.to(device))
        return y.cpu().numpy().astype(np.float32)

    def save(self, path, extra):
        state = {"cfg": self.cfg, "w": self.w, "b": self.b,
                 "mlp": self.mlp.state_dict() if self.mlp is not None else None, **extra}
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        torch.save(state, path)

    @staticmethod
    def load(path):
        st = torch.load(path, map_location="cpu", weights_only=False)
        mlp = None
        if st["mlp"] is not None:
            mlp = make_mlp(st["cfg"]["dx"], st["cfg"]["hidden"], 8576)
            mlp.load_state_dict(st["mlp"])
        return Mapper(st["cfg"], st["w"], st["b"], mlp)


def make_mlp(dx, hidden, dy):
    return nn.Sequential(nn.Linear(dx, hidden), nn.GELU(), nn.Dropout(0.1), nn.Linear(hidden, dy))


# ----------------------------------------------------------------------------- metrics
def evaluate(predict, halves, offset, context):
    """Cosine per row (overall and per block), mean per-dim Pearson r and R2 over the given halves."""
    cos, cos_blocks, n = [], {b[0]: [] for b in BLOCKS}, 0
    sp = st = spp = stt = spt = None
    for half in halves:
        _, _, s, t = half
        k = min(len(s), len(t))
        p = predict(s)[:k]
        t = np.asarray(t[:k], dtype=np.float32)
        cos.append(_cos(p, t))
        for name, a, b in BLOCKS:
            cos_blocks[name].append(_cos(p[:, a:b], t[:, a:b]))
        p64, t64 = p.astype(np.float64), t.astype(np.float64)
        sums = [p64.sum(0), t64.sum(0), (p64 ** 2).sum(0), (t64 ** 2).sum(0), (p64 * t64).sum(0)]
        if sp is None:
            sp, st, spp, stt, spt = sums
        else:
            sp, st, spp, stt, spt = [a + b for a, b in zip((sp, st, spp, stt, spt), sums)]
        n += k
    cov = spt / n - sp / n * st / n
    vp, vt = spp / n - (sp / n) ** 2, stt / n - (st / n) ** 2
    r = cov / np.sqrt(np.clip(vp * vt, 1e-20, None))
    sse = (spp - 2 * spt + stt).sum()
    sst = (vt * n).sum()
    return {"cosine": float(np.concatenate(cos).mean()),
            "cosine_ge_0.95": float((np.concatenate(cos) >= 0.95).mean()),
            **{f"cosine_{k}": float(np.concatenate(v).mean()) for k, v in cos_blocks.items()},
            "pearson_r_mean": float(r[vt > 1e-12].mean()),
            "R2": float(1 - sse / sst),
            "rows": int(n)}


def _cos(a, b):
    return (a * b).sum(1) / np.clip(np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1), 1e-12, None)


def reference(halves):
    """What the cosine numbers mean: Baidu vs itself one second later, and vs random seconds."""
    rng = np.random.default_rng(0)
    nb, rnd = [], []
    for _, _, _, t in halves:
        t = np.asarray(t, dtype=np.float32)
        nb.append(_cos(t[:-1], t[1:]))
        rnd.append(_cos(t[rng.integers(0, len(t), 2000)], t[rng.integers(0, len(t), 2000)]))
    return {"baidu_next_second": float(np.concatenate(nb).mean()), "baidu_random_second": float(np.concatenate(rnd).mean())}


# ----------------------------------------------------------------------------- train
def fit_ridge(train, offset, context, lambdas, device):
    dx = 768 * (2 * context + 1)
    stats = Stats(dx, 8576, device)
    for half in train:
        stats.add(*pairs(half, offset, context))
    return stats, stats.solve(lambdas)


def ridge_mapper(w, b, stats, offset, context):
    cfg = {"kind": "ridge", "offset": offset, "context": context, "ymin": stats.ymin.float().cpu(),
           "ymax": stats.ymax.float().cpu()}
    return Mapper(cfg, w.cpu(), b.cpu())


def train_mlp(train, val, offset, context, args, ymin, ymax):
    """MLP on the same context rows as ridge. Memory: only the 768-d rows (fp32) and the 8576-d targets (fp16)
    are kept on the device; the context rows of each batch are gathered on the fly (all rows at once would
    need >10 GB for 40 games)."""
    dev = args.device
    srcs, idx, tgts, base = [], [], [], 0
    for _, _, s, t in train:
        n = min(len(s), len(t))
        rows = np.arange(n)[:, None] + offset + np.arange(-context, context + 1)[None, :]
        idx.append(np.clip(rows, 0, len(s) - 1) + base)   # context stays inside its half
        srcs.append(s)
        tgts.append(np.asarray(t[:n], dtype=np.float16))
        base += len(s)
    src = torch.from_numpy(np.concatenate(srcs))
    idx = torch.from_numpy(np.concatenate(idx)).to(dev)
    s_mean, s_std = src.mean(0), src.std(0) + 1e-6
    y = torch.from_numpy(np.concatenate(tgts))
    del srcs, tgts
    y_mean = torch.zeros(y.shape[1], dtype=torch.float64)
    y_sq = torch.zeros(y.shape[1], dtype=torch.float64)
    for i in range(0, len(y), 65536):
        c = y[i:i + 65536].double()
        y_mean += c.sum(0)
        y_sq += (c ** 2).sum(0)
    y_mean /= len(y)
    y_std = (y_sq / len(y) - y_mean ** 2).clamp_min(0).sqrt().float() + 1e-6
    y_mean = y_mean.float()
    k = 2 * context + 1
    cfg = {"kind": "mlp", "offset": offset, "context": context, "dx": 768 * k, "hidden": args.hidden,
           "x_mean": s_mean.repeat(k), "x_std": s_std.repeat(k), "y_mean": y_mean, "y_std": y_std,
           "ymin": ymin, "ymax": ymax}
    xs = ((src - s_mean) / s_std).to(dev)
    ys = torch.empty(y.shape, dtype=torch.float16, device=dev)  # z-scores: every block weighs the same
    for i in range(0, len(y), 65536):
        ys[i:i + 65536] = ((y[i:i + 65536].float() - y_mean) / y_std).to(dev, torch.float16)
    del src, y
    print(f"  {len(idx)} training rows, input {cfg['dx']}, output 8576")
    mlp = make_mlp(cfg["dx"], args.hidden, 8576).to(dev)
    opt = torch.optim.AdamW(mlp.parameters(), lr=args.lr, weight_decay=0.05)
    best, best_state = -1, None
    for epoch in range(args.epochs):
        mlp.train()
        perm = torch.randperm(len(idx), device=dev)
        for i in range(0, len(idx), args.mlp_batch):
            j = perm[i:i + args.mlp_batch]
            loss = nn.functional.mse_loss(mlp(xs[idx[j]].reshape(len(j), -1)), ys[j].float())
            opt.zero_grad()
            loss.backward()
            opt.step()
        m = Mapper(cfg, mlp=mlp)
        score = evaluate(lambda s: m(s, dev), val, offset, context)["cosine"]
        print(f"  mlp epoch {epoch + 1}: train mse {loss.item():.4f}, val cosine {score:.4f}")
        if score > best:
            best, best_state = score, {k: v.detach().cpu().clone() for k, v in mlp.state_dict().items()}
    mlp.load_state_dict(best_state)
    return Mapper(cfg, mlp=mlp.cpu())


def train(args):
    files = [args.src, args.tgt]
    tr_games = games_with(args.soccernet_path, args.train_splits, files)
    va_games = games_with(args.soccernet_path, args.val_splits, files)
    te_games = games_with(args.soccernet_path, args.test_splits, files)
    print(f"games with {args.src} and {args.tgt}: train {len(tr_games)}, val {len(va_games)}, test {len(te_games)}")
    if not tr_games or not va_games:
        raise SystemExit("need games with both files in the train and val splits")
    tr = load_halves(args.soccernet_path, tr_games, args.src, args.tgt)
    va = load_halves(args.soccernet_path, va_games, args.src, args.tgt)
    te = load_halves(args.soccernet_path, te_games, args.src, args.tgt)
    dev = args.device

    # 1) time offset between the files: quick ridge without context, scored on val
    print("offset search (ridge, no context):")
    scores = {}
    for k in range(-args.max_offset, args.max_offset + 1):
        stats, sol = fit_ridge(tr, k, 0, [args.lambdas[len(args.lambdas) // 2]], dev)
        (w, b), = sol.values()
        m = ridge_mapper(w, b, stats, k, 0)
        scores[k] = evaluate(lambda s: m(s, dev), va, k, 0)["cosine"]
        print(f"  offset {k:+d}: val cosine {scores[k]:.4f}")
    offset = max(scores, key=scores.get)
    print(f"best offset {offset:+d}")

    # 2) ridge with context, lambda picked on val
    stats, sol = fit_ridge(tr, offset, args.context, args.lambdas, dev)
    best = None
    for lam, (w, b) in sol.items():
        m = ridge_mapper(w, b, stats, offset, args.context)
        r = evaluate(lambda s: m(s, dev), va, offset, args.context)
        print(f"ridge context {args.context} lambda {lam:g}: val cosine {r['cosine']:.4f}, r {r['pearson_r_mean']:.3f}")
        if best is None or r["cosine"] > best[0]:
            best = (r["cosine"], lam, m)
    _, lam, mapper = best
    mapper.cfg["lambda"] = lam

    if args.mlp:
        print(f"MLP (hidden {args.hidden}, {args.epochs} epochs):")
        mlp_mapper = train_mlp(tr, va, offset, args.context, args, mapper.ymin, mapper.ymax)
        if evaluate(lambda s: mlp_mapper(s, dev), va, offset, args.context)["cosine"] > best[0]:
            mapper = mlp_mapper
        else:
            print("MLP is not better than ridge on val, keeping ridge")

    report = {"src": args.src, "tgt": args.tgt, "kind": mapper.cfg["kind"], "offset": offset,
              "context": args.context, "lambda": lam, "offset_search": scores,
              "games": {"train": tr_games, "val": va_games, "test": te_games},
              "val": evaluate(lambda s: mapper(s, dev), va, offset, args.context),
              "reference_val": reference(va)}
    if te:
        report["test"] = evaluate(lambda s: mapper(s, dev), te, offset, args.context)
        report["reference_test"] = reference(te)
    mapper.save(args.out, {"report": report})
    with open(os.path.splitext(args.out)[0] + "_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({k: report[k] for k in ("kind", "offset", "context", "lambda", "val", "reference_val")
                      + (("test", "reference_test") if te else ())}, indent=2))
    print("saved", args.out)


def apply(args):
    mapper = Mapper.load(args.mapper)
    if args.games:  # any folders (e.g. new matches that are not in the SoccerNet splits)
        games = [g.replace("\\", "/") for g in args.games]
        print(f"{len(games)} games given with --games")
    else:
        games = games_with(args.soccernet_path, args.splits, [args.src])
        print(f"{len(games)} games with {args.src} in {args.splits}")
    for g in games:
        for h in (1, 2):
            out = os.path.join(args.soccernet_path, g, f"{h}_{args.out_name}")
            if not os.path.exists(out) or args.overwrite:
                np.save(out, mapper(np.load(os.path.join(args.soccernet_path, g, f"{h}_{args.src}")), args.device))
            if args.ref_name:  # same games under another name, to compare with the real features
                real = os.path.join(args.soccernet_path, g, f"{h}_{args.tgt}")
                ref = os.path.join(args.soccernet_path, g, f"{h}_{args.ref_name}")
                if os.path.exists(real) and not os.path.exists(ref):
                    try:
                        os.link(real, ref)
                    except OSError:
                        shutil.copyfile(real, ref)
        print("done:", g)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("train", "apply"):
        q = sub.add_parser(name)
        q.add_argument("--soccernet_path", required=True)
        q.add_argument("--src", default="timesformer768.npy")
        q.add_argument("--tgt", default="baidu_soccer_embeddings.npy")
        q.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    t = sub.choices["train"]
    t.add_argument("--out", default="models/mapper_timesformer.pt")
    t.add_argument("--train_splits", nargs="+", default=["train"])
    t.add_argument("--val_splits", nargs="+", default=["valid"])
    t.add_argument("--test_splits", nargs="+", default=["test"])
    t.add_argument("--max_offset", type=int, default=4)
    t.add_argument("--context", type=int, default=2, help="also use src rows t-context..t+context")
    t.add_argument("--lambdas", type=float, nargs="+", default=[1e-3, 1e-2, 1e-1, 1, 10])
    t.add_argument("--mlp", action="store_true", help="also train an MLP and keep it if it beats ridge on val")
    t.add_argument("--hidden", type=int, default=2048)
    t.add_argument("--epochs", type=int, default=20)
    t.add_argument("--lr", type=float, default=1e-3)
    t.add_argument("--mlp_batch", type=int, default=512)
    a = sub.choices["apply"]
    a.add_argument("--mapper", required=True)
    a.add_argument("--splits", nargs="+", default=["test"])
    a.add_argument("--games", nargs="+", default=None,
                   help="game folders relative to --soccernet_path (instead of --splits), e.g. new matches")
    a.add_argument("--out_name", default="baidu_from_timesformer.npy")
    a.add_argument("--ref_name", default=None, help="also link the real Baidu files of the same games under this name")
    a.add_argument("--overwrite", action="store_true")
    args = p.parse_args()
    train(args) if args.cmd == "train" else apply(args)


if __name__ == "__main__":
    main()
