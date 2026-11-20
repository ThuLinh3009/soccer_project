"""(v7.7) Score card of a commentary demo: pace, repeats, LLM share and facts, to compare versions on the same match.

Reads what the pipeline wrote, and optionally listens to the video:
- commentary_timeline.json (commentary/no_flow_v2.py): which lines were written by the LLM, the facts each line says;
- audio_timeline.json (voice/tts_v2.py): when each clip is really heard and how long, its speed;
- --video: the demo mp4 is transcribed with Whisper (pip install faster-whisper; runs on this machine, nothing is
  sent out) to check what is actually heard: names and shirt numbers against the metadata.

Score card (the part of the half in --start / --end):
    speech share        % of the time with someone speaking (TV commentary: about 40-60%)
    longest silence     seconds
    words per second    while speaking (natural English commentary: about 2.5-3.2)
    speed               mean speed-up of the clips (voice/tts_v2.py --openai_speed and the fit to the slots)
    LLM share           no-flow lines written by the LLM (the rest are templates)
    repeated facts      facts said more than once (score and clock excluded)
    shirt numbers       "number N" said next to a player's name that is not that player's number (transcript)
    unknown names       capitalised words of the transcript close to no name of the match (Whisper spelling
                        is not exact: a list to read, not an error count)

usage (from the repo root):
    python -m evaluation.check_commentary --timeline ".../timeline_v2/<game>/commentary_timeline.json" \
        --audio_timeline ".../timeline_v2/<game>/audio_openai/audio_timeline.json" \
        --metadata "../video_test/metadata/<game>" --half 1 --start 00:00 --end 10:00 \
        [--video ".../audio_openai/1_demo.mp4"] [--out report.json]
"""
import csv
import difflib
import json
import os
import re
import sys
import unicodedata
from argparse import ArgumentParser
from collections import Counter

NUMBER_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve "
                                           "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty "
                                           "twenty-one twenty-two twenty-three twenty-four twenty-five twenty-six"
                                           .split())}
COMMON = {"I", "The", "A", "An", "It", "It's", "That", "That's", "This", "There", "They", "He", "She", "His", "Her",
          "We", "We're", "And", "But", "With", "In", "On", "At", "For", "Of", "No", "Number", "Still", "Welcome",
          "Hello", "Goal", "Half-time", "Full-time", "Thank", "Thanks", "Stay", "Don't", "Last", "These", "Win",
          "Seven", "Five", "Four", "Three", "Two", "One", "Six", "Eight", "Nine", "Ten", "About", "Up", "Back",
          "Forty", "Thirty", "Twenty", "Fifteen", "June", "July", "May", "April", "March", "August", "Round",
          "World", "Cup", "FIFA", "VAR", "Stadium", "Group", "Final", "Penalty", "Corner", "Yellow", "Red", "Jr",
          "Junior", "Leading", "Played", "Plays", "Today", "Both", "Here", "Now", "Ninety", "Eighty"}


def clock(value):
    if value in (None, ""):
        return None
    parts = [float(x) for x in str(value).split(":")]
    return parts[0] if len(parts) == 1 else parts[0] * 60 + parts[1]


def plain(s):
    s = unicodedata.normalize("NFKD", (s or "").replace("ø", "o").replace("Ø", "O").replace("æ", "ae"))
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower()


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- from the pipeline files
def timeline_card(path, half, t0, t1):
    d = json.load(open(path, encoding="utf-8"))
    lines = [c for c in d["comments"] if c["half"] == half and t0 <= c["second"] < t1 and not c.get("muted")]
    no = [c for c in lines if c["flow"] == "no"]
    asked = [c for c in no if c.get("source") not in (None, "")]
    llm = [c for c in asked if c.get("source") != "template"]
    facts = Counter(f for c in no for f in c.get("facts", []) if f not in ("score", "clock"))
    repeated = {k: v for k, v in facts.items() if v > 1}
    return {"lines": len(lines), "no_lines": len(no), "yes_lines": len(lines) - len(no),
            "events_source": d.get("events_source"), "llm": d.get("llm"),
            "llm_share": round(len(llm) / len(no), 2) if no else None,
            "facts_said": len(facts), "repeated_facts": len(repeated), "repeated": repeated}


def audio_card(path, half, t0, t1):
    d = json.load(open(path, encoding="utf-8"))
    clips = [c for c in d["clips"] if c["half"] == half and t0 <= c["start"] < t1]
    if not clips:
        return {}
    span = min(t1, max(c["end"] for c in clips)) - t0
    talk = sum(min(c["end"], t1) - c["start"] for c in clips)
    words = sum(len(c["text"].split()) for c in clips)
    edges = sorted((c["start"], c["end"]) for c in clips)
    gaps = [b[0] - a[1] for a, b in zip(edges, edges[1:])] + [edges[0][0] - t0]
    return {"clips": len(clips), "speech_share": round(talk / span, 2) if span > 0 else None,
            "longest_silence_s": round(max(gaps), 1), "words_per_second": round(words / talk, 2) if talk else None,
            "mean_speed": round(sum(c.get("speed", 1) for c in clips) / len(clips), 2),
            "late_over_5s": sum(c.get("shift", 0) > 5 for c in clips)}


# ---------------------------------------------------------------- from the video (Whisper)
def transcribe(video, model_size="small.en"):
    try:
        import av
        import numpy as np
        from faster_whisper import WhisperModel
    except ImportError as e:
        sys.exit(f"--video needs faster-whisper and PyAV (pip install faster-whisper av): {e}")
    chunks = []
    with av.open(video) as c:  # decoded here: some PyAV versions do not take the options faster-whisper passes
        rs = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for fr in c.decode(c.streams.audio[0]):
            for f in rs.resample(fr):
                chunks.append(f.to_ndarray().reshape(-1))
    audio = np.concatenate(chunks).astype(np.float32) / 32768
    model = WhisperModel(model_size, device="auto", compute_type="int8")
    segs, _ = model.transcribe(audio, word_timestamps=True, vad_filter=True, beam_size=1)
    return [{"start": s.start, "end": s.end, "text": s.text.strip(),
             "words": [(w.start, w.end, w.word.strip()) for w in s.words]} for s in segs], len(audio) / 16000


def speech_from_words(segs, length):
    words = [w for s in segs for w in s["words"]]
    if not words:
        return {}
    spans, (a, b) = [], (words[0][0], words[0][1])
    for s, e, _ in words[1:]:
        if s - b <= 0.6:  # a pause inside a sentence
            b = e
        else:
            spans.append((a, b))
            a, b = s, e
    spans.append((a, b))
    talk = sum(e - s for s, e in spans)
    gaps = [s2 - e1 for (_, e1), (s2, _) in zip(spans, spans[1:])] + [spans[0][0]]
    return {"speech_share": round(talk / length, 2), "longest_silence_s": round(max(gaps), 1),
            "words_per_second": round(len(words) / talk, 2)}


def number_of(token):
    t = token.lower().strip(".,!?")
    return int(t) if t.isdigit() else NUMBER_WORDS.get(t)


def fact_check(segs, meta_dir):
    """Shirt numbers said next to a player's name, and capitalised words close to no name of the match."""
    lineups = read_csv(os.path.join(meta_dir, "lineups.csv"))
    info = {r["field"]: r["value"] for r in read_csv(os.path.join(meta_dir, "match_info.csv"))}
    staff = read_csv(os.path.join(meta_dir, "staff.csv"))
    players = [(r["name"], r.get("shirt_number", ""), r.get("team", "")) for r in lineups if r.get("name")]
    other = [r.get(k, "") for f in ("form.csv", "head_to_head.csv", "tournament_path.csv", "teams.csv")
             for r in read_csv(os.path.join(meta_dir, f)) for k in ("opponent", "team", "home", "away", "competition")]
    other += [r.get("name", "") + " " + r.get("club", "") for r in read_csv(os.path.join(meta_dir, "wikipedia",
                                                                                         "squads.csv"))]
    known = set()
    for text in [n for n, _, _ in players] + [r.get("name", "") for r in staff] + list(info.values()) + other:
        known.update(plain(w) for w in re.findall(r"[\w'’-]{3,}", text or ""))
    surname = {}
    for name, num, team in players:
        for w in name.split():
            if len(w) >= 4:
                surname.setdefault(plain(w), set()).add((name, num, team))

    def close(word):
        p = plain(word).strip("'’s")
        return p in known or bool(difflib.get_close_matches(p, known, n=1, cutoff=0.72))

    wrong_numbers, unknown = [], Counter()
    for s in segs:
        for sentence in re.split(r"(?<=[.!?])\s+", s["text"]):
            tokens = sentence.split()
            for i, tok in enumerate(tokens):
                w = re.sub(r"[^\w'’-]", "", tok)
                if w[:1].isupper() and w not in COMMON and not close(w):
                    unknown[w] += 1
            # "number N" with exactly one player of the match in the same sentence (by name, Whisper spelling fuzzy)
            found = set()
            for tok in tokens:
                p = plain(re.sub(r"[^\w'’-]", "", tok))
                hit = surname.get(p) or next((surname[k] for k in difflib.get_close_matches(p, surname, 1, 0.8)), None)
                if hit and len(p) >= 4:
                    found |= hit
            nums = [number_of(tokens[i + 1]) for i, tok in enumerate(tokens[:-1]) if tok.lower().strip(",") == "number"]
            nums = [n for n in nums if n is not None]
            if len(found) == 1 and len(nums) == 1:
                name, num, team = next(iter(found))
                if num.isdigit() and int(num) != nums[0]:
                    wrong_numbers.append(f"{sentence.strip()}  (metadata: {name} = {num})")
    return {"shirt_number_errors": wrong_numbers,
            "unknown_names": [w for w, _ in unknown.most_common(20)]}


# ---------------------------------------------------------------- report
def main(args):
    t0, t1 = clock(args.start) or 0.0, clock(args.end) or 10 ** 6
    card = {"half": args.half, "from": args.start or "00:00", "to": args.end or "end"}
    if args.timeline:
        card["timeline"] = timeline_card(args.timeline, args.half, t0, t1)
    if args.audio_timeline:
        card["audio"] = audio_card(args.audio_timeline, args.half, t0, t1)
    if args.video:
        print(f"transcribing {args.video} (Whisper {args.whisper}) ...", flush=True)
        segs, length = transcribe(args.video, args.whisper)
        card["heard"] = speech_from_words(segs, length)
        if args.metadata:
            card["heard"].update(fact_check(segs, args.metadata))
        card["transcript"] = [f"{int(s['start']) // 60:02d}:{s['start'] % 60:04.1f} {s['text']}" for s in segs]
    tl, au, hd = card.get("timeline", {}), card.get("audio", {}), card.get("heard", {})

    def show(label, value, good=None):
        mark = "" if good is None else ("  ok" if good else "  <- check")
        print(f"  {label:<30} {value}{mark}")

    print(f"\n== Score card: half {args.half}, {card['from']} - {card['to']}")
    share = hd.get("speech_share", au.get("speech_share"))
    if share is not None:
        show("speech share", f"{100 * share:.0f}%", 0.35 <= share <= 0.65)
    silence = hd.get("longest_silence_s", au.get("longest_silence_s"))
    if silence is not None:
        show("longest silence", f"{silence:.0f} s", silence <= 30)
    wps = hd.get("words_per_second", au.get("words_per_second"))
    if wps is not None:
        show("words per second (speaking)", wps, 2.2 <= wps <= 3.4)
    if au:
        show("mean clip speed", f"x{au['mean_speed']}", au["mean_speed"] <= 1.25)
        show("lines heard > 5 s late", au["late_over_5s"])
    if tl:
        show("events", f"{tl['events_source']} ({tl['yes_lines']} lines)")
        if tl["llm_share"] is not None:
            show("LLM share of the no lines", f"{100 * tl['llm_share']:.0f}% ({tl['llm']})",
                 tl["llm"] == "template" or tl["llm_share"] >= 0.6)
        show("facts said / repeated", f"{tl['facts_said']} / {tl['repeated_facts']}", tl["repeated_facts"] == 0)
    if "shirt_number_errors" in hd:
        show("shirt number errors", len(hd["shirt_number_errors"]), not hd["shirt_number_errors"])
        for e in hd["shirt_number_errors"][:5]:
            print(f"      {e}")
        show("words close to no name", ", ".join(hd["unknown_names"][:12]) or "none")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(card, f, indent=2, ensure_ascii=False)
        print(f"  -> {args.out}")
    return card


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = ArgumentParser(description="Score card of a commentary demo (pace, repeats, LLM share, facts)")
    p.add_argument("--timeline", help="commentary_timeline.json of commentary/no_flow_v2.py")
    p.add_argument("--audio_timeline", help="audio_timeline.json of voice/tts_v2.py")
    p.add_argument("--video", help="demo mp4 (or wav) to transcribe with Whisper (optional)")
    p.add_argument("--metadata", help="metadata folder of the match (names, shirt numbers) for the transcript check")
    p.add_argument("--half", type=int, default=1)
    p.add_argument("--start", default=None, help="MM:SS in the half (the demo part)")
    p.add_argument("--end", default=None, help="MM:SS")
    p.add_argument("--whisper", default="small.en", help="faster-whisper model")
    p.add_argument("--out", default=None, help="write the score card (and the transcript) to this json")
    a = p.parse_args()
    if not (a.timeline or a.audio_timeline or a.video):
        p.error("give --timeline, --audio_timeline and/or --video")
    main(a)
