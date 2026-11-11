"""Cut a full-match video into the two halves SoccerNet-style: <out_dir>/1_224p.mp4 and 2_224p.mp4.

Each half starts exactly at its kick-off (second 0 of the half = the FIFA minute 0' / 45'), so events from
fifa_crawl.py (events.csv: half, second) line up with the video. The video is re-encoded (an exact cut, not
at the nearest keyframe), scaled to 224 pixels high (TimeSformer works at 224) and without sound.
Needs only PyAV (pip install av), no ffmpeg install.

usage:
    python cut_halves.py match.mp4 --t1 12:34 --t2 1:10:05 \
        --out_dir "videos/fifa_world-cup/2026/2026-07-06 - Mexico 2 - 3 England"
    --t1 / --t2: kick-off of the 1st / 2nd half in the video (seconds, mm:ss or hh:mm:ss)
"""
import argparse
import os
from fractions import Fraction

import av


def parse_time(s):
    """'75', '1:15', '1:01:15' -> seconds"""
    sec = 0.0
    for part in s.split(":"):
        sec = sec * 60 + float(part)
    return sec


def pick_encoder():
    for name in ("libx264", "h264", "mpeg4"):
        try:
            av.codec.Codec(name, "w")
            return name
        except Exception:
            continue
    raise SystemExit("no video encoder available in PyAV")


def cut(src, start, duration, dst, height, encoder):
    with av.open(src) as inp:
        vs = inp.streams.video[0]
        vs.thread_type = "AUTO"
        rate = Fraction(vs.average_rate or 25).limit_denominator(1001)
        width = round(vs.codec_context.width * height / vs.codec_context.height / 2) * 2
        inp.seek(int(start / vs.time_base), stream=vs, backward=True)  # nearest keyframe before start
        with av.open(dst, "w") as out:
            st = out.add_stream(encoder, rate=rate)
            st.width, st.height, st.pix_fmt = width, height, "yuv420p"
            if encoder == "libx264":
                st.options = {"crf": "23", "preset": "veryfast"}
            tb, last, n = 1 / rate, -1, 0
            for frame in inp.decode(vs):
                if frame.time is None or frame.time < start:
                    continue  # frames between the keyframe and the exact start
                if frame.time >= start + duration:
                    break
                pts = round((frame.time - start) * rate)
                if pts <= last:
                    continue
                img = frame.reformat(width=width, height=height, format="yuv420p")
                img.pts, img.time_base, last = pts, tb, pts
                out.mux(st.encode(img))
                n += 1
            out.mux(st.encode(None))
    return n, float(last / rate) if n else 0.0


def main():
    p = argparse.ArgumentParser(description="Cut a full match into 1_224p.mp4 / 2_224p.mp4")
    p.add_argument("video")
    p.add_argument("--t1", required=True, help="kick-off of the 1st half in the video")
    p.add_argument("--t2", required=True, help="kick-off of the 2nd half in the video")
    p.add_argument("--out_dir", required=True, help="<league>/<season>/<game> folder for the halves")
    p.add_argument("--duration", type=float, default=50 * 60, help="seconds kept per half (45' + stoppage time)")
    p.add_argument("--height", type=int, default=224)
    a = p.parse_args()

    t1, t2 = parse_time(a.t1), parse_time(a.t2)
    if t2 <= t1:
        raise SystemExit("--t2 must be after --t1")
    os.makedirs(a.out_dir, exist_ok=True)
    encoder = pick_encoder()
    with av.open(a.video) as inp:
        total = float(inp.duration / av.time_base) if inp.duration else None
    print(f"video {a.video}: {total / 60:.1f} min" if total else f"video {a.video}", f"| encoder {encoder}")
    for half, start, limit in ((1, t1, min(a.duration, t2 - t1)), (2, t2, a.duration)):
        dst = os.path.join(a.out_dir, f"{half}_{a.height}p.mp4")
        frames, length = cut(a.video, start, limit, dst, a.height, encoder)
        print(f"half {half}: from {start:.0f}s, {frames} frames, {length / 60:.1f} min -> {dst}")
        if length < 44 * 60:
            print(f"  WARNING: half {half} is shorter than 44 min: check --t{half} and the end of the video")


if __name__ == "__main__":
    main()
