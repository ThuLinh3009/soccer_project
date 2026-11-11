"""No flow at test time: an LLM (ElevenLabs Agents, text-only) says background lines in the gaps between events.

Nothing is trained here (no labels). For each free slot between two event comments (same slot rules as
commentary_timeline.py), the fact to say is chosen from facts.csv (fifa_crawl.py), then the LLM rewrites it as one
spoken commentator line, using only the facts it is given (minute, score, fact, last event, lines already said).

Event comments (yes flow) come from:
    --yes_events <file>   the trained model on this match: results_dense_captioning.json (main.py)
                          or commentary_timeline.json (commentary_timeline.py --events_only)
    --events_from_fifa    stand-in until the yes model is ready: the FIFA events of events.csv
                          (used only for the gap times; marked "fifa" in the output)

LLM (--llm):
    elevenlabs  an ElevenLabs agent in text-only chat mode (created once, id cached in metadata/elevenlabs_agent.json).
                Needs the ELEVENLABS_API_KEY environment variable (never written to a file by this script).
    template    no LLM: the fact sentence as written in facts.csv (offline test)

usage:
    set ELEVENLABS_API_KEY=...        (PowerShell: $env:ELEVENLABS_API_KEY="...")
    python no_flow_llm.py --metadata "../video_test/metadata/2026-07-05 - Brazil 1 - 2 Norway" \
        --video_dir "../video_test/fifa_world-cup/2026/2026-07-05 - Brazil 1 - 2 Norway" --events_from_fifa
"""
import csv
import json
import os
import re
import time
import urllib.error
import urllib.request
from argparse import ArgumentParser

from commentary_timeline import add_slot_args, format_game_time, parse_game_time, schedule_background
from match_facts import Fact

API = "https://api.elevenlabs.io"
WSS = "wss://api.elevenlabs.io/v1/convai/conversation"
AGENT_CACHE = os.path.join("metadata", "elevenlabs_agent.json")
# FIFA event types that count as an on-pitch event (a yes-flow comment would be there)
FIFA_EVENT_TYPES = {"Goal!", "Penalty Goal", "Own goal", "Yellow card", "Red card", "Second yellow card", "Substitution",
                    "Corner", "Attempt at Goal", "Attempt Missed", "Foul", "Offside", "Penalty Awarded", "VAR",
                    "Penalty Missed"}

SYSTEM_PROMPT = """You are a live TV football commentator. The pictures are commented by someone else; your job is to \
fill the quiet moments of the match with background information.

Each message gives you the match minute, the score, the fact to say, the last thing that happened on the pitch and \
the lines you already said. Answer with the line to be spoken, nothing else.

Rules:
- {language}, one or two short sentences, at most 35 words, natural spoken commentary.
- Use only the information in the message. Never invent names, numbers, statistics, records or on-pitch actions.
- Add no details or opinions that are not in the fact: no ages ("young"), no "strong", "crucial", "important", \
no time of day, no weather.
- A long list (line-up, bench): say only the most useful part, never more than 35 words.
- You cannot see the pitch: do not describe what is happening now (no passes, shots, saves, chances).
- Do not repeat the wording of the lines already said; vary how you start the sentence.
- No quotes, no emojis, no markdown, no stage directions."""


# ---------------------------------------------------------------- inputs

def read_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_facts(metadata_dir):
    facts = []
    for r in read_csv(os.path.join(metadata_dir, "facts.csv")):
        until = (int(r["valid_until_half"]), int(r["valid_until_second"])) if r["valid_until_half"] else None
        facts.append(Fact(r["topic"], r["text"], int(r["priority"]),
                          valid_from=(int(r["valid_from_half"]), int(r["valid_from_second"])), valid_until=until,
                          repeat_every=int(r["repeat_every"]) if r["repeat_every"] else None,
                          repeat_text=r["repeat_text"] or None, live=r["live"] == "True"))
    return facts


def load_match_info(metadata_dir):
    return {r["field"]: r["value"] for r in read_csv(os.path.join(metadata_dir, "match_info.csv"))}


def load_fifa_events(metadata_dir):
    return [r for r in read_csv(os.path.join(metadata_dir, "events.csv")) if r["half"] in ("1", "2")]


def events_from_fifa(fifa_events):
    seen, events = set(), []
    for r in fifa_events:
        if r["type_name"] not in FIFA_EVENT_TYPES:
            continue
        key = (int(r["half"]), int(r["second"]))
        if key in seen:  # several FIFA rows in the same minute = one comment
            continue
        seen.add(key)
        events.append((key, r["description"] or f"{r['type_name']} ({r['team']})", r["type_name"], None))
    return sorted(events, key=lambda e: e[0])


def events_from_yes(path):
    data = json.load(open(path, encoding="utf-8"))
    if "predictions" in data:  # results_dense_captioning.json
        items = [(parse_game_time(p["gameTime"]), p.get("comment", ""), p.get("label", ""), p.get("confidence"))
                 for p in data["predictions"]]
    else:  # commentary_timeline.json
        items = [((c["half"], c["second"]), c["text"], c.get("topic", ""), c.get("confidence"))
                 for c in data["comments"] if c.get("flow") == "yes"]
    return sorted((e for e in items if e[0][0] in (1, 2)), key=lambda e: e[0])


def half_lengths(video_dir, events):
    lens = []
    for half in (1, 2):
        path = os.path.join(video_dir, f"{half}_224p.mp4") if video_dir else None
        if path and os.path.exists(path):
            import av
            with av.open(path) as c:
                lens.append(int(c.duration / av.time_base))
        else:  # no video: up to the last event of the half + 1 min
            lens.append(max([s for (h, s), *_ in events if h == half] + [45 * 60]) + 60)
    return lens


def score_at(fifa_events, half, second):
    home = away = 0
    for r in fifa_events:
        if (int(r["half"]), int(r["second"])) > (half, second):
            break
        if r["home_goals"] != "":
            home, away = int(r["home_goals"]), int(r["away_goals"])
    return home, away


def match_minute(half, second):
    minute = max(1, second // 60)  # FIFA style: 34:00 into the 2nd half = 79'
    if half == 1:
        return f"{minute}'" if minute <= 45 else f"45'+{minute - 45}'"
    minute += 45
    return f"{minute}'" if minute <= 90 else f"90'+{minute - 90}'"


# ---------------------------------------------------------------- prompt

def build_message(info, half, second, score, fact_text, last_event, said):
    lines = [f"Match: {info.get('home_team')} v {info.get('away_team')}, {info.get('competition')}"
             f"{', ' + info['stage'] if info.get('stage') else ''}.",
             f"Minute: {match_minute(half, second)} ({'first' if half == 1 else 'second'} half).",
             f"Score: {info.get('home_team')} {score[0]}, {info.get('away_team')} {score[1]}."]
    if last_event:
        ago = (second - last_event[0]) // 60 if last_event[0] <= second else 0
        lines.append(f"Last thing on the pitch ({'just now' if ago == 0 else f'{ago} min ago'}): {last_event[1]}")
    lines.append(f"Fact to say: {fact_text}")
    if said:
        lines.append("Already said (do not repeat): " + " | ".join(said))
    lines.append("Your line:")
    return "\n".join(lines)


def numbers_ok(answer, message):
    """Every number in the answer must come from the message (a cheap guard against invented stats)."""
    allowed = set(re.findall(r"\d+", message.replace(",", "")))
    return all(n in allowed for n in re.findall(r"\d+", answer.replace(",", "")))


# the LLM cannot know the time of day: drop it even when it ignores the rule
TIME_OF_DAY = re.compile(r",?\s+(?:this|on this)\s+(?:afternoon|evening|morning)|,?\s+tonight", re.I)


def clean(answer):
    answer = TIME_OF_DAY.sub("", answer.strip().strip('"').strip())
    return re.sub(r"\s+", " ", answer).replace(" .", ".")


# ---------------------------------------------------------------- ElevenLabs

class ElevenLabsLLM:
    """Text-only conversation with an ElevenLabs agent; the agent's LLM writes the lines."""

    def __init__(self, api_key, llm, system_prompt, temperature, agent_id=None, agent_cache=AGENT_CACHE):
        self.key, self.llm, self.prompt, self.temperature = api_key, llm, system_prompt, temperature
        self.cache = agent_cache
        self.agent_id = agent_id or self._agent()
        self.ws = None

    def _http(self, method, path, body=None):
        req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body else None,
                                     headers={"xi-api-key": self.key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            raise SystemExit(f"ElevenLabs {method} {path}: HTTP {e.code} {e.read().decode(errors='replace')[:500]}")

    def _config(self):
        return {"name": "AI football commentator - no flow",
                "conversation_config": {
                    "agent": {"first_message": "", "language": "en",
                              "prompt": {"prompt": self.prompt, "llm": self.llm, "temperature": self.temperature}},
                    "conversation": {"text_only": True}}}

    def _agent(self):
        """Reuse the cached agent (its prompt/LLM updated to this run's), or create one."""
        cached = json.load(open(self.cache)) if os.path.exists(self.cache) else {}
        if cached.get("agent_id"):
            self._http("PATCH", f"/v1/convai/agents/{cached['agent_id']}", self._config())
            return cached["agent_id"]
        agent_id = self._http("POST", "/v1/convai/agents/create", self._config())["agent_id"]
        os.makedirs(os.path.dirname(os.path.abspath(self.cache)), exist_ok=True)
        json.dump({"agent_id": agent_id}, open(self.cache, "w"))
        print(f"created ElevenLabs agent {agent_id} (cached in {self.cache})")
        return agent_id

    def _connect(self):
        from websockets.sync.client import connect
        url = self._http("GET", f"/v1/convai/conversation/get-signed-url?agent_id={self.agent_id}")["signed_url"]
        self.ws = connect(url, open_timeout=30, max_size=2 ** 22).__enter__()
        self.ws.send(json.dumps({"type": "conversation_initiation_client_data",
                                 "conversation_config_override": {"conversation": {"text_only": True}}}))

    def new_conversation(self):
        self.close()
        self._connect()

    def ask(self, message, timeout=90, retries=2):
        for attempt in range(retries + 1):
            try:
                if self.ws is None:
                    self._connect()
                self.ws.send(json.dumps({"type": "user_message", "text": message}))
                # the agent streams the reply (agent_chat_response_part) AND sends it whole (agent_response):
                # wait for the whole one, else the next question would read this reply
                deadline, parts = time.time() + timeout, []
                while time.time() < deadline:
                    try:
                        ev = json.loads(self.ws.recv(timeout=max(0.01, deadline - time.time())))
                    except TimeoutError:
                        break
                    kind = ev.get("type")
                    if kind == "ping":
                        self.ws.send(json.dumps({"type": "pong", "event_id": ev["ping_event"]["event_id"]}))
                    elif kind == "agent_response":
                        return ev["agent_response_event"]["agent_response"]
                    elif kind == "agent_chat_response_part":
                        part = ev["text_response_part"]
                        if part.get("type") == "delta":
                            parts.append(part.get("text", ""))
                        elif part.get("type") == "stop":
                            deadline = min(deadline, time.time() + 5)  # agent_response should follow at once
                if parts:
                    return "".join(parts)
                raise TimeoutError("no agent_response")
            except Exception as e:  # closed / timed out conversation: open a new one and retry
                print(f"  LLM retry {attempt + 1}: {type(e).__name__}: {e}")
                self.close()
                time.sleep(2)
        return None

    def close(self):
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass
        self.ws = None


# ---------------------------------------------------------------- main

def main(args):
    meta = args.metadata
    info, facts, fifa_events = load_match_info(meta), load_facts(meta), load_fifa_events(meta)
    if args.yes_events:
        events, source = events_from_yes(args.yes_events), "yes"
    else:
        events, source = events_from_fifa(fifa_events), "fifa"
    half_lens = half_lengths(args.video_dir, events)
    slots = schedule_background(events, facts, half_lens, args)
    game = os.path.basename(os.path.normpath(meta))
    print(f"{game}: {len(events)} events ({source}), halves {half_lens[0] // 60}/{half_lens[1] // 60} min, "
          f"{len(slots)} background slots, LLM {args.llm}")

    llm = None
    if args.llm == "elevenlabs":
        key = os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            raise SystemExit("set the ELEVENLABS_API_KEY environment variable first")
        language = "English" if args.language == "en" else f"Language: {args.language}"
        llm = ElevenLabsLLM(key, args.llm_model, SYSTEM_PROMPT.format(language=language), args.temperature,
                            args.agent_id, args.agent_cache)
        print(f"agent {llm.agent_id}, model {args.llm_model}")

    timeline = [{"half": h, "second": s, "gameTime": format_game_time(h, s), "flow": "yes", "source": source,
                 "topic": label or "comment", "text": text, "confidence": conf} for (h, s), text, label, conf in events]
    said, current_half, n_fallback = [], None, 0
    for i, (half, t, fact, fact_text) in enumerate(slots):
        if llm and half != current_half:
            llm.new_conversation()  # one conversation per half keeps the history short
        current_half = half
        before = [e for e in events if e[0] <= (half, t)]
        last_event = (before[-1][0][1], before[-1][1]) if before and before[-1][0][0] == half else None
        message = build_message(info, half, t, score_at(fifa_events, half, t), fact_text, last_event,
                                said[-args.history:])
        text, used = fact_text, "template"
        if llm:
            answer = llm.ask(message)
            if answer and numbers_ok(clean(answer), message) and len(clean(answer).split()) <= 45:
                text, used = clean(answer), "llm"
            else:
                n_fallback += 1
                print(f"  slot {format_game_time(half, t)}: LLM answer rejected or missing -> fact sentence")
        said.append(text)
        timeline.append({"half": half, "second": t, "gameTime": format_game_time(half, t), "flow": "no",
                         "source": used, "topic": fact.topic, "fact": fact_text, "text": text, "confidence": None})
        print(f"[{i + 1}/{len(slots)}] {format_game_time(half, t)} ({fact.topic}) {text}")
    if llm:
        llm.close()

    timeline.sort(key=lambda c: (c["half"], c["second"], c["flow"] == "no"))
    out_dir = os.path.join(args.out_dir, game)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "commentary_timeline.json"), "w", encoding="utf-8") as f:
        json.dump({"game": game, "events_source": source, "llm": args.llm,
                   "llm_model": args.llm_model if llm else None, "comments": timeline}, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, "commentary_timeline.txt"), "w", encoding="utf-8") as f:
        for c in timeline:
            tag = ("EVENT" if c["source"] == "yes" else "FIFA ") if c["flow"] == "yes" else "INFO "
            f.write(f"{c['gameTime']}  [{tag}] ({c['topic']}) {c['text']}\n")
    print(f"{sum(c['flow'] == 'no' for c in timeline)} background lines ({n_fallback} fell back to the fact sentence)"
          f" -> {os.path.join(out_dir, 'commentary_timeline.txt')}")


if __name__ == "__main__":
    p = ArgumentParser(description="No flow: LLM background commentary in the gaps between events")
    p.add_argument("--metadata", required=True, help="fifa_crawl.py output folder of the match (facts.csv, ...)")
    p.add_argument("--video_dir", default=None, help="folder with 1_224p.mp4 / 2_224p.mp4 (for the half lengths)")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--yes_events", help="results_dense_captioning.json or commentary_timeline.json of the yes flow")
    src.add_argument("--events_from_fifa", action="store_true", help="stand-in: FIFA events.csv as the events")
    p.add_argument("--llm", choices=["elevenlabs", "template"], default="elevenlabs")
    p.add_argument("--llm_model", default="gemini-2.5-flash", help="LLM of the ElevenLabs agent")
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--agent_id", default=None, help="use this existing agent instead of the cached/created one")
    p.add_argument("--agent_cache", default=AGENT_CACHE, help="json file keeping the id of the created agent")
    p.add_argument("--language", default="en", help="language of the lines (en = English)")
    p.add_argument("--history", type=int, default=4, help="how many previous lines are shown to avoid repeats")
    p.add_argument("--out_dir", default=os.path.join("outputs", "no_flow"))
    add_slot_args(p)
    main(p.parse_args())
