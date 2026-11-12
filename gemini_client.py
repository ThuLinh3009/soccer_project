"""Small REST client for Google Gemini: text generation (commentary lines) and text-to-speech (voice).

No SDK needed (urllib only). The API key is read from the GEMINI_API_KEY environment variable by the callers and is
never written to a file. Two kinds of keys work:
    gemini  Google AI Studio key -> https://generativelanguage.googleapis.com/v1beta (header x-goog-api-key)
    vertex  Vertex AI express-mode key -> https://aiplatform.googleapis.com/v1/publishers/google (?key=...)
backend="auto" tries the AI Studio endpoint first, then Vertex.

TTS: gemini-2.5-*-tts through generateContent (responseModalities AUDIO), newer TTS models (gemini-3.x-*-tts) through
the Interactions API. Audio is 16-bit mono PCM, 24 kHz, saved as wav.
There is no "gemini-2.5-flash-lite" TTS model: the Flash-Lite TTS model is gemini-3.8-flash-lite-tts (default).

usage (check the key and list the models it can use):
    python gemini_client.py --check
"""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from argparse import ArgumentParser

ENDPOINTS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    "vertex": "https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent",
}
LIST_MODELS = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000"
INTERACTIONS = "https://generativelanguage.googleapis.com/v1beta/interactions"  # newer TTS models (AI Studio keys)
RETRY_STATUS = {429, 500, 502, 503, 504}


class GeminiError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status

    @property
    def quota(self):
        """429 because the quota of the model is used up (free tier: a few requests per day): retrying is useless."""
        return self.status == 429 and "exceeded your current quota" in str(self).lower()


class ModelPool:
    """Models tried in order: when one has no quota left, the next one is used (e.g. free tier daily limits)."""

    def __init__(self, models):
        self.models = [m.strip() for m in (models.split(",") if isinstance(models, str) else models) if m.strip()]
        self.i = 0

    @property
    def current(self):
        return self.models[self.i] if self.i < len(self.models) else None

    def call(self, fn):
        while self.current:
            try:
                return fn(self.current)
            except GeminiError as e:
                if not e.quota and e.status != 404:
                    raise
                why = "no quota left" if e.quota else "not found"
                print(f"    {self.current}: {why} -> " + (f"switching to {self.models[self.i + 1]}"
                                                         if self.i + 1 < len(self.models) else "no model left"))
                self.i += 1
        raise GeminiError(429, "every model in the list has no quota left")


def read_key(env="GEMINI_API_KEY"):
    key = (os.environ.get(env) or "").strip().strip("\"'").strip()  # pasted with spaces / quotes
    if not key:
        raise SystemExit(f"set the {env} environment variable first (Colab: Secrets -> {env})")
    return key


class Gemini:
    def __init__(self, api_key, backend="auto", timeout=60, retries=4, min_interval=0.0):
        self.key, self.timeout, self.retries = api_key, timeout, retries
        self.min_interval, self._last = min_interval, 0.0  # seconds between calls (free tier: requests per minute)
        self.backend = self.detect() if backend == "auto" else backend

    # ------------------------------------------------------------ http
    def _request(self, url, body=None, backend=None):
        backend = backend or self.backend
        headers = {"Content-Type": "application/json"}
        if backend == "vertex":
            url += ("&" if "?" in url else "?") + "key=" + urllib.parse.quote(self.key)
        else:
            headers["x-goog-api-key"] = self.key
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors="replace")
            try:
                text = json.loads(text)["error"]["message"]
            except (ValueError, KeyError, TypeError):
                pass
            raise GeminiError(e.code, text[:500]) from None

    def _generate(self, model, body, url=None):
        for attempt in range(self.retries + 1):
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            try:
                return self._request(url or ENDPOINTS[self.backend].format(model=model), body)
            except GeminiError as e:
                if e.status not in RETRY_STATUS or e.quota or attempt == self.retries:
                    raise
                delay = 15 * (attempt + 1) if e.status == 429 else 3 * (attempt + 1)
                m = re.search(r"retry in ([\d.]+)s", str(e))
                if m:
                    delay = max(delay, float(m.group(1)) + 1)
                print(f"    Gemini {e.status}, retry in {delay:.0f}s")
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == self.retries:
                    raise
                time.sleep(3 * (attempt + 1))

    # ------------------------------------------------------------ setup
    def detect(self):
        """gemini if the key works on AI Studio (list models), else vertex if a tiny call works there."""
        try:
            self._request(LIST_MODELS, backend="gemini")
            return "gemini"
        except GeminiError as e:
            first = e
        try:
            self._request(ENDPOINTS["vertex"].format(model="gemini-2.5-flash-lite"),
                          {"contents": [{"role": "user", "parts": [{"text": "Say OK."}]}],
                           "generationConfig": {"maxOutputTokens": 5}}, backend="vertex")
            return "vertex"
        except GeminiError as e:
            raise SystemExit(f"the key works neither on AI Studio ({first}) nor on Vertex AI express ({e})")

    def list_models(self):
        """Model ids usable with generateContent (AI Studio keys only; Vertex has no list for express keys)."""
        if self.backend != "gemini":
            return []
        out = self._request(LIST_MODELS, backend="gemini")
        return sorted(m["name"].split("/")[-1] for m in out.get("models", [])
                      if "generateContent" in m.get("supportedGenerationMethods", []))

    # ------------------------------------------------------------ text
    def text(self, model, system, message, temperature=0.7, max_tokens=256):
        config = {"temperature": temperature, "maxOutputTokens": max_tokens}
        if "2.5" in model and "tts" not in model:
            config["thinkingConfig"] = {"thinkingBudget": 0}  # short lines: no thinking, faster and cheaper
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": message}]}], "generationConfig": config}
        out = self._generate(model, body)
        parts = (out.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts).strip()

    # ------------------------------------------------------------ speech
    def speech(self, model, text, voice="Puck", style=None):
        """(pcm bytes, sample rate). style: delivery, e.g. 'excited live football commentator'.

        gemini-2.5-*-tts: generateContent, the style goes in the prompt ("Say <style>: <text>").
        newer TTS models (gemini-3.x): they read the whole prompt aloud, so they go through the Interactions API,
        where the style is metadata (speech_metadata) and the text is spoken word for word.
        """
        if model.startswith("gemini-2.5"):
            prompt = f"Say {style}: {text}" if style else text
            body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                        "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
            out = self._generate(model, body)
            blobs = [p.get("inlineData") or p.get("inline_data") or {}
                     for p in (out.get("candidates") or [{}])[0].get("content", {}).get("parts", [])]
            blobs = [(b.get("data"), b.get("mimeType", "")) for b in blobs]
        else:
            content = {"type": "text", "text": text}
            if style:
                content["annotations"] = [{"type": "speech_metadata", "style": style}]
            body = {"model": model, "input": [{"type": "user_input", "content": [content]}],
                    "response_format": {"type": "audio"}, "generation_config": {"speech_config": [{"voice": voice}]}}
            out = self._generate(model, body, url=INTERACTIONS)
            blobs = [(c.get("data"), c.get("mime_type") or c.get("mimeType", ""))
                     for step in out.get("steps", []) for c in step.get("content", [])]
        for data, mime in blobs:
            if data:
                audio = base64.b64decode(data)
                if audio[:4] == b"RIFF":  # wav file
                    return wav_to_pcm(audio)
                m = re.search(r"rate=(\d+)", mime)
                return audio, int(m.group(1)) if m else 24000
        raise GeminiError(200, f"no audio in the answer: {json.dumps(out)[:300]}")


def wav_to_pcm(data):
    import io
    with wave.open(io.BytesIO(data)) as w:
        return w.readframes(w.getnframes()), w.getframerate()


def save_wav(path, pcm, rate):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


if __name__ == "__main__":
    p = ArgumentParser(description="Check a Gemini API key and list the models it can use")
    p.add_argument("--check", action="store_true")
    p.add_argument("--backend", default="auto", choices=["auto", "gemini", "vertex"])
    p.add_argument("--llm_model", default="gemini-2.5-flash-lite,gemini-3.1-flash-lite,gemini-3.5-flash-lite")
    p.add_argument("--tts_model", default="gemini-3.8-flash-lite-tts,gemini-2.5-flash-preview-tts,"
                                          "gemini-3.1-flash-tts-preview")
    args = p.parse_args()
    key = read_key()
    g = Gemini(key, args.backend, retries=1)
    print(f"key: {len(key)} characters, starts with {key[:3]}… | backend: {g.backend}")
    models = g.list_models()
    if models:
        print("TTS models:", ", ".join(m for m in models if "tts" in m) or "none")
        print("flash-lite models:", ", ".join(m for m in models if "flash-lite" in m and "tts" not in m) or "none")
    text_pool, tts_pool = ModelPool(args.llm_model), ModelPool(args.tts_model)
    try:
        answer = text_pool.call(lambda m: g.text(m, "Answer in five words or fewer.", "Say hello to football fans."))
        print(f"text test ({text_pool.current}): {answer}")
    except GeminiError as e:
        print("text test failed:", e)
    try:
        pcm, rate = tts_pool.call(lambda m: g.speech(m, "Hello and welcome.", style="football commentator"))
        print(f"tts test ({tts_pool.current}): {len(pcm) / 2 / rate:.1f} s of audio at {rate} Hz")
    except GeminiError as e:
        print("tts test failed:", e)
