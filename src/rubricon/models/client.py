"""Model client abstraction.

The repository runs end-to-end with no API key and no network. That is a
deliberate property, not a limitation to apologise for: an evaluation harness
whose results move when someone else's inference endpoint changes is not
reproducible, and reproducibility is the point.

Three implementations:

* ``FixtureClient`` - replays the authored corpus. The default. Deterministic,
  free, offline.
* ``CachedClient`` - wraps a live client with a content-addressed disk cache, so
  re-running an analysis never re-bills or re-samples. The cache key includes
  the prompt, the system id, and the decoding parameters, because a temperature
  change is a different experiment.
* ``LiveClient`` subclasses (Anthropic / OpenAI / Ollama) - thin adapters. They
  are unexercised in the default run and are marked as such; claiming otherwise
  would be exactly the kind of unverified assertion this project is about.

Swapping ``FixtureClient`` for a live client is a one-line change in the
pipeline and requires no change to any downstream module, because everything
downstream consumes ``ModelResponse``.
"""

from __future__ import annotations

import hashlib
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from ..core.schema import ModelResponse, TaskItem


@dataclass(frozen=True)
class GenerationConfig:
    """Decoding parameters. Part of the cache key: changing any of these is a
    different experiment and must not silently reuse prior samples."""

    model: str = "fixture"
    temperature: float = 0.0
    top_p: float = 1.0
    max_tokens: int = 2048
    seed: int | None = 0
    system_prompt: str = ""

    def cache_key(self, item: TaskItem) -> str:
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "seed": self.seed,
            "system_prompt": self.system_prompt,
            "prompt": item.prompt,
            "context": item.context,
            "item_id": item.item_id,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()[:24]

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "seed": self.seed,
            "system_prompt_sha256_12": hashlib.sha256(
                self.system_prompt.encode()
            ).hexdigest()[:12],
        }


class ModelClient(ABC):
    """Everything downstream depends on this interface and nothing else."""

    system_id: str = "unknown"
    is_live: bool = False

    @abstractmethod
    def generate(self, item: TaskItem, config: GenerationConfig) -> ModelResponse: ...

    def generate_batch(
        self, items: Sequence[TaskItem], config: GenerationConfig
    ) -> list[ModelResponse]:
        return [self.generate(i, config) for i in items]

    def provenance(self) -> dict:
        return {"system_id": self.system_id, "is_live": self.is_live, "client": type(self).__name__}


class FixtureClient(ModelClient):
    """Replays authored responses. The default execution path."""

    is_live = False

    def __init__(self, responses: Iterable[ModelResponse], system_id: str) -> None:
        self.system_id = system_id
        self._by_item: dict[str, ModelResponse] = {
            r.item_id: r for r in responses if r.system_id == system_id
        }

    def generate(self, item: TaskItem, config: GenerationConfig) -> ModelResponse:
        try:
            return self._by_item[item.item_id]
        except KeyError:
            raise KeyError(
                f"No fixture response for item {item.item_id!r} under system "
                f"{self.system_id!r}. Fixture corpora must be complete; a missing "
                "response would silently reduce n and bias the aggregate."
            ) from None

    def provenance(self) -> dict:
        d = super().provenance()
        d["n_fixtures"] = len(self._by_item)
        d["note"] = "Authored fixture corpus, not live model output."
        return d


class CachedClient(ModelClient):
    """Content-addressed disk cache in front of any client."""

    def __init__(self, inner: ModelClient, cache_dir: str | Path = ".cache/responses") -> None:
        self.inner = inner
        self.system_id = inner.system_id
        self.is_live = inner.is_live
        self.cache_dir = Path(cache_dir) / self.system_id
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0

    def generate(self, item: TaskItem, config: GenerationConfig) -> ModelResponse:
        path = self.cache_dir / f"{config.cache_key(item)}.json"
        if path.exists():
            self.hits += 1
            return ModelResponse.from_dict(json.loads(path.read_text(encoding="utf-8")))
        self.misses += 1
        resp = self.inner.generate(item, config)
        path.write_text(json.dumps(resp.to_dict(), sort_keys=True), encoding="utf-8")
        return resp

    def provenance(self) -> dict:
        d = self.inner.provenance()
        d.update({"cache_hits": self.hits, "cache_misses": self.misses,
                  "cache_dir": str(self.cache_dir)})
        return d


# --------------------------------------------------------------------------
# live adapters
# --------------------------------------------------------------------------


class LiveClient(ModelClient):
    """Base for network-backed clients.

    NOT exercised by the default pipeline run and NOT covered by the test suite.
    Marked explicitly rather than left ambiguous.
    """

    is_live = True

    def __init__(self, system_id: str, api_key_env: str) -> None:
        self.system_id = system_id
        self.api_key_env = api_key_env

    def _key(self) -> str:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise RuntimeError(
                f"{type(self).__name__} requires {self.api_key_env} in the environment. "
                "The default pipeline uses FixtureClient and needs no key; set "
                "RUBRICON_CLIENT=anthropic|openai|ollama to opt into live generation."
            )
        return key

    def provenance(self) -> dict:
        d = super().provenance()
        d["verified_in_this_repo"] = False
        d["note"] = "Live adapter; unexercised in the reproducible offline run."
        return d


class AnthropicClient(LiveClient):
    def __init__(self, system_id: str = "anthropic", model: str = "claude-sonnet-4-5") -> None:
        super().__init__(system_id, "ANTHROPIC_API_KEY")
        self.model = model

    def generate(self, item: TaskItem, config: GenerationConfig) -> ModelResponse:
        import anthropic  # imported lazily so the package is not a hard dependency

        client = anthropic.Anthropic(api_key=self._key())
        prompt = f"{item.context}\n\n{item.prompt}".strip()
        msg = client.messages.create(
            model=config.model if config.model != "fixture" else self.model,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            system=config.system_prompt or "You are a helpful assistant.",
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return ModelResponse(
            response_id=f"{item.item_id}::{self.system_id}",
            item_id=item.item_id,
            system_id=self.system_id,
            text=text,
            tokens_out=getattr(msg.usage, "output_tokens", 0),
            metadata={"model": msg.model, "stop_reason": msg.stop_reason},
        )


class OpenAIClient(LiveClient):
    def __init__(self, system_id: str = "openai", model: str = "gpt-4o-mini") -> None:
        super().__init__(system_id, "OPENAI_API_KEY")
        self.model = model

    def generate(self, item: TaskItem, config: GenerationConfig) -> ModelResponse:
        from openai import OpenAI

        client = OpenAI(api_key=self._key())
        prompt = f"{item.context}\n\n{item.prompt}".strip()
        msgs = []
        if config.system_prompt:
            msgs.append({"role": "system", "content": config.system_prompt})
        msgs.append({"role": "user", "content": prompt})
        r = client.chat.completions.create(
            model=config.model if config.model != "fixture" else self.model,
            messages=msgs,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
        return ModelResponse(
            response_id=f"{item.item_id}::{self.system_id}",
            item_id=item.item_id,
            system_id=self.system_id,
            text=r.choices[0].message.content or "",
            tokens_out=r.usage.completion_tokens if r.usage else 0,
            metadata={"model": r.model},
        )


class OllamaClient(LiveClient):
    """Local runner. No API key needed; the env var check is skipped."""

    def __init__(self, system_id: str = "ollama", model: str = "llama3.1",
                 host: str = "http://localhost:11434") -> None:
        super().__init__(system_id, "OLLAMA_HOST")
        self.model = model
        self.host = os.environ.get("OLLAMA_HOST", host)

    def _key(self) -> str:
        return "local"

    def generate(self, item: TaskItem, config: GenerationConfig) -> ModelResponse:
        import urllib.request

        prompt = f"{item.context}\n\n{item.prompt}".strip()
        body = json.dumps({
            "model": config.model if config.model != "fixture" else self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": config.temperature, "seed": config.seed},
        }).encode()
        req = urllib.request.Request(
            f"{self.host}/api/generate", data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=300) as r:
            payload = json.loads(r.read())
        return ModelResponse(
            response_id=f"{item.item_id}::{self.system_id}",
            item_id=item.item_id,
            system_id=self.system_id,
            text=payload.get("response", ""),
            metadata={"model": payload.get("model", self.model)},
        )


def build_client(kind: str, system_id: str, fixtures: Sequence[ModelResponse] | None = None,
                 **kw) -> ModelClient:
    kind = (kind or "fixture").lower()
    if kind == "fixture":
        if fixtures is None:
            raise ValueError("FixtureClient requires a fixture corpus")
        return FixtureClient(fixtures, system_id)
    if kind == "anthropic":
        return AnthropicClient(system_id, **kw)
    if kind == "openai":
        return OpenAIClient(system_id, **kw)
    if kind == "ollama":
        return OllamaClient(system_id, **kw)
    raise ValueError(f"unknown client kind {kind!r}")


__all__ = [
    "AnthropicClient",
    "CachedClient",
    "FixtureClient",
    "GenerationConfig",
    "LiveClient",
    "ModelClient",
    "OllamaClient",
    "OpenAIClient",
    "build_client",
]
