"""Small REST client for OpenAI chat models (v5.9): the no flow writes its commentary lines with gpt-4o-mini.

No SDK needed (urllib only). The key is read from the OPENAI_API_KEY environment variable (Colab: Secrets) and is
never written to a file. Same interface as gemini_client.Gemini.text(), so commentary/no_flow_v2.py uses either one; errors are
raised as gemini_client.GeminiError so that ModelPool stops when the key is refused or there is no credit left.

usage (check the key):
    python -m api.openai_client --check
"""
import json
import time
import urllib.error
import urllib.request
from argparse import ArgumentParser

from api.gemini_client import GeminiError, read_key

CHAT_URL = "https://api.openai.com/v1/chat/completions"
RETRY_STATUS = {429, 500, 502, 503, 504}


class OpenAIChat:
    backend = "openai"

    def __init__(self, api_key, timeout=60, retries=4, min_interval=0.0):
        self.key, self.timeout, self.retries = api_key, timeout, retries
        self.min_interval, self._last = min_interval, 0.0

    def text(self, model, system, message, temperature=0.7, max_tokens=200):
        body = {"model": model, "temperature": temperature, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": message}]}
        for attempt in range(self.retries + 1):
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            req = urllib.request.Request(CHAT_URL, data=json.dumps(body).encode(), method="POST",
                                         headers={"Authorization": f"Bearer {self.key}",
                                                  "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.loads(r.read().decode())
                return (data["choices"][0]["message"].get("content") or "").strip()
            except urllib.error.HTTPError as e:
                text = e.read().decode(errors="replace")
                try:
                    err = json.loads(text)["error"]
                    text, code = err.get("message", text), err.get("code") or ""
                except (ValueError, KeyError, TypeError):
                    code = ""
                if e.code == 401 or code == "insufficient_quota":
                    # no use asking again: ModelPool reads this as "no quota left" and stops calling the LLM
                    raise GeminiError(429, f"exceeded your current quota (OpenAI {e.code} {code}): {text[:300]}") \
                        from None
                if e.code in RETRY_STATUS and attempt < self.retries:
                    time.sleep(min(30, 2 ** attempt * 2))
                    continue
                raise GeminiError(e.code, text[:500]) from None
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < self.retries:
                    time.sleep(3)
                    continue
                raise GeminiError(0, f"network error: {e}") from None
        raise GeminiError(0, "too many retries")


if __name__ == "__main__":
    p = ArgumentParser(description="Check the OpenAI key with one short chat request")
    p.add_argument("--check", action="store_true")
    p.add_argument("--model", default="gpt-4o-mini")
    args = p.parse_args()
    client = OpenAIChat(read_key("OPENAI_API_KEY"))
    print(f"{args.model}:", client.text(args.model, "Answer with one word.", "Say OK.", 0.0, max_tokens=5))
