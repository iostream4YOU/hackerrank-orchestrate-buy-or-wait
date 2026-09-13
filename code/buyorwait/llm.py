"""Model clients for the evidence layer: JSON-schema constrained calls + token/cost accounting.

Providers (first configured one that works is used; a key/billing error moves to the next):
  * anthropic - ANTHROPIC_API_KEY (+ ANTHROPIC_WORKSPACE_ID for keys not scoped to a workspace)
  * gemini    - GEMINI_API_KEY (Google AI Studio; plain HTTPS, no extra package)
Order can be forced with BUYORWAIT_PROVIDER, e.g. "gemini" or "anthropic,gemini".
Credentials come from the environment or a .env file in the repo root / code/ and are never
written anywhere else.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request

MODEL = os.environ.get("BUYORWAIT_MODEL", "claude-opus-5")
GEMINI_MODELS = [m.strip() for m in os.environ.get(
    "BUYORWAIT_GEMINI_MODEL", "gemini-3.6-flash,gemini-flash-latest,gemini-3.1-flash-lite").split(",") if m.strip()]
GEMINI_MODEL = GEMINI_MODELS[0]
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
PRICES = {  # USD per 1M tokens (input, output) actually billed for this project
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
PRICES.update({m: (0.0, 0.0) for m in GEMINI_MODELS})  # Google AI Studio free tier: no charge


def _load_dotenv():
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(here, "..", "..", ".env"), os.path.join(here, "..", ".env")):
        path = os.path.normpath(path)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class Usage:
    def __init__(self):
        self.by_model = {}
        self.rejected = 0   # requests refused before billing (auth / credit / config)

    def record(self, model, task, input_tokens, output_tokens, cache_read=0, cache_write=0):
        m = self.by_model.setdefault(model, {"calls": 0, "input": 0, "output": 0, "cache_read": 0,
                                             "cache_write": 0, "tasks": {}})
        m["calls"] += 1
        m["input"] += input_tokens or 0
        m["output"] += output_tokens or 0
        m["cache_read"] += cache_read or 0
        m["cache_write"] += cache_write or 0
        m["tasks"][task] = m["tasks"].get(task, 0) + 1

    def cost(self, model, m):
        pin, pout = PRICES.get(model, (5.0, 25.0))
        return (m["input"] * pin + m["cache_write"] * pin * 1.25 + m["cache_read"] * pin * 0.1
                + m["output"] * pout) / 1e6


class ConfigError(RuntimeError):
    """Non-retryable provider problem (bad key, no credit, missing permission)."""


def _gemini_schema(s):
    """JSON Schema subset -> Gemini responseSchema (OpenAPI style, nullable instead of type unions)."""
    t = s.get("type")
    out = {}
    if isinstance(t, list):
        out["nullable"] = "null" in t
        t = [x for x in t if x != "null"][0]
    out["type"] = t.upper()
    if "enum" in s:
        out["enum"] = s["enum"]
    if t == "object":
        out["properties"] = {k: _gemini_schema(v) for k, v in s["properties"].items()}
        out["required"] = list(s.get("required", []))
    if t == "array":
        out["items"] = _gemini_schema(s["items"])
    return out


class _Anthropic:
    name = "anthropic"

    def __init__(self, usage):
        import anthropic
        self.a = anthropic
        self.usage = usage
        self.model = MODEL
        headers = {}
        if os.environ.get("ANTHROPIC_WORKSPACE_ID"):
            headers["anthropic-workspace-id"] = os.environ["ANTHROPIC_WORKSPACE_ID"]
        self.client = anthropic.Anthropic(max_retries=4, default_headers=headers or None)
        self.use_fallbacks = True

    def call(self, task, system, content, schema, effort):
        a = self.a
        kwargs = dict(model=self.model, max_tokens=4000, system=system,
                      messages=[{"role": "user", "content": content}],
                      output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}})
        for attempt in range(3):
            try:
                if self.use_fallbacks:
                    try:  # server-side refusal fallback (beta); plain call if unsupported
                        resp = self.client.beta.messages.create(
                            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
                    except (a.BadRequestError, TypeError) as e:
                        if "workspace" in str(e) or "credit" in str(e):
                            raise
                        self.use_fallbacks = False
                        resp = self.client.messages.create(**kwargs)
                else:
                    resp = self.client.messages.create(**kwargs)
                u = resp.usage
                self.usage.record(resp.model, task, u.input_tokens, u.output_tokens,
                                  getattr(u, "cache_read_input_tokens", 0), getattr(u, "cache_creation_input_tokens", 0))
                if resp.stop_reason == "refusal":
                    raise RuntimeError(f"model refused ({task})")
                return json.loads(next(b.text for b in resp.content if b.type == "text")), resp.model
            except (a.RateLimitError, a.APIConnectionError, a.InternalServerError):
                time.sleep(2 * (attempt + 1))
            except (a.AuthenticationError, a.PermissionDeniedError, a.BadRequestError) as e:
                raise ConfigError(f"{type(e).__name__}: {getattr(e, 'message', e)}")
        raise RuntimeError(f"anthropic call failed after retries ({task})")


class _Gemini:
    """Gemini over plain HTTPS. Free-tier keys have small per-model daily quotas, so a daily-quota
    refusal moves to the next model in GEMINI_MODELS instead of retrying; per-minute limits and
    overloads are retried with backoff."""
    name = "gemini"

    def __init__(self, usage):
        self.usage = usage
        self.models = list(GEMINI_MODELS)
        self.key = os.environ["GEMINI_API_KEY"]

    @property
    def model(self):
        return self.models[0] if self.models else GEMINI_MODEL

    @staticmethod
    def _parts(content):
        if isinstance(content, str):
            return [{"text": content}]
        parts = []
        for block in content:  # Anthropic-style blocks -> Gemini parts
            if block["type"] == "image":
                src = block["source"]
                parts.append({"inline_data": {"mime_type": src["media_type"], "data": src["data"]}})
            else:
                parts.append({"text": block["text"]})
        return parts

    def call(self, task, system, content, schema, effort):
        body = json.dumps({"systemInstruction": {"parts": [{"text": system}]},
                           "contents": [{"role": "user", "parts": self._parts(content)}],
                           "generationConfig": {"responseMimeType": "application/json",
                                                "responseSchema": _gemini_schema(schema), "temperature": 0}}
                          ).encode("utf-8")
        attempt = 0
        while self.models:
            model = self.models[0]
            req = urllib.request.Request(GEMINI_URL.format(model=model), data=body, method="POST",
                                         headers={"x-goog-api-key": self.key, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    resp = json.load(r)
            except urllib.error.HTTPError as e:
                detail = e.read()[:2000].decode("utf-8", "replace")
                if e.code == 429 and "PerDay" in detail or e.code == 404:
                    self.models.pop(0)          # daily quota spent / model retired: next model
                    attempt = 0
                    continue
                if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                    attempt += 1
                    time.sleep(min(60, 8 * attempt))
                    continue
                if e.code in (429, 503):
                    self.models.pop(0)
                    attempt = 0
                    continue
                raise ConfigError(f"Gemini HTTP {e.code}: {detail[:200]}")
            except (urllib.error.URLError, TimeoutError):
                attempt += 1
                if attempt > 3:
                    raise RuntimeError(f"gemini network failure ({task})")
                time.sleep(5 * attempt)
                continue
            u = resp.get("usageMetadata", {})
            served = resp.get("modelVersion", model)
            self.usage.record(served, task, u.get("promptTokenCount", 0),
                              u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0))
            cand = (resp.get("candidates") or [{}])[0]
            text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []) if not p.get("thought"))
            if not text:
                raise RuntimeError(f"empty Gemini response ({task}, finish={cand.get('finishReason')})")
            PRICES.setdefault(served, (0.0, 0.0))
            return json.loads(text), served
        raise ConfigError("Gemini: every configured model is out of free-tier quota or unavailable")


class LLM:
    def __init__(self, model=None):
        _load_dotenv()
        self.usage = Usage()
        self.error = None
        self.backends = []
        order = [p.strip() for p in os.environ.get("BUYORWAIT_PROVIDER", "anthropic,gemini").split(",") if p.strip()]
        problems = []
        for name in order:
            if name == "anthropic":
                if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
                    problems.append("no ANTHROPIC_API_KEY")
                    continue
                try:
                    self.backends.append(_Anthropic(self.usage))
                except ImportError:
                    problems.append("anthropic package not installed")
            elif name == "gemini":
                if os.environ.get("GEMINI_API_KEY"):
                    self.backends.append(_Gemini(self.usage))
                else:
                    problems.append("no GEMINI_API_KEY")
        if not self.backends:
            self.error = "; ".join(problems) or "no model provider configured"

    @property
    def available(self):
        return bool(self.backends)

    @property
    def model(self):
        return self.backends[0].model if self.backends else MODEL

    def json_call(self, task, system, content, schema, effort="low", max_tokens=4000):
        """One structured-output call on the first working provider. Returns (dict, served_model)."""
        while self.backends:
            backend = self.backends[0]
            try:
                return backend.call(task, system, content, schema, effort)
            except ConfigError as e:
                self.usage.rejected += 1
                self.error = f"{backend.name}: {e}"
                self.backends.pop(0)  # key/credit problem: fall through to the next provider
        raise RuntimeError(self.error or "no model provider available")

    @staticmethod
    def image_block(path):
        with open(path, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode("utf-8")
        return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}
