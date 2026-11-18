"""(v6.2) Listen before choosing: one short wav per OpenAI voice, each reading the same 3 lines of a match:
an event (yes style), a goal (goal style) and a presenter line (no style), with the --openai_style of voice/tts_v2.py.

Key: OPENAI_API_KEY environment variable (Colab: Secrets). About 3 short requests per voice.

usage:
    python -m voice.voice_samples --out_dir outputs/voice_samples --style epic
    python -m voice.voice_samples --voices ash,verse,onyx --style calm
"""
import os
from argparse import ArgumentParser, Namespace

import numpy as np

from voice import tts_v2
from api.gemini_client import save_wav

VOICES = "alloy,ash,ballad,coral,echo,fable,nova,onyx,sage,shimmer,verse,marin,cedar"
LINES = [  # (style, text): lines of the Chelsea - Manchester City timeline
    ("yes", "Erin Cuthbert, Chelsea, takes a corner kick."),
    ("goal", "Goal! Aggie Beever-Jones puts Chelsea ahead in the 31st minute! Chelsea 1, Manchester City 0."),
    ("no", "Welcome to Stamford Bridge, where Chelsea host Manchester City on matchday one of the Women's Super "
           "League."),
]


def main(args):
    tts_v2.set_openai_style(Namespace(openai_style=args.style))
    client = tts_v2.OpenAITTS(args.model, min_interval=1.0)
    os.makedirs(args.out_dir, exist_ok=True)
    pause = np.zeros(int(0.8 * tts_v2.RATE), dtype=np.int16)
    for voice in [v.strip() for v in args.voices.split(",") if v.strip()]:
        parts = []
        try:
            for style, text in LINES:
                pcm, _ = client.speech(text, voice, tts_v2.OPENAI_STYLE[style])
                parts += [np.frombuffer(pcm, dtype=np.int16), pause]
        except (RuntimeError, OSError) as e:
            print(f"{voice:<8} failed: {str(e)[:150]}")
            if isinstance(e, tts_v2.OpenAIStop):
                break
            continue
        path = os.path.join(args.out_dir, f"{args.style}_{voice}.wav")
        save_wav(path, np.concatenate(parts).tobytes(), tts_v2.RATE)
        print(f"{voice:<8} -> {path}")


if __name__ == "__main__":
    p = ArgumentParser(description="One sample per OpenAI voice, to choose the commentary voices")
    p.add_argument("--voices", default=VOICES, help="comma-separated OpenAI voices")
    p.add_argument("--style", choices=["epic", "calm"], default="epic", help="speaking style (voice/tts_v2.py)")
    p.add_argument("--model", default="gpt-4o-mini-tts")
    p.add_argument("--out_dir", default=os.path.join("outputs", "voice_samples"))
    main(p.parse_args())
