"""Extract Baidu's SoccerNet-finetuned TimeSformer features (768-d) from match videos, in PyTorch.

PyTorch port of the PaddleVideo model used by https://github.com/baidu-research/Soccernet-features
(VisionTransformer_tweaks, divided space-time attention, 16 frames, 224x224) and of its one-file
inference pipeline:
  - the video is sampled on a 5 fps grid (Baidu converts videos to 5 fps first)
  - one clip per second: frames linspace(int(start*5), int((start+5)*5), 16) of a 5 s window
  - pixels / 255 (mean 0, std 1), short side resized to 224 (bilinear), center crop 224x224
  - feature = final LayerNorm of the CLS token (the head's input)

Differences with the original, on purpose:
  - one row per second of video (Baidu's loop gives length-5 rows). Row t uses the window starting at
    t - center_offset (clamped to the video), so with center_offset=2 the 5 s window is centred on
    second t like the rows of 1_baidu_soccer_embeddings.npy (and the npy has the same number of rows).
  - batched on the GPU with fp16 autocast (Baidu: batch 1, fp32, 2-3 h per half).

Weights: the .pdparams file from the README of baidu-research/Soccernet-features (OneDrive / Baidu Pan).
Loading it needs no PaddlePaddle when it is a plain pickle of numpy arrays, otherwise `pip install paddlepaddle`.

Usage:
    # every game folder under video_root with 1_224p.mkv / 2_224p.mkv -> <out_root>/<game>/1_timesformer768.npy
    python timesformer_extract.py --weights ppTimeSformer.pdparams --video_root videos_raw/Dataset --out_root dataset/caption-2024
    # one video
    python timesformer_extract.py --weights ppTimeSformer.pdparams --video match_half1.mp4 --out 1_timesformer768.npy
"""
import argparse
import glob
import math
import os
import pickle
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


# ----------------------------------------------------------------------------- model
class Attention(nn.Module):
    def __init__(self, dim, num_heads, qkv_bias=False):
        super().__init__()
        self.num_heads = num_heads
        self.qkv = nn.Linear(dim, dim * 3, bias=qkv_bias)
        self.proj = nn.Linear(dim, dim)

    def forward(self, x):
        B, N, C = x.shape
        q, k, v = self.qkv(x).reshape(B, N, 3, self.num_heads, C // self.num_heads).permute(2, 0, 3, 1, 4)
        x = F.scaled_dot_product_attention(q, k, v)  # scale = head_dim ** -0.5, as in Paddle
        return self.proj(x.transpose(1, 2).reshape(B, N, C))


class Mlp(nn.Module):
    def __init__(self, dim, hidden):
        super().__init__()
        self.fc1 = nn.Linear(dim, hidden)
        self.act = nn.GELU()  # exact erf GELU, Paddle's default
        self.fc2 = nn.Linear(hidden, dim)

    def forward(self, x):
        return self.fc2(self.act(self.fc1(x)))


class Block(nn.Module):
    """Divided space-time block, same token order and reshapes as Paddle's Block."""

    def __init__(self, dim, num_heads, mlp_ratio, qkv_bias, eps):
        super().__init__()
        self.norm1 = nn.LayerNorm(dim, eps=eps)
        self.attn = Attention(dim, num_heads, qkv_bias)
        self.temporal_norm1 = nn.LayerNorm(dim, eps=eps)
        self.temporal_attn = Attention(dim, num_heads, qkv_bias)
        self.temporal_fc = nn.Linear(dim, dim)
        self.norm2 = nn.LayerNorm(dim, eps=eps)
        self.mlp = Mlp(dim, int(dim * mlp_ratio))

    def forward(self, x, B, T, W):
        M = x.shape[-1]
        H = (x.shape[1] - 1) // T // W
        # temporal attention: patch tokens are ordered (h, w, t)
        xt = x[:, 1:, :]
        res_t = self.temporal_attn(self.temporal_norm1(xt.reshape(-1, T, M))).reshape(B, H * W * T, M)
        xt = xt + self.temporal_fc(res_t)
        # spatial attention, one CLS copy per frame
        init_cls = x[:, :1, :]
        cls = init_cls.repeat(1, T, 1).reshape(B * T, 1, M)
        xs = xt.reshape(B, H, W, T, M).permute(0, 3, 1, 2, 4).reshape(B * T, H * W, M)
        res_s = self.attn(self.norm1(torch.cat((cls, xs), dim=1)))
        cls = res_s[:, 0, :].reshape(B, T, M).mean(1, keepdim=True)
        res_s = res_s[:, 1:, :].reshape(B, T, H, W, M).permute(0, 2, 3, 1, 4).reshape(B, H * W * T, M)
        x = torch.cat((init_cls, xt), dim=1) + torch.cat((cls, res_s), dim=1)
        return x + self.mlp(self.norm2(x))


class TimeSformer(nn.Module):
    def __init__(self, img_size=224, patch_size=16, embed_dim=768, depth=12, num_heads=12, mlp_ratio=4,
                 qkv_bias=False, eps=1e-6, num_seg=16, num_classes=18):
        super().__init__()
        self.patch_embed = nn.Module()
        self.patch_embed.proj = nn.Conv2d(3, embed_dim, kernel_size=patch_size, stride=patch_size)
        num_patches = (img_size // patch_size) ** 2
        self.cls_token = nn.Parameter(torch.zeros(1, 1, embed_dim))
        self.pos_embed = nn.Parameter(torch.zeros(1, num_patches + 1, embed_dim))
        self.time_embed = nn.Parameter(torch.zeros(1, num_seg, embed_dim))
        self.blocks = nn.ModuleList([Block(embed_dim, num_heads, mlp_ratio, qkv_bias, eps) for _ in range(depth)])
        self.norm = nn.LayerNorm(embed_dim, eps=eps)
        # head of the SoccerNet fine-tuning (18 classes + event time), kept to check the weights load
        self.head = nn.Module()
        self.head.fc = nn.Linear(embed_dim, num_classes)
        self.head.fc_event_times = nn.Linear(embed_dim, num_classes)

    def forward(self, x):
        """x: [B, 3, T, 224, 224] in [0, 1]. Returns the 768-d CLS feature."""
        B, C, T, Hi, Wi = x.shape
        x = self.patch_embed.proj(x.transpose(1, 2).reshape(B * T, C, Hi, Wi))  # [BT, F, nH, nW]
        W = x.shape[-1]
        x = x.flatten(2).transpose(1, 2)  # [BT, n, F]
        x = torch.cat((self.cls_token.expand(B * T, -1, -1), x), dim=1) + self.pos_embed
        cls = x[:B, :1, :]  # cls_token + pos_embed[0], identical for every row
        n, M = x.shape[1] - 1, x.shape[2]
        x = x[:, 1:].reshape(B, T, n, M).transpose(1, 2).reshape(-1, T, M)
        x = x + self.time_embed
        x = torch.cat((cls, x.reshape(B, n * T, M)), dim=1)
        for blk in self.blocks:
            x = blk(x, B, T, W)
        return self.norm(x)[:, 0]


def load_pdparams(path):
    """Read a .pdparams file into {name: numpy array}."""
    try:
        with open(path, "rb") as f:
            state = pickle.load(f, encoding="latin1")
        if not isinstance(state, dict):
            raise TypeError(type(state))
        state = {k: np.asarray(v) for k, v in state.items() if k != "StructuredToParameterName@@"}
    except Exception as e:  # saved with Paddle objects inside
        print(f"plain pickle failed ({e}), loading with paddle")
        import paddle
        state = {k: v.numpy() for k, v in paddle.load(path).items()}
    return state


def build_model(weights):
    model = TimeSformer()
    state = load_pdparams(weights)
    own = model.state_dict()
    new = {}
    for k, v in state.items():
        name = k[len("backbone."):] if k.startswith("backbone.") else k
        if name not in own:
            print("unused weight:", k, v.shape)
            continue
        t = torch.from_numpy(np.ascontiguousarray(v)).float()
        if t.ndim == 2 and name.endswith(".weight"):  # Paddle Linear stores [in, out]
            t = t.t()
        if t.shape != own[name].shape:
            raise ValueError(f"{k}: {tuple(t.shape)} vs {tuple(own[name].shape)}")
        new[name] = t
    missing = [k for k in own if k not in new]
    if [k for k in missing if not k.startswith("head.")]:
        raise ValueError(f"missing weights: {missing}")
    model.load_state_dict(new, strict=False)
    print(f"loaded {len(new)} tensors from {weights}" + (f" (no head: {missing})" if missing else ""))
    return model.eval()


# ----------------------------------------------------------------------------- video
def read_grid(path, fps=5.0, size=224, device="cpu"):
    """Decode a video on a `fps` grid. Returns (uint8 tensor [N, 3, size, size], duration in seconds)."""
    import av
    container = av.open(path)
    stream = container.streams.video[0]
    stream.thread_type = "AUTO"
    duration = float(container.duration / av.time_base) if container.duration else float(stream.duration * stream.time_base)
    w0, h0 = stream.codec_context.width, stream.codec_context.height
    # Baidu runs on videos converted to 456x256 first: scale big videos down to a 256 short side with
    # swscale, then resize the short side to 224 with bilinear interpolation like JitterScale
    if min(w0, h0) > 256:
        w1, h1 = (round(w0 * 256 / h0 / 2) * 2, 256) if h0 <= w0 else (256, round(h0 * 256 / w0 / 2) * 2)
    else:
        w1, h1 = w0, h0
    if h1 <= w1:
        w2, h2 = int(math.floor(w1 / h1 * size)), size
    else:
        w2, h2 = size, int(math.floor(h1 / w1 * size))
    x1, y1 = int(round((w2 - size) / 2.0)), int(round((h2 - size) / 2.0))

    frames, next_t, step = [], 0.0, 1.0 / fps
    batch = []

    def flush():
        if not batch:
            return
        x = torch.from_numpy(np.stack(batch)).to(device).permute(0, 3, 1, 2)  # [n, 3, h1, w1] uint8
        if (h2, w2) != (h1, w1):
            x = F.interpolate(x.float(), size=(h2, w2), mode="bilinear", align_corners=False)
            x = x.round().clamp(0, 255).to(torch.uint8)
        frames.append(x[:, :, y1:y1 + size, x1:x1 + size].contiguous())
        batch.clear()

    for frame in container.decode(stream):
        if frame.time is None or frame.time + 1e-6 < next_t:
            continue
        img = frame.to_ndarray(format="rgb24", width=w1, height=h1)
        while next_t <= frame.time + 1e-6:  # duplicate the frame if the source has gaps
            batch.append(img)
            next_t += step
        if len(batch) >= 256:
            flush()
    flush()
    container.close()
    return torch.cat(frames), duration


@torch.no_grad()
def extract(model, grid, n_rows, fps=5.0, clip_secs=5.0, num_seg=16, center_offset=2.0, batch_size=32,
            device="cuda", amp=True):
    """One 768-d feature per second t (window [t - center_offset, t - center_offset + clip_secs])."""
    n_frames = grid.shape[0]
    last_start = max(n_rows - clip_secs, 0)
    starts = np.clip(np.arange(n_rows) - center_offset, 0, last_start)
    idx = np.stack([np.linspace(int(s * fps), int((s + clip_secs) * fps), num_seg).astype(np.int64) for s in starts])
    idx = torch.from_numpy(np.minimum(idx, n_frames - 1))
    out = np.zeros((n_rows, 768), dtype=np.float32)
    for i in range(0, n_rows, batch_size):
        clips = grid[idx[i:i + batch_size].to(grid.device)]  # [b, T, 3, 224, 224] uint8
        x = clips.to(device, non_blocking=True).permute(0, 2, 1, 3, 4).float().div_(255.0)
        with torch.autocast("cuda", dtype=torch.float16, enabled=amp and device == "cuda"):
            out[i:i + batch_size] = model(x).float().cpu().numpy()
    return out


def process(model, video, out, args):
    t0 = time.time()
    grid, duration = read_grid(video, args.fps, device=args.grid_device)
    t1 = time.time()
    n_rows = int(duration)  # one row per full second, like the Baidu npy
    feats = extract(model, grid, n_rows, args.fps, args.clip_secs, args.num_seg, args.center_offset,
                    args.batch_size, args.device, not args.fp32)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    np.save(out, feats)
    print(f"{out}: {feats.shape} | decode {t1 - t0:.0f}s ({grid.shape[0]} frames), model {time.time() - t1:.0f}s")
    del grid


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--weights", required=True, help=".pdparams file of Baidu's SoccerNet TimeSformer")
    p.add_argument("--video", help="single video file")
    p.add_argument("--out", help="output .npy for --video")
    p.add_argument("--video_root", help="folder with <league>/<season>/<game>/{1,2}_224p.mkv")
    p.add_argument("--out_root", help="where to write <league>/<season>/<game>/{1,2}_<name>")
    p.add_argument("--video_name", default="{half}_224p.mkv")
    p.add_argument("--name", default="timesformer768.npy")
    p.add_argument("--games", nargs="*", help="only these games (relative paths)")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--fps", type=float, default=5.0)
    p.add_argument("--clip_secs", type=float, default=5.0)
    p.add_argument("--num_seg", type=int, default=16)
    p.add_argument("--center_offset", type=float, default=2.0, help="row t uses the window starting at t - center_offset")
    p.add_argument("--batch_size", type=int, default=32)
    p.add_argument("--fp32", action="store_true", help="disable fp16 autocast")
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    p.add_argument("--grid_device", default=None, help="where decoded frames live (default: same as --device)")
    args = p.parse_args()
    args.grid_device = args.grid_device or args.device

    model = build_model(args.weights).to(args.device)
    if args.video:
        process(model, args.video, args.out or os.path.splitext(args.video)[0] + "_" + args.name, args)
        return
    pattern = os.path.join(args.video_root, "**", args.video_name.format(half="[12]"))
    videos = sorted(v.replace("\\", "/") for v in glob.glob(pattern, recursive=True))
    root = args.video_root.replace("\\", "/").rstrip("/")
    for v in videos:
        game = os.path.dirname(v)[len(root) + 1:]
        if args.games and game not in args.games:
            continue
        half = os.path.basename(v)[0]
        out = os.path.join(args.out_root, game, f"{half}_{args.name}")
        if os.path.exists(out) and not args.overwrite:
            print("exists:", out)
            continue
        process(model, v, out, args)


if __name__ == "__main__":
    main()
