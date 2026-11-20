"""Provider abstraction over Gemini (primary) and Groq (fallback) using plain REST.

* Ordered fallback chain per task (config.REASONING_CHAIN / EXTRACTION_CHAIN).
  Fallbacks are never silent: every result records the provider/model that
  actually answered, and every call is appended to logs/llm_usage.jsonl.
* Retries with exponential backoff on 429/5xx/timeouts; a per-model circuit
  breaker skips a model for a cool-down after repeated overload errors.
* Response cache (SQLite) keyed on (model, system, prompt): re-runs are free,
  deterministic and resumable after a crash or quota stop.
* Keys come from the environment only and are never logged.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass

import requests

import config

log = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    data: dict | list | None
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    retries: int = 0
    cached: bool = False
    est_cost_usd: float = 0.0


def parse_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                return None
    return None


class LLMClient:
    def __init__(self, cache_path=config.LLM_CACHE_PATH, usage_path=None, use_cache=True):
        self.use_cache = use_cache
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache = sqlite3.connect(str(cache_path), check_same_thread=False)
        self._cache.execute("CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT)")
        # circuit-breaker state is shared across processes so a dead model is not re-probed by every script
        self._cache.execute("CREATE TABLE IF NOT EXISTS breaker (model TEXT PRIMARY KEY, until REAL)")
        self._lock = threading.Lock()
        config.LOG_DIR.mkdir(exist_ok=True)
        self.usage_path = usage_path or (config.LOG_DIR / "llm_usage.jsonl")
        self._breaker: dict[str, float] = {}   # model -> skip-until timestamp
        self._fail_counts: dict[str, int] = {}
        self.session_usage: list[dict] = []

    # ------------------------------------------------------------------ public
    def complete(self, prompt: str, system: str = "", chain=None, json_mode=True,
                 max_tokens=4096, temperature=0.1, task="generic") -> LLMResult:
        chain = chain or config.REASONING_CHAIN
        errors = []
        for provider, model in chain:
            key = self._key(model, system, prompt, json_mode)
            if self.use_cache:
                hit = self._cache.execute("SELECT v FROM cache WHERE k=?", (key,)).fetchone()
                if hit:
                    d = json.loads(hit[0])
                    res = LLMResult(**{**d, "cached": True})
                    self._record(res, task)
                    return res
            if self._breaker_until(model) > time.time():
                errors.append(f"{model}: circuit open")
                continue
            if not os.getenv("GEMINI_API_KEY" if provider == "gemini" else "GROQ_API_KEY"):
                errors.append(f"{provider}: no API key")
                continue
            try:
                res = self._call_with_retries(provider, model, prompt, system, json_mode, max_tokens, temperature)
            except LLMUnavailable as e:
                errors.append(f"{provider}/{model}: {e}")
                log.warning("LLM fallback: %s/%s failed (%s)", provider, model, e)
                continue
            if json_mode and res.data is None:
                errors.append(f"{model}: unparseable JSON")
                log.warning("LLM %s returned unparseable JSON; trying next", model)
                continue
            if self.use_cache:
                with self._lock:
                    self._cache.execute("INSERT OR REPLACE INTO cache VALUES (?,?)",
                                        (key, json.dumps({k: v for k, v in asdict(res).items() if k != "cached"})))
                    self._cache.commit()
            self._record(res, task)
            return res
        raise LLMUnavailable("all providers failed: " + "; ".join(errors))

    # ----------------------------------------------------------------- private
    def _breaker_until(self, model) -> float:
        row = self._cache.execute("SELECT until FROM breaker WHERE model=?", (model,)).fetchone()
        return max(self._breaker.get(model, 0), row[0] if row else 0)

    def _open_breaker(self, model, seconds):
        self._breaker[model] = time.time() + seconds
        with self._lock:
            self._cache.execute("INSERT OR REPLACE INTO breaker VALUES (?,?)", (model, self._breaker[model]))
            self._cache.commit()
        log.warning("circuit opened for %s (%ds)", model, seconds)

    @staticmethod
    def _key(model, system, prompt, json_mode):
        return hashlib.sha256(json.dumps([model, system, prompt, json_mode]).encode()).hexdigest()

    def _call_with_retries(self, provider, model, prompt, system, json_mode, max_tokens, temperature):
        delay = 3.0
        last = ""
        api_json = json_mode  # may be switched off for one provider retry; parsing still uses json_mode
        for attempt in range(config.LLM_MAX_RETRIES + 1):
            t0 = time.time()
            try:
                fn = self._gemini if provider == "gemini" else self._groq
                text, tin, tout = fn(model, prompt, system, api_json, max_tokens, temperature)
                self._fail_counts[model] = 0
                price = config.PRICING.get(model, {"in": 0, "out": 0})
                return LLMResult(text=text, data=parse_json(text) if json_mode else None, provider=provider,
                                 model=model, input_tokens=tin, output_tokens=tout,
                                 latency_s=round(time.time() - t0, 2), retries=attempt,
                                 est_cost_usd=(tin * price["in"] + tout * price["out"]) / 1e6)
            except requests.HTTPError as e:
                code = e.response.status_code
                full = e.response.text or ""
                body = full[:300]
                last = f"HTTP {code}: {body}"
                if code == 429 and _is_daily_quota(provider, full):
                    # Gemini "PerDay" quotas reset daily; Groq TPD is a rolling window -> shorter lockout
                    self._open_breaker(model, 6 * 3600 if provider == "gemini" else 1800)
                    raise LLMUnavailable("daily free-tier quota exhausted")
                if code == 400 and "json_validate_failed" in body and api_json:
                    # Groq's server-side JSON validator rejected the output: retry once without
                    # response_format and parse the JSON ourselves.
                    api_json = False
                    continue
                if code in (400, 401, 403, 404, 413) or "too large" in body.lower():
                    raise LLMUnavailable(last)  # not retryable (Groq reports oversize requests as 429 too)
                retry_after = e.response.headers.get("retry-after")
                wait = float(retry_after) if retry_after and retry_after.replace(".", "").isdigit() else delay
                if code == 429 and wait > 60:
                    raise LLMUnavailable(f"rate limited for {wait:.0f}s")
                if code >= 500:
                    self._fail_counts[model] = self._fail_counts.get(model, 0) + 1
                    if self._fail_counts[model] >= config.CIRCUIT_FAILURES:
                        self._open_breaker(model, config.CIRCUIT_COOLDOWN_S)
                        raise LLMUnavailable(f"overloaded ({code}), circuit opened")
            except (requests.Timeout, requests.ConnectionError) as e:
                last = f"network: {type(e).__name__}"
                self._fail_counts[model] = self._fail_counts.get(model, 0) + 1
                if self._fail_counts[model] >= config.CIRCUIT_FAILURES - 1:  # timeouts are expensive
                    self._open_breaker(model, config.TIMEOUT_COOLDOWN_S)
                    raise LLMUnavailable("timeouts, circuit opened")
                wait = delay
            if attempt < config.LLM_MAX_RETRIES:
                time.sleep(min(wait, 60))
                delay *= 2
        raise LLMUnavailable(f"retries exhausted ({last})")

    def _gemini(self, model, prompt, system, json_mode, max_tokens, temperature):
        gen = {"temperature": temperature, "maxOutputTokens": max_tokens}
        if json_mode:
            gen["responseMimeType"] = "application/json"
        if model.startswith("gemini-3"):
            gen["thinkingConfig"] = {"thinkingLevel": "low"}
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": gen}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                          headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, json=body,
                          timeout=config.LLM_TIMEOUT_S)
        r.raise_for_status()
        d = r.json()
        cand = (d.get("candidates") or [{}])[0]
        parts = cand.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text:
            raise requests.HTTPError(response=_FakeResp(502, f"empty response finish={cand.get('finishReason')}"))
        u = d.get("usageMetadata", {})
        return text, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)

    def _groq(self, model, prompt, system, json_mode, max_tokens, temperature):
        est_in = int(len(prompt + system) / 3.2) + 50   # conservative chars->tokens estimate
        cap = min(max_tokens, config.GROQ_TPM - est_in)
        if cap < 800:
            raise requests.HTTPError(response=_FakeResp(413, f"prompt ~{est_in} tokens too large for Groq free-tier TPM"))
        max_tokens = cap
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        body = {"model": model, "messages": msgs, "temperature": temperature, "max_tokens": max_tokens}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if "gpt-oss" in model:
            body["reasoning_effort"] = "low"
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                          headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"}, json=body,
                          timeout=config.LLM_TIMEOUT_S)
        r.raise_for_status()
        d = r.json()
        u = d.get("usage", {})
        return d["choices"][0]["message"]["content"] or "", u.get("prompt_tokens", 0), u.get("completion_tokens", 0)

    def _record(self, res: LLMResult, task: str):
        row = {"ts": time.time(), "task": task, **{k: v for k, v in asdict(res).items() if k not in ("text", "data")}}
        self.session_usage.append(row)
        with self._lock, open(self.usage_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def usage_summary(self) -> dict:
        live = [u for u in self.session_usage if not u["cached"]]
        by_model: dict[str, dict] = {}
        for u in self.session_usage:
            m = by_model.setdefault(f"{u['provider']}/{u['model']}", {"calls": 0, "cached": 0, "in": 0, "out": 0, "cost": 0.0})
            m["calls"] += 1
            m["cached"] += int(u["cached"])
            m["in"] += u["input_tokens"]
            m["out"] += u["output_tokens"]
            m["cost"] += u["est_cost_usd"] if not u["cached"] else 0
        return {"calls": len(self.session_usage), "live_calls": len(live), "by_model": by_model}


def _is_daily_quota(provider: str, body: str) -> bool:
    """True only when the violated quota itself is a per-day quota (not merely mentioned in the body)."""
    if provider == "gemini":
        try:
            details = json.loads(body).get("error", {}).get("details", [])
            ids = [v.get("quotaId", "") for d in details for v in d.get("violations", [])]
            return any("PerDay" in i for i in ids)
        except (ValueError, AttributeError):
            return False
    return "tokens per day" in body.lower() or "requests per day" in body.lower()


class _FakeResp:
    def __init__(self, code, text):
        self.status_code, self.text, self.headers = code, text, {}


_client: LLMClient | None = None


def get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
