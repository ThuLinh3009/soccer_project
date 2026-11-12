"""Text-to-speech of the commentary timeline (no_flow_v2.py output) with Gemini TTS, then one audio track per half.

Two voices, like a TV broadcast:
    yes lines (events on the pitch, trained model)   --voice_yes (default Puck),   play-by-play style
    no lines (script 2.0 + LLM)                      --voice_no  (default Charon), presenter style
Default TTS model: gemini-3.8-flash-lite-tts (the Flash-Lite TTS model; there is no "gemini-2.5-flash-lite" TTS).

Each line becomes a wav clip (cached: a line already spoken is not sent again, which saves quota). The clips are
placed in a silent track as long as the half; with --video_dir, the track is put on the video (ffmpeg):
<half>_commentary.mp4.

Timing (v5.1), with the real length of every clip (silence at both ends cut off):
- a no line that follows the previous one (chain A1 -> A2 -> A3, C1 -> C2, G1 -> G4, or planned less than --join
  seconds after the end of the previous clip) starts at the next whole second after the previous clip ends;
- any other line (and every yes line: never before its event) starts at its time, or at the next whole second
  after the previous clip if that one is still speaking (no overlap);
- the slot of the line (seconds until the next line, from no_flow_v2.py): a clip longer than its slot is sped up
  (WSOLA, the pitch does not change), at most --max_speed times;
- audio_timeline.json: gameTime / gameTimeEnd = when the clip is really heard, planned = time in the script.

Engines (v5.2), --engine:
- gemini (default): Gemini TTS through the API. Key: GEMINI_API_KEY environment variable (Colab: Secrets), never
  written to a file. Free tier: small daily quota.
- kokoro: Kokoro-82M, an open model that runs on this machine (Colab CPU or GPU): no key, no quota, the text is not
  sent anywhere. English only. Needs Python 3.10-3.12 (not 3.13: make a 3.12 environment, e.g. `uv venv --seed
  --python 3.12`), `pip install "kokoro>=0.9.4" soundfile`, `python -m spacy download en_core_web_sm`, espeak-ng.
  Voices --kokoro_voice_yes / --kokoro_voice_no (first letter: a = American, b = British English).

Demo part (v5.2): --start MM:SS --end MM:SS (time in the half) speaks only the lines of that part and also writes
<half>_demo.wav / <half>_demo.mp4, cut to that part.

usage:
    python tts_v2.py --timeline "outputs/no_flow_v2/<game>/commentary_timeline.json" \
        --video_dir "../video_test/<...>/<game>" --max_lines 20
"""
import hashlib
import json
import math
import os
import re
import subprocess
from argparse import ArgumentParser

import numpy as np

from gemini_client import Gemini, GeminiError, ModelPool, read_key, save_wav, wav_to_pcm
from script_v2 import neutral_caption, time_slots

RATE = 24000


def format_game_time(half, sec):  # same as commentary_timeline.py (not imported: it needs the SoccerNet package)
    return f"{half} - {sec // 60:02d}:{sec % 60:02d}"


ORDINAL = {1: "st", 2: "nd", 3: "rd"}


def _ordinal(n):
    n = int(n)
    return f"{n}{'th' if 10 <= n % 100 <= 20 else ORDINAL.get(n % 10, 'th')}"


def spoken_text(text):
    """Text a TTS model reads well: 85' -> 85th minute, 90'+4' -> 90th minute plus 4, 2-1 -> 2 1, 1-0 -> 1 nil,
    3-4-2-1 -> 3 4 2 1, BRIGHT -> Bright, no brackets."""
    t = re.sub(r"(\d+)['’]\s*\+\s*(\d+)['’]?", lambda m: f"{_ordinal(m.group(1))} minute plus {m.group(2)}", text)
    t = re.sub(r"(\d+)['’](?!\w)", lambda m: f"{_ordinal(m.group(1))} minute", t)
    t = re.sub(r"\b\d(?:-\d){2,}\b", lambda m: m.group(0).replace("-", " "), t)  # formation
    t = re.sub(r"\b(\d+)-(\d+)\b", lambda m: f"{m.group(1)} {'nil' if m.group(2) == '0' else m.group(2)}"
               if m.group(1) != "0" else f"nil {'nil' if m.group(2) == '0' else m.group(2)}", t)  # score
    t = re.sub(r"\b[A-ZÀ-Ý]{3,}\b", lambda m: m.group(0) if m.group(0) in ("VAR", "FIFA", "UEFA", "WSL")
               else m.group(0).capitalize(), t)
    t = re.sub(r"\s*\(([^)]*)\)", r", \1,", t)
    t = re.sub(r",\s*([.!?;:])", r"\1", t)
    t = t.replace(";", ",").replace("!!", "!")
    return re.sub(r"\s+", " ", t).strip()


def clock(value):
    """'28:00' or '1680' -> seconds; None stays None."""
    if value in (None, ""):
        return None
    parts = [float(x) for x in str(value).split(":")]
    return parts[0] if len(parts) == 1 else parts[0] * 60 + parts[1]


class Kokoro:
    """Kokoro-82M on this machine. One model, one pipeline per language (first letter of the voice)."""

    def __init__(self):
        import torch
        from kokoro import KModel
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = KModel(repo_id="hexgrad/Kokoro-82M").to(self.device).eval()
        self.pipes = {}
        print(f"  Kokoro-82M on {self.device}")

    def speech(self, text, voice, speed=1.0):
        from kokoro import KPipeline
        lang = voice[0]
        if lang not in self.pipes:
            self.pipes[lang] = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M", model=self.model)
        parts = []
        for _, _, audio in self.pipes[lang](text, voice=voice, speed=speed, split_pattern=r"\n+"):
            if audio is not None:
                parts.append(audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio))
        if not parts:
            raise RuntimeError("Kokoro gave no audio")
        audio = np.concatenate(parts).astype(np.float32)
        return (np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes(), RATE


def cut_video(src, out, start, end):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(start), "-to", str(end), "-i", src,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "128k", out],
                   check=True)


def style_for(c, args):
    if c["flow"] == "yes":
        return args.style_yes
    if c.get("topic") == "goal":
        return args.style_goal
    return args.style_no


def clip_path(clip_dir, voice, style, text):
    h = hashlib.sha1(f"{voice}|{style}|{text}".encode()).hexdigest()[:16]
    return os.path.join(clip_dir, f"{h}.wav")


def load_clip(path):
    with open(path, "rb") as f:
        pcm, rate = wav_to_pcm(f.read())
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if rate != RATE:  # simple resampling (all Gemini TTS models answer at 24 kHz)
        x = np.linspace(0, len(audio) - 1, int(len(audio) * RATE / rate))
        audio = np.interp(x, np.arange(len(audio)), audio)
    return audio


def trim(audio, threshold=0.02, pad=0.05):
    """Cut the silence at both ends of a clip (keeps `pad` seconds)."""
    loud = np.flatnonzero(np.abs(audio) > threshold * max(1.0, np.abs(audio).max()))
    if not len(loud):
        return audio
    p = int(pad * RATE)
    return audio[max(0, loud[0] - p):loud[-1] + p]


def time_stretch(x, speed, win=1024, tol=256):
    """Speed speech up by `speed` (> 1) without changing the pitch: WSOLA (overlap-add of windows, each taken where
    it continues the previous one best)."""
    if speed <= 1.001 or len(x) < 2 * win:
        return x
    hop = win // 2
    w = np.hanning(win).astype(np.float32)
    n_in = len(x)
    x = np.concatenate([x, np.zeros(2 * win + tol, dtype=np.float32)]).astype(np.float32)
    n_out = int(n_in / speed)
    y = np.zeros(n_out + 2 * win, dtype=np.float32)
    norm = np.zeros_like(y)
    pos, out, prev = 0.0, 0, None
    while int(pos) < n_in and out + win <= len(y):
        ideal = int(pos)
        if prev is None:
            start = ideal
        else:
            lo, hi = max(0, ideal - tol), min(len(x) - 2 * win, ideal + tol)
            corr = np.correlate(x[lo:hi + win], prev, "valid")
            start = lo + int(np.argmax(corr))
        y[out:out + win] += x[start:start + win] * w
        norm[out:out + win] += w
        prev = x[start + hop:start + hop + win]
        out += hop
        pos += hop * speed
    y = y / np.maximum(norm, 1e-3)
    return y[:n_out]


def has_audio(video):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                          "-of", "csv=p=0", video], capture_output=True, text=True)
    return bool(out.stdout.strip())


def mux(video, wav, out, original_volume):
    if original_volume > 0 and has_audio(video):
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-i", wav, "-filter_complex",
               f"[0:a]volume={original_volume}[a0];[a0][1:a]amix=inputs=2:duration=first:normalize=0[a]",
               "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", out]
    else:
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-i", wav, "-map", "0:v:0", "-map", "1:a:0",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", out]
    subprocess.run(cmd, check=True)


def main(args):
    data = json.load(open(args.timeline, encoding="utf-8"))
    half_lens = data.get("half_lengths") or [3600, 3600]
    out_dir = args.out_dir or os.path.join(os.path.dirname(args.timeline), "audio")
    clip_dir = os.path.join(out_dir, "clips")
    os.makedirs(clip_dir, exist_ok=True)

    # also reads the timeline of no_flow_llm.py (v1): no slot -> computed here, [PLAYER] ([TEAM]) -> "the player"
    spoken = [c for c in data["comments"] if not c.get("muted") and c.get("text")]
    if any("slot" not in c for c in spoken):
        slots = time_slots([(c["half"], c["second"]) for c in spoken], half_lens, gap=data.get("gap", 0.3))
        for c in spoken:
            c.setdefault("slot", slots[(c["half"], c["second"])])
    for c in spoken:
        if "[" in c["text"]:
            c["text"] = neutral_caption(c["text"])
    lines = [c for c in spoken if c["half"] in args.halves and (args.only == "all" or c["flow"] == args.only)]
    lines.sort(key=lambda c: (c["half"], c["second"]))
    t0, t1 = clock(args.start), clock(args.end)
    if t0 is not None or t1 is not None:  # demo part
        t0 = t0 or 0.0
        lines = [c for c in lines if t0 <= c["second"] and (t1 is None or c["second"] < t1)]
    if args.max_lines:
        lines = lines[:args.max_lines]
    kokoro = args.engine == "kokoro"
    pool = ModelPool("kokoro-82m" if kokoro else args.tts_model)
    voice_yes = args.kokoro_voice_yes if kokoro else args.voice_yes
    voice_no = args.kokoro_voice_no if kokoro else args.voice_no
    gem = []  # created at the first clip that is not in the cache (no key / no model needed when all are cached)
    print(f"{data['game']}: {len(lines)} lines to speak | TTS {', '.join(pool.models)} | voices yes {voice_yes}, "
          f"no {voice_no}")

    done, failed, cached = [], 0, 0
    for i, c in enumerate(lines):
        voice = voice_yes if c["flow"] == "yes" else voice_no
        if kokoro:
            speed = args.speed_goal if c.get("topic") == "goal" else args.speed_yes if c["flow"] == "yes" \
                else args.speed_no
            style, say = f"kokoro x{speed}", spoken_text(c["text"])
        else:
            style, say = style_for(c, args), c["text"]
        path = clip_path(clip_dir, voice, style, say)
        if os.path.exists(path):
            cached += 1
        else:
            try:
                if kokoro:
                    if not gem:
                        gem.append(Kokoro())
                    pcm, rate = gem[0].speech(say, voice, speed)
                else:
                    if not gem:
                        gem.append(Gemini(read_key(), args.backend,
                                          min_interval=60.0 / args.rpm if args.rpm else 0))
                        print(f"  backend {gem[0].backend}")
                    pcm, rate = pool.call(lambda m: gem[0].speech(m, say, voice=voice, style=style))
                save_wav(path, pcm, rate)
            except (GeminiError, OSError, RuntimeError, ValueError) as e:
                failed += 1
                print(f"  [{i + 1}/{len(lines)}] {c['gameTime']} TTS failed: {str(e)[:200]}")
                if pool.current is None:
                    print("  no TTS quota left on any model: stopping (clips made so far are kept, run again later)")
                    break
                continue
        done.append((c, path, voice))
        print(f"  [{i + 1}/{len(lines)}] {c['gameTime']} {voice:<7} {c['text'][:90]}")

    placed, rates = [], {}
    for half in args.halves:
        half_len = half_lens[half - 1]
        track = np.zeros(int(half_len * RATE) + RATE, dtype=np.float32)
        prev_end, prev_code = None, None
        for c, path, voice in (d for d in done if d[0]["half"] == half):
            audio = trim(load_clip(path))
            raw = len(audio) / RATE
            rates.setdefault(voice, []).append(len(c["text"].split()) / max(raw, 0.5))
            nxt = None if prev_end is None else math.ceil(prev_end + args.pause)  # next whole second
            # a no line close after the previous clip is said right after it; a yes line (event on the pitch)
            # is never said before its time
            follows = nxt is not None and c["flow"] == "no" and bool(
                (c.get("after") and c["after"] == prev_code) or c["second"] - prev_end <= args.join)
            start = nxt if follows else max(math.ceil(c["second"]), nxt or 0)
            if start >= half_len:
                continue
            speed = 1.0
            if args.max_speed > 1 and c.get("slot"):  # time left before the next planned line
                avail = c["second"] + c["slot"] - start
                if raw > avail:
                    speed = min(raw / max(avail, 0.1), args.max_speed)
                    audio = time_stretch(audio, speed)
            dur = len(audio) / RATE
            a = int(start * RATE)
            b = min(a + len(audio), len(track))
            track[a:b] += audio[:b - a]
            prev_end, prev_code = start + dur, c.get("code") or None
            placed.append({"half": half, "gameTime": format_game_time(half, int(start)),
                           "gameTimeEnd": format_game_time(half, int(math.ceil(start + dur))),
                           "start": float(start), "end": round(start + dur, 2), "duration": round(dur, 2),
                           "planned": c["gameTime"], "shift": round(start - c["second"], 2),
                           "speed": round(speed, 2), "follows": follows, "voice": voice, "flow": c["flow"],
                           "code": c.get("code", ""), "text": c["text"]})
        wav = os.path.join(out_dir, f"{half}_commentary.wav")
        save_wav(wav, np.clip(track, -32768, 32767).astype(np.int16).tobytes(), RATE)
        mine = [p for p in placed if p["half"] == half]
        late = [p for p in mine if p["shift"] > 5]
        fast = [p for p in mine if p["speed"] > 1.0]
        print(f"half {half}: {len(mine)} clips -> {wav}" + (f" | {len(fast)} sped up" if fast else "")
              + (f" | {len(late)} moved > 5 s later" if late else ""))
        for p in mine:
            note = (f", x{p['speed']}" if p["speed"] > 1 else "") + (f", planned {p['planned'][4:]}"
                                                                      if p["planned"] != p["gameTime"] else "")
            print(f"  {p['gameTime']} -> {p['gameTimeEnd'][4:]}  ({p['duration']:4.1f}s{note})  {p['text'][:70]}")
        demo = t0 is not None
        if demo:
            d1 = min(t1 if t1 is not None else half_len, half_len)
            if mine:  # do not cut a line that is still being spoken
                d1 = min(max(d1, math.ceil(max(p["end"] for p in mine)) + 1), half_len)
            part = track[int(t0 * RATE):int(d1 * RATE)]
            demo_wav = os.path.join(out_dir, f"{half}_demo.wav")
            save_wav(demo_wav, np.clip(part, -32768, 32767).astype(np.int16).tobytes(), RATE)
            print(f"half {half}: demo part {format_game_time(half, int(t0))[4:]} - "
                  f"{format_game_time(half, int(d1))[4:]} -> {demo_wav}")
        if args.video_dir:
            video = os.path.join(args.video_dir, args.video_name.format(half=half))
            if os.path.exists(video):
                out = os.path.join(out_dir, f"{half}_commentary.mp4")
                mux(video, wav, out, args.original_volume)
                print(f"half {half}: video with commentary -> {out}")
                if demo:
                    demo_mp4 = os.path.join(out_dir, f"{half}_demo.mp4")
                    cut_video(out, demo_mp4, t0, d1)
                    print(f"half {half}: demo video -> {demo_mp4}")
            else:
                print(f"half {half}: no video {video}")
    with open(os.path.join(out_dir, "audio_timeline.json"), "w", encoding="utf-8") as f:
        json.dump({"game": data["game"], "tts_models": pool.models,
                   "words_per_second": {v: round(float(np.median(r)), 2) for v, r in rates.items()},
                   "clips": placed}, f, indent=2, ensure_ascii=False)
    print(f"{len(done)} clips ({cached} from cache), {failed} failed -> {out_dir}")
    if rates:
        print(f"measured speech rate, words per second (the schedule used {data.get('wps', 2.6)}): "
              + ", ".join(f"{v} {np.median(r):.2f}" for v, r in rates.items())
              + "  -> give it to no_flow_v2.py --wps for a schedule that fits better")


if __name__ == "__main__":
    p = ArgumentParser(description="Gemini TTS of the commentary timeline, one audio track per half")
    p.add_argument("--timeline", required=True, help="commentary_timeline.json of no_flow_v2.py")
    p.add_argument("--out_dir", default=None, help="default: <timeline folder>/audio")
    p.add_argument("--video_dir", default=None, help="folder with 1_224p.mp4 / 2_224p.mp4: also write the videos")
    p.add_argument("--video_name", default="{half}_224p.mp4",
                   help="video file of a half in --video_dir, e.g. {half}_720p.mp4 (cut_halves.py --height 720)")
    p.add_argument("--engine", choices=["gemini", "kokoro"], default="gemini",
                   help="gemini: API (key, quota) | kokoro: open model on this machine (no key, no quota, English)")
    p.add_argument("--kokoro_voice_yes", default="am_michael", help="Kokoro voice of the yes lines")
    p.add_argument("--kokoro_voice_no", default="bm_george", help="Kokoro voice of the no lines")
    p.add_argument("--speed_yes", type=float, default=1.1, help="Kokoro speaking speed of the yes lines")
    p.add_argument("--speed_no", type=float, default=1.0, help="Kokoro speaking speed of the no lines")
    p.add_argument("--speed_goal", type=float, default=1.15, help="Kokoro speaking speed of a goal line")
    p.add_argument("--start", default=None, help="demo part: speak only from this time of the half (MM:SS)")
    p.add_argument("--end", default=None, help="demo part: ... to this time (MM:SS); also writes <half>_demo.*")
    p.add_argument("--tts_model", default="gemini-3.8-flash-lite-tts,gemini-2.5-flash-preview-tts,"
                                          "gemini-3.1-flash-tts-preview,gemini-3.8-flash-tts",
                   help="TTS models tried in order: the next one is used when a model has no quota left")
    p.add_argument("--backend", choices=["auto", "gemini", "vertex"], default="auto")
    p.add_argument("--voice_yes", default="Puck")
    p.add_argument("--voice_no", default="Charon")
    p.add_argument("--style_yes", default="fast, lively live football play-by-play commentator")
    p.add_argument("--style_no", default="warm, clear TV football presenter")
    p.add_argument("--style_goal", default="very excited football commentator celebrating a goal")
    p.add_argument("--only", choices=["all", "yes", "no"], default="all", help="which lines to speak")
    p.add_argument("--halves", type=int, nargs="+", default=[1, 2])
    p.add_argument("--max_lines", type=int, default=0, help="speak only the first N lines (test, saves quota)")
    p.add_argument("--rpm", type=float, default=10, help="max TTS requests per minute")
    p.add_argument("--max_speed", type=float, default=1.25,
                   help="a clip longer than its time slot is sped up at most this much (1 = never)")
    p.add_argument("--join", type=float, default=5.0,
                   help="a no line planned less than this many seconds after the previous clip ends follows it")
    p.add_argument("--pause", type=float, default=0.2,
                   help="silence after a clip; the next line starts at the next whole second after it")
    p.add_argument("--original_volume", type=float, default=0.25, help="volume of the video's own sound (0 = off)")
    main(p.parse_args())
