"""No flow v2: commentary script 2.0 (NO_FLOW_SCRIPT.md) + Gemini.

New version next to commentary/no_flow_llm.py (v1, ElevenLabs, kept unchanged). Differences:
- the lines follow the script: mandatory lines (welcome, teams, stakes, live news, score updates, half-time,
  second half, 80', stoppage time, full-time) + optional background in long gaps (commentary/script_v2.py);
- every line is first a filled template (works for any match); the LLM only says it in its own words;
- LLM: Google Gemini (default gemini-2.5-flash-lite, then gemini-3.1-flash-lite / gemini-3.5-flash-lite when its
  quota is used up: the free tier of gemini-2.5-flash-lite allows only 20 requests a day), key in the
  GEMINI_API_KEY environment variable (Colab: Secrets). --llm template = no LLM, the templates as they are;
- answers are checked (numbers, names, length, banned words) and replaced by the template when they fail;
- yes comments are written without [PLAYER]/[TEAM] ("the player", "the team"), ready for text-to-speech;
- (v5.1) every line gets a time slot: the seconds until the next line of the timeline (yes or no). The slot gives
  the most words that can be spoken in it (--wps words per second); the LLM is told "TIME: x s, at most n words",
  an answer longer than that is asked again shorter (--retries), then replaced by the template. The slot is written
  to the timeline; voice/tts_v2.py measures the real clip and speeds it up a little when it is still too long.
- (v5.5) --continuous: the commentary never stops. After the script, every silence between two lines (yes or no)
  longer than 3 s is filled with FILL lines from the metadata, sized to the silence: players and shirt numbers,
  units (defence / midfield / attack), captains, coaches, formations, bench, form, head to head, venue, the score
  and the clock, and a recap of the goals, cards and changes so far. Topics take turns; nothing is repeated within
  15 minutes until everything has been said. FILL lines are templates (no LLM call: hundreds of lines a match, far
  above the free quota) unless --fill_llm.
- (v5.9) --llm openai: an OpenAI chat model (--openai_model gpt-4o-mini, key in OPENAI_API_KEY) writes the lines,
  then voice/tts_v2.py --engine openai (gpt-4o-mini-tts) reads them. --llm_half / --llm_start / --llm_end: the LLM only for
  the demo part (the other lines stay templates): a continuous match has 1000+ lines.

Output (<out_dir>/<game>/): commentary_timeline.json / .txt (yes + no lines), input of voice/tts_v2.py.

usage:
    python -m commentary.no_flow_v2 --metadata "../video_test/metadata/<game>" --video_dir "../video_test/<...>/<game>" \
        --yes_events "outputs/yes/<game>/results_dense_captioning.json" --llm gemini
"""
import json
import os
import re
from argparse import ArgumentParser

from commentary.commentary_timeline import format_game_time
from commentary.no_flow_llm import events_from_fifa, events_from_yes, half_lengths, load_fifa_events, numbers_ok
from commentary import script_v2
from commentary.script_v2 import (MatchContext, build_schedule, fill_continuous, max_words, neutral_caption, speech_len,
                       time_slots, word_count)

SYSTEM_PROMPT = """You are the lead TV commentator of a live football broadcast. A second voice describes the action on \
the pitch. Your job is to say the key lines of the broadcast (welcome, half-time, second half, late game, full-time) \
and to fill the quiet moments with the information you are given.

Each message gives you: PHASE, GENDER, MATCH, MINUTE, SCORE, TIME (how long you can speak before the next line, \
and the most words that fit), FACT (what to say), LAST EVENT (what just happened on the pitch), ALREADY SAID (your \
recent lines), and sometimes SCORERS. Say the FACT as a live commentator would. \
Answer with the line to be spoken, nothing else.

Language: {language}. Spoken, natural, live broadcast style.

Hard rules:
1. Use only the information in the message. Never invent names, numbers, statistics, records, injuries, quotes, \
weather, time of day, crowd reactions or actions on the pitch.
2. The SCORE in the message is always right. Never say any other score.
3. Say a minute only if it is in the FACT, and exactly as written there.
4. You cannot see the pitch. Never describe passes, shots, saves, chances or pressure unless they are in the FACT \
or the LAST EVENT.
5. Length: one or two sentences, at most 30 words (PHASE welcome and full_time: at most 45 words), and NEVER more \
words than TIME allows: the next line starts right after yours. When TIME is short, keep the names and the score \
and drop the rest.
6. Keep every name, team, number, date and score of the FACT. Change only the wording, and do not repeat the wording \
of ALREADY SAID. Never call a past match the last or previous meeting unless the FACT says so.
7. Emotion is allowed: excitement for a goal, tension when time is running out. Opinions are not: never judge \
players, tactics, the referee or who deserves to win.
8. GENDER women: players are she/her. GENDER men: he/him.
9. No quotes, emojis, markdown, hashtags, stage directions or speaker names.
10. Say only what the FACT is about. Some moments are split into several lines said one after the other \
(score, scorers, invitation, result, goodbye): never add the content of another line, e.g. no goodbye and no \
invitation unless the FACT says it.

Phase rules:
- welcome: greet the viewers ("Hello and welcome"), name the stadium, the city, the competition, the round or \
matchday and both teams. Never say good morning, afternoon or evening.
- teams: introduce both teams and their head coaches, home team first.
- stakes: say what is at stake, only from the FACT.
- live_news: a goal, card, substitution, penalty or VAR decision just happened. Say it right away. Goal: excited, \
with the scorer and the new SCORE. Cards and substitutions: neutral and short.
- score_update: remind the score in a fresh way, short.
- background: one piece of background from the FACT, calm tone.
- half_time: one part of the half-time moment, the one in the FACT: the whistle and the score, or the scorers, or \
the invitation to stay for the second half.
- second_half: the second half is under way. Remind the SCORE.
- late_game: about ten minutes left, or stoppage time has begun. Build tension with the SCORE.
- extra_time: the match goes to extra time. Give the SCORE.
- full_time: one part of the full-time moment, the one in the FACT: the final whistle and the score, or the \
scorers, or what the result means, or the goodbye."""

BANNED = re.compile(r"\b(morning|afternoon|evening|tonight|weather|sunny|rain\w*|young|veteran|deserv\w*|"
                    r"brilliant|terrible|poor|amazing|incredible|legend\w*|crucial|fantastic|excellent|"
                    r"superb|impressive|dominant|disappointing|key|vital|star|strong|talented|influential|"
                    r"boasts?)\b", re.I)
LAST_MEETING = re.compile(r"\b(last|previous|latest|most recent) (encounter|meeting|time they met|clash)", re.I)
SPLIT_CODES = {"A1", "A2", "A3", "C1", "C1b", "C2", "G1", "G2", "G3", "G4"}
CAPITAL_OK = {"I", "VAR", "Goal", "Penalty", "Full-time", "Half-time"}
LONG_PHASES = {"welcome", "full_time"}
MIN_BUDGET = 6  # a slot shorter than this many words: the answer may still have 6 words (voice/tts_v2.py speeds it up)


def clock(value):
    """'28:00' or '1680' -> seconds in the half; None / '' stays None."""
    if value in (None, ""):
        return None
    parts = [float(x) for x in str(value).split(":")]
    return parts[0] if len(parts) == 1 else parts[0] * 60 + parts[1]


def build_message(ctx, line, last_event, said, gender, budget=None):
    v = line.vars
    match = f"{ctx.home} v {ctx.away}, {v['competition']}"
    match += f", {v['round_phrase']}" if v.get("round_phrase") else ""
    match += f", {v['stadium']}" if v.get("stadium") else ""
    match += f", {v['city']}" if v.get("city") else ""
    rows = [f"PHASE: {line.phase}", f"GENDER: {gender}", f"MATCH: {match}", f"MINUTE: {v['minute']}",
            f"SCORE: {v['score']}"]
    if line.phase in ("half_time", "full_time") and v.get("scorers"):
        rows.append(f"SCORERS: {v['scorers']}")
    if budget is not None:
        rows.append(f"TIME: {line.slot:.1f} seconds, at most {budget} words")
    if line.code in SPLIT_CODES:
        rows.append("NOTE: this moment is said in several lines; say only this FACT, nothing of the other lines.")
    rows += [f"FACT: {line.text}", f"LAST EVENT: {last_event or 'none'}",
             f"ALREADY SAID: {' | '.join(said) if said else 'none'}", "YOUR LINE:"]
    return "\n".join(rows)


def clean_answer(text):
    text = re.sub(r"^\s*(YOUR LINE:|Commentator:)\s*", "", text.strip(), flags=re.I)
    text = text.strip().strip('"').strip("*").strip()
    return re.sub(r"\s+", " ", text)


def check(answer, message, fact, phase, budget=None):
    """Reason the answer is rejected, or None if it can be used."""
    if not answer:
        return "empty"
    words = len(answer.split())
    limit = max(45 if phase in LONG_PHASES else 30, len(fact.split()) + 8)
    if budget is not None:
        limit = min(limit, max(budget, MIN_BUDGET))
    if words > limit:
        return f"too long ({words} words)"
    if not numbers_ok(answer, message):
        return "number not in the message"
    if BANNED.search(answer):
        return f"banned word '{BANNED.search(answer).group(0)}'"
    if LAST_MEETING.search(answer) and not LAST_MEETING.search(fact) and "last met" not in fact.lower():
        return f"banned word '{LAST_MEETING.search(answer).group(0)}'"
    known = message.lower()
    for sentence in re.split(r"(?<=[.!?])\s+", answer):
        for w in re.findall(r"[A-ZÀ-Ý][\w'’-]+", sentence)[1:]:  # capitalised words after the first one
            if w not in CAPITAL_OK and w.lower().strip("'’s") not in known and w.lower() not in known:
                return f"unknown name '{w}'"
    if any(ch in answer for ch in "*#“”"):
        return "markdown or quotes"
    return None


def main(args):
    meta = args.metadata
    ctx = MatchContext(meta)
    game = os.path.basename(os.path.normpath(meta))
    if args.yes_events:
        events, source = events_from_yes(args.yes_events), "yes"
    else:
        events, source = events_from_fifa(load_fifa_events(meta)), "fifa"
    half_lens = half_lengths(args.video_dir, events)
    yes = [(h, s, neutral_caption(text) if source == "yes" else text) for (h, s), text, _, _ in events]
    script_v2.WORDS_PER_SECOND = args.wps  # used by the schedule (speech_len) and the word budgets
    lines, muted = build_schedule(ctx, yes, half_lens, seed=args.seed)
    n_fill = 0
    if args.continuous:
        fills = fill_continuous(ctx, lines, yes, muted, half_lens, pause=args.fill_pause, seed=args.seed)
        n_fill = len(fills)
        lines = sorted(lines + fills, key=lambda l: (l.half, l.second))
    slots = time_slots([(h, s) for h, s, _ in yes if (h, s) not in muted] + [(l.half, l.second) for l in lines],
                       half_lens, gap=args.gap)
    for line in lines:
        line.slot = slots[(line.half, line.second)]
    n_mand = sum(l.mandatory for l in lines)
    print(f"{game}: {ctx.kind} match, {ctx.gender} | {len(events)} events ({source}), "
          f"halves {half_lens[0] // 60}/{half_lens[1] // 60} min | {len(lines)} no-flow lines "
          f"({n_mand} mandatory, {len(lines) - n_mand - n_fill} optional, {n_fill} continuous fill), "
          f"{len(muted)} yes comments muted | LLM {args.llm}{' (FILL lines: templates)' if n_fill and not args.fill_llm else ''}")

    llm = None
    if args.llm == "gemini":
        from clients.gemini_client import Gemini, ModelPool, read_key
        rpm = 12 if args.rpm is None else args.rpm
        llm = Gemini(read_key(), args.backend, min_interval=60.0 / rpm if rpm else 0)
        pool = ModelPool(args.llm_model)
        system = SYSTEM_PROMPT.format(language=args.language)
        print(f"Gemini backend {llm.backend}, models (in order) {', '.join(pool.models)}")
    elif args.llm == "openai":  # (v5.9) gpt-4o-mini writes the lines; voice/tts_v2.py --engine openai reads them
        from clients.gemini_client import ModelPool, read_key
        from clients.openai_client import OpenAIChat
        rpm = 300 if args.rpm is None else args.rpm
        llm = OpenAIChat(read_key("OPENAI_API_KEY"), min_interval=60.0 / rpm if rpm else 0)
        pool = ModelPool(args.openai_model)
        system = SYSTEM_PROMPT.format(language=args.language)
        print(f"OpenAI LLM {', '.join(pool.models)}")
    t0, t1 = clock(args.llm_start), clock(args.llm_end)

    def llm_here(line):  # --llm_half / --llm_start / --llm_end: the LLM only for the demo part (the rest: templates)
        if args.llm_half and line.half != args.llm_half:
            return False
        return (t0 is None or line.second >= t0) and (t1 is None or line.second < t1)

    def budget_of(slot, phase):  # words that fit in the slot, at most the length rule (30, welcome / full_time 45)
        return min(max_words(slot), 45 if phase in LONG_PHASES else 30)

    def timing(text, slot, phase="event"):
        return {"slot": round(slot, 2), "words": word_count(text), "max_words": budget_of(slot, phase),
                "est_seconds": round(speech_len(text), 2), "over": speech_len(text) > slot + 0.05}

    timeline = [{"half": h, "second": s, "gameTime": format_game_time(h, int(s)), "flow": "yes", "source": source,
                 "phase": "event", "code": "", "text": text, "text_raw": raw, "muted": (h, s) in muted,
                 **timing(text, slots.get((h, s), 0.0))}
                for (h, s, text), ((_, _), raw, _, _) in zip(yes, events)]
    said, n_llm, rejected, n_retry = [], 0, {}, 0
    for i, line in enumerate(lines):
        before = [t for h, s, t in yes if h == line.half and s <= line.second and (h, s) not in muted]
        budget = budget_of(line.slot, line.phase)
        message = build_message(ctx, line, before[-1] if before else None, said[-args.history:], ctx.gender, budget)
        text, used = line.text, "template"
        if llm and pool.current and (line.code != "FILL" or args.fill_llm) and llm_here(line):
            ask = message
            for attempt in range(1 + args.retries):
                model = None
                try:
                    answer = clean_answer(pool.call(lambda m: llm.text(m, system, ask, args.temperature)))
                    model = pool.current
                except Exception as e:  # network / no quota left: keep the template line
                    answer = ""
                    print(f"  LLM error: {str(e)[:160]}")
                reason = check(answer, message, line.text, line.phase, budget) if model else "no answer"
                if not reason or not reason.startswith("too long") or attempt == args.retries:
                    break
                n_retry += 1  # too long for the slot: ask again, shorter
                ask = message.rsplit("YOUR LINE:", 1)[0] + (
                    f"TOO LONG: your answer \"{answer}\" has {word_count(answer)} words. Say it again in at most "
                    f"{max(budget, MIN_BUDGET)} words.\nYOUR LINE:")
            if reason:
                rejected[reason.split(" '")[0].split(" (")[0]] = rejected.get(reason.split(" '")[0].split(" (")[0], 0) + 1
                if model:
                    print(f"  {format_game_time(line.half, int(line.second))} {line.code}: rejected ({reason}): "
                          f"{answer}")
            else:
                text, used = answer, model
                n_llm += 1
        said.append(text)
        t = timing(text, line.slot, line.phase)
        timeline.append({"half": line.half, "second": line.second, "gameTime": format_game_time(line.half,
                         int(line.second)), "flow": "no", "source": used, "phase": line.phase, "code": line.code,
                         "topic": line.topic, "mandatory": line.mandatory, "after": line.after, "fact": line.text,
                         "text": text, **t})
        print(f"[{i + 1}/{len(lines)}] {format_game_time(line.half, int(line.second))} {line.code:<12} "
              f"{t['words']:>2}/{t['max_words']:<2} words {t['est_seconds']:>4.1f}/{t['slot']:<5.1f}s "
              f"{'OVER ' if t['over'] else ''}{text}")

    timeline.sort(key=lambda c: (c["half"], c["second"], c["flow"] == "no"))
    out_dir = os.path.join(args.out_dir, game)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "commentary_timeline.json"), "w", encoding="utf-8") as f:
        json.dump({"game": game, "script": "2.0", "events_source": source, "llm": args.llm,
                   "llm_model": (args.openai_model if args.llm == "openai" else args.llm_model) if llm else None, "half_lengths": half_lens, "gender": ctx.gender,
                   "wps": args.wps, "gap": args.gap, "comments": timeline}, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, "commentary_timeline.txt"), "w", encoding="utf-8") as f:
        for c in timeline:
            if c["flow"] == "yes":
                tag = "MUTED" if c["muted"] else "EVENT" if c["source"] == "yes" else "FIFA "
            else:
                tag = c["code"]
            time = "" if c.get("muted") else (f"  ({c['words']}/{c['max_words']} words, {c['est_seconds']:.1f}/"
                                                f"{c['slot']:.1f}s{' OVER' if c['over'] else ''})")
            f.write(f"{c['gameTime']}  [{tag:<5}] {c['text']}{time}\n")
    over = [c for c in timeline if not c.get("muted") and c["over"]]
    for half in sorted({c["half"] for c in timeline}):  # how continuous the commentary is (estimated speech)
        spoken = sorted((c["second"], c["est_seconds"]) for c in timeline if c["half"] == half and not c.get("muted"))
        talk = sum(d for _, d in spoken)
        gaps = [b[0] - (a[0] + a[1]) for a, b in zip(spoken, spoken[1:])]
        long_gaps = [g for g in gaps if g > 3]
        print(f"half {half}: {len(spoken)} lines, about {talk / 60:.1f} min of speech in {half_lens[half - 1] / 60:.1f} "
              f"min ({100 * talk / half_lens[half - 1]:.0f}%), longest silence {max(gaps + [0]):.1f} s, "
              f"{len(long_gaps)} silences over 3 s")
    print(f"{len(lines)} no-flow lines: {n_llm} by the LLM, {len(lines) - n_llm} templates"
          f"{' (rejected: ' + ', '.join(f'{k} {v}' for k, v in rejected.items()) + ')' if rejected else ''}"
          f", {n_retry} asked again shorter | speech {args.wps} words/s: {len(over)} lines (yes "
          f"{sum(c['flow'] == 'yes' for c in over)}, no {sum(c['flow'] == 'no' for c in over)}) longer than their "
          f"slot (voice/tts_v2.py speeds them up) -> {os.path.join(out_dir, 'commentary_timeline.txt')}")


if __name__ == "__main__":
    p = ArgumentParser(description="No flow v2: commentary script 2.0 + Gemini")
    p.add_argument("--metadata", required=True, help="crawler/fifa_crawl.py output folder of the match")
    p.add_argument("--video_dir", default=None, help="folder with 1_224p.mp4 / 2_224p.mp4 (half lengths)")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--yes_events", help="results_dense_captioning.json of the yes flow (deltalab/infer_match.py)")
    src.add_argument("--events_from_fifa", action="store_true", help="stand-in: FIFA events.csv as the events")
    p.add_argument("--llm", choices=["gemini", "openai", "template"], default="gemini",
                   help="gemini | openai (v5.9: OpenAI chat model, key in OPENAI_API_KEY) | template (no LLM)")
    p.add_argument("--openai_model", default="gpt-4o-mini", help="--llm openai: chat model that writes the lines")
    p.add_argument("--llm_half", type=int, default=0, help="the LLM only for lines of this half (0 = both)")
    p.add_argument("--llm_start", default=None, help="the LLM only from this time of the half (MM:SS), e.g. the "
                                                   "demo part; the other lines stay templates (saves time and cost)")
    p.add_argument("--llm_end", default=None, help="... to this time (MM:SS)")
    p.add_argument("--llm_model", default="gemini-2.5-flash-lite,gemini-3.1-flash-lite,gemini-3.5-flash-lite",
                   help="models tried in order: the next one is used when a model has no quota left")
    p.add_argument("--backend", choices=["auto", "gemini", "vertex"], default="auto")
    p.add_argument("--rpm", type=float, default=None,
                   help="max LLM requests per minute (default: gemini 12 for the free tier, openai 300)")
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--language", default="English")
    p.add_argument("--history", type=int, default=3, help="previous lines shown to the LLM to avoid repeats")
    p.add_argument("--seed", type=int, default=0, help="choice between template variants")
    p.add_argument("--wps", type=float, default=2.6,
                   help="spoken words per second of the TTS voice (English 2.6; Vietnamese about 4.5 syllables). "
                        "voice/tts_v2.py prints the rate measured on the real clips")
    p.add_argument("--gap", type=float, default=0.3, help="seconds of silence kept before the next line")
    p.add_argument("--retries", type=int, default=1,
                   help="times the LLM is asked again, shorter, when its answer does not fit the time slot")
    p.add_argument("--continuous", action="store_true",
                   help="fill every silence with no-flow lines from the metadata: the commentary never stops (v5.5)")
    p.add_argument("--fill_llm", action="store_true",
                   help="--continuous: the FILL lines also go through the LLM (many requests: needs a paid quota)")
    p.add_argument("--fill_pause", type=float, default=0.7, help="--continuous: seconds between two lines")
    p.add_argument("--out_dir", default=os.path.join("outputs", "no_flow_v2"))
    main(p.parse_args())
