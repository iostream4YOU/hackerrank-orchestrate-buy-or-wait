"""Thin Claude client: JSON-schema constrained calls + token/cost accounting.

Credentials come from the environment only (ANTHROPIC_API_KEY, or a .env file
in the repo root / code/ that defines it). Nothing is ever written to disk.
"""
from __future__ import annotations

import base64
import json
import os
import time

MODEL = os.environ.get("BUYORWAIT_MODEL", "claude-opus-5")
PRICES = {  # USD per 1M tokens (input, output)
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


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

    def add(self, model, task, usage):
        m = self.by_model.setdefault(model, {"calls": 0, "input": 0, "output": 0, "cache_read": 0,
                                             "cache_write": 0, "tasks": {}})
        m["calls"] += 1
        m["input"] += getattr(usage, "input_tokens", 0) or 0
        m["output"] += getattr(usage, "output_tokens", 0) or 0
        m["cache_read"] += getattr(usage, "cache_read_input_tokens", 0) or 0
        m["cache_write"] += getattr(usage, "cache_creation_input_tokens", 0) or 0
        m["tasks"][task] = m["tasks"].get(task, 0) + 1

    def cost(self, model, m):
        pin, pout = PRICES.get(model, (5.0, 25.0))
        return (m["input"] * pin + m["cache_write"] * pin * 1.25 + m["cache_read"] * pin * 0.1
                + m["output"] * pout) / 1e6


class LLM:
    def __init__(self, model=MODEL):
        _load_dotenv()
        self.model = model
        self.usage = Usage()
        self.client = None
        self.error = None
        self._use_fallbacks = True
        try:
            import anthropic  # noqa: F401
            self._anthropic = anthropic
        except ImportError:
            self.error = "anthropic package not installed"
            return
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            self.error = "no ANTHROPIC_API_KEY in environment"
            return
        headers = {}
        if os.environ.get("ANTHROPIC_WORKSPACE_ID"):  # needed for keys not scoped to a workspace
            headers["anthropic-workspace-id"] = os.environ["ANTHROPIC_WORKSPACE_ID"]
        self.client = anthropic.Anthropic(max_retries=4, default_headers=headers or None)

    @property
    def available(self):
        return self.client is not None

    def json_call(self, task, system, content, schema, effort="low", max_tokens=4000):
        """One structured-output call. Returns (dict, served_model)."""
        a = self._anthropic
        kwargs = dict(
            model=self.model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        )
        for attempt in range(3):
            try:
                if self._use_fallbacks:
                    try:  # server-side refusal fallback (beta); plain call if unsupported
                        resp = self.client.beta.messages.create(
                            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
                    except (a.BadRequestError, TypeError) as e:
                        if "workspace" in str(e):
                            raise
                        self._use_fallbacks = False
                        resp = self.client.messages.create(**kwargs)
                else:
                    resp = self.client.messages.create(**kwargs)
                self.usage.add(resp.model, task, resp.usage)
                if resp.stop_reason == "refusal":
                    raise RuntimeError(f"model refused ({task})")
                text = next(b.text for b in resp.content if b.type == "text")
                return json.loads(text), resp.model
            except (a.RateLimitError, a.APIConnectionError, a.InternalServerError):
                time.sleep(2 * (attempt + 1))
            except (a.AuthenticationError, a.PermissionDeniedError, a.BadRequestError) as e:
                # configuration problems are not retryable: disable the model for this run
                self.usage.rejected += 1
                self.client = None
                self.error = f"{type(e).__name__}: {getattr(e, 'message', e)}"
                raise
        raise RuntimeError(f"LLM call failed after retries ({task})")

    @staticmethod
    def image_block(path):
        with open(path, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode("utf-8")
        return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}
