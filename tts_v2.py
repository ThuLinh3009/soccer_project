"""Text-to-speech of the commentary timeline (no_flow_v2.py output) with Gemini TTS, then one audio track per half.

Two voices, like a TV broadcast:
    yes lines (events on the pitch, trained model)   --voice_yes (default Puck),   play-by-play style
    no lines (script 2.0 + LLM)                      --voice_no  (default Charon), presenter style
Default TTS model: gemini-3.8-flash-lite-tts (the Flash-Lite TTS model; there is no "gemini-2.5-flash-lite" TTS).

Each line becomes a wav clip (cached: a line already spoken is not sent again, which saves quota). The clips are
placed at their time in a silent track as long as the half; a clip that would overlap the previous one starts right
after it. With --video_dir, the track is put on the video (ffmpeg): <half>_commentary.mp4.

Key: GEMINI_API_KEY environment variable (Colab: Secrets), never written to a file.

usage:
    python tts_v2.py --timeline "outputs/no_flow_v2/<game>/commentary_timeline.json" \
        --video_dir "../video_test/<...>/<game>" --max_lines 20
"""
import hashlib
import json
import os
import subprocess
from argparse import ArgumentParser

import numpy as np

from gemini_client import Gemini, GeminiError, ModelPool, read_key, save_wav, wav_to_pcm

RATE = 24000


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

    lines = [c for c in data["comments"] if c["half"] in args.halves and not c.get("muted")
             and (args.only == "all" or c["flow"] == args.only) and c.get("text")]
    lines.sort(key=lambda c: (c["half"], c["second"]))
    if args.max_lines:
        lines = lines[:args.max_lines]
    gem = Gemini(read_key(), args.backend, min_interval=60.0 / args.rpm if args.rpm else 0)
    pool = ModelPool(args.tts_model)
    print(f"{data['game']}: {len(lines)} lines to speak | TTS {', '.join(pool.models)} | voices yes {args.voice_yes}, "
          f"no {args.voice_no} | backend {gem.backend}")

    done, failed, cached = [], 0, 0
    for i, c in enumerate(lines):
        voice = args.voice_yes if c["flow"] == "yes" else args.voice_no
        style = style_for(c, args)
        path = clip_path(clip_dir, voice, style, c["text"])
        if os.path.exists(path):
            cached += 1
        else:
            try:
                pcm, rate = pool.call(lambda m: gem.speech(m, c["text"], voice=voice, style=style))
                save_wav(path, pcm, rate)
            except (GeminiError, OSError) as e:
                failed += 1
                print(f"  [{i + 1}/{len(lines)}] {c['gameTime']} TTS failed: {str(e)[:200]}")
                if pool.current is None:
                    print("  no TTS quota left on any model: stopping (clips made so far are kept, run again later)")
                    break
                continue
        done.append((c, path, voice))
        print(f"  [{i + 1}/{len(lines)}] {c['gameTime']} {voice:<7} {c['text'][:90]}")

    placed = []
    for half in args.halves:
        track = np.zeros(int(half_lens[half - 1] * RATE) + RATE, dtype=np.float32)
        free_at = 0
        for c, path, voice in (d for d in done if d[0]["half"] == half):
            audio = load_clip(path)
            start = max(int(c["second"] * RATE), free_at)
            if start >= len(track):
                continue
            end = min(start + len(audio), len(track))
            track[start:end] += audio[:end - start]
            free_at = end + int(0.3 * RATE)
            placed.append({"half": half, "gameTime": c["gameTime"], "start": round(start / RATE, 2),
                           "shift": round(start / RATE - c["second"], 2), "duration": round(len(audio) / RATE, 2),
                           "voice": voice, "flow": c["flow"], "text": c["text"]})
        wav = os.path.join(out_dir, f"{half}_commentary.wav")
        save_wav(wav, np.clip(track, -32768, 32767).astype(np.int16).tobytes(), RATE)
        n = sum(p["half"] == half for p in placed)
        late = [p for p in placed if p["half"] == half and p["shift"] > 5]
        print(f"half {half}: {n} clips -> {wav}" + (f" ({len(late)} moved > 5 s later)" if late else ""))
        if args.video_dir:
            video = os.path.join(args.video_dir, f"{half}_224p.mp4")
            if os.path.exists(video):
                out = os.path.join(out_dir, f"{half}_commentary.mp4")
                mux(video, wav, out, args.original_volume)
                print(f"half {half}: video with commentary -> {out}")
    with open(os.path.join(out_dir, "audio_timeline.json"), "w", encoding="utf-8") as f:
        json.dump({"game": data["game"], "tts_models": pool.models, "clips": placed}, f, indent=2,
                  ensure_ascii=False)
    print(f"{len(done)} clips ({cached} from cache), {failed} failed -> {out_dir}")


if __name__ == "__main__":
    p = ArgumentParser(description="Gemini TTS of the commentary timeline, one audio track per half")
    p.add_argument("--timeline", required=True, help="commentary_timeline.json of no_flow_v2.py")
    p.add_argument("--out_dir", default=None, help="default: <timeline folder>/audio")
    p.add_argument("--video_dir", default=None, help="folder with 1_224p.mp4 / 2_224p.mp4: also write the videos")
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
    p.add_argument("--original_volume", type=float, default=0.25, help="volume of the video's own sound (0 = off)")
    main(p.parse_args())
