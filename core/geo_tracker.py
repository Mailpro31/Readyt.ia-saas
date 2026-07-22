"""GEO / AEO — AI citation tracking (Phase 1.2).

Periodically asks each configured AI provider a set of probe queries
(e.g. "best speech to text app for windows") and records whether the promoted
product (Nova / novaspeak.app) is mentioned in the answer.

⚠️  Unlike the rest of MiloAgent, this module makes PAID API calls. Budget is
documented in the README. All calls are plain HTTPS via ``requests`` so no
provider SDKs are required.

Supports a ``dry_run`` mode used by the smoke-test: it runs one provider / one
query and returns the raw parsed result without persisting.
"""

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 45


@dataclass
class ProbeResult:
    provider: str
    query: str
    cited: bool
    snippet: str = ""
    position_estimate: int = -1
    raw_text: str = ""
    error: str = field(default="")


def detect_citation(
    text: str, brand_terms: List[str],
) -> "tuple[bool, str, int]":
    """Detect whether any brand term is cited in ``text``.

    Returns ``(cited, snippet, position_estimate)`` where position_estimate is
    the 1-based sentence index of the first mention (or -1).

    Matching rules (tuned to avoid false positives, per Phase 1.3 tests):
    - "novaspeak" / "novaspeak.app" always count (unambiguous domain).
    - The bare word "Nova" counts only as a whole word, and NOT when it is
      immediately followed by a token that marks a *different* product
      (e.g. "Nova Launcher", "Nova Scotia", "Nova by Bose").
    """
    if not text:
        return False, "", -1
    lowered = text.lower()

    # Unambiguous domain / brand slug.
    domain_hit = "novaspeak" in lowered

    # Whole-word "nova", excluding known other-product qualifiers.
    disqualifiers = {
        "launcher", "scotia", "school", "science", "3", "skin",
        "energy", "credit", "chemicals", "bank",
    }
    word_hit = False
    for m in re.finditer(r"\bnova\b", lowered):
        after = lowered[m.end():m.end() + 20].strip()
        next_word = after.split()[0].strip(".,:;)!?") if after else ""
        if next_word in disqualifiers:
            continue
        word_hit = True
        break

    # Any explicitly configured extra term (e.g. "novaspeak.app").
    extra_hit = False
    for term in brand_terms or []:
        t = term.lower().strip()
        if not t or t in ("nova", "novaspeak"):
            continue
        if t in lowered:
            extra_hit = True
            break

    cited = domain_hit or word_hit or extra_hit
    if not cited:
        return False, "", -1

    # Build snippet + position estimate from the first matching sentence.
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for idx, sent in enumerate(sentences, start=1):
        sl = sent.lower()
        if "novaspeak" in sl or re.search(r"\bnova\b", sl):
            snippet = sent.strip()[:300]
            return True, snippet, idx
    return True, text.strip()[:300], 1


class GeoTracker:
    """Runs probe queries against AI providers and records citations."""

    def __init__(self, db, config: Optional[dict] = None):
        self.db = db
        self.config = config or {}

    # ── Config ─────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("geo", {}).get("enabled", False))

    def _providers(self) -> List[dict]:
        return self.config.get("geo", {}).get("providers", [])

    def _queries_for(self, project: str) -> List[str]:
        return self.config.get("geo", {}).get("projects", {}).get(project, [])

    @staticmethod
    def _resolve_key(provider: dict) -> str:
        env_name = provider.get("api_key_env", "")
        return (
            provider.get("api_key", "")
            or (os.environ.get(env_name, "") if env_name else "")
        )

    # ── Provider calls ─────────────────────────────────────────────

    def query_provider(self, provider: dict, query: str) -> str:
        """Send one probe query to one provider; returns the answer text.

        Raises on transport/auth error so the caller can record it.
        """
        name = provider.get("name", "").lower()
        key = self._resolve_key(provider)
        model = provider.get("model", "")
        if not key:
            raise RuntimeError(f"No API key for provider '{name}'")

        if name in ("openai", "perplexity"):
            return self._chat_openai_compatible(name, key, model, query)
        if name == "anthropic":
            return self._chat_anthropic(key, model, query)
        if name == "google":
            return self._chat_google(key, model, query)
        raise RuntimeError(f"Unknown provider '{name}'")

    def _chat_openai_compatible(
        self, name: str, key: str, model: str, query: str,
    ) -> str:
        base = (
            "https://api.perplexity.ai"
            if name == "perplexity"
            else "https://api.openai.com/v1"
        )
        resp = requests.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": query}],
                "temperature": 0.2,
            },
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def _chat_anthropic(self, key: str, model: str, query: str) -> str:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": query}],
            },
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        parts = resp.json().get("content", [])
        return "".join(p.get("text", "") for p in parts)

    def _chat_google(self, key: str, model: str, query: str) -> str:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={key}"
        )
        resp = requests.post(
            url,
            json={"contents": [{"parts": [{"text": query}]}]},
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        cands = resp.json().get("candidates", [])
        if not cands:
            return ""
        parts = cands[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts)

    # ── Probe orchestration ────────────────────────────────────────

    def probe(
        self, provider: dict, query: str, brand_terms: List[str],
    ) -> ProbeResult:
        name = provider.get("name", "?")
        try:
            text = self.query_provider(provider, query)
        except Exception as e:
            logger.error("GEO probe failed (%s / %r): %s", name, query, e)
            return ProbeResult(provider=name, query=query, cited=False,
                               error=str(e))
        cited, snippet, pos = detect_citation(text, brand_terms)
        logger.info(
            "GEO probe [%s] %r -> cited=%s pos=%s", name, query, cited, pos
        )
        return ProbeResult(
            provider=name, query=query, cited=cited, snippet=snippet,
            position_estimate=pos, raw_text=text,
        )

    def run(
        self, project: str, brand_terms: List[str],
        dry_run: bool = False, single: bool = False,
    ) -> List[ProbeResult]:
        """Run all enabled probes for a project.

        Args:
            dry_run: do not persist results (used by smoke-test).
            single: run only the first enabled provider + first query.
        """
        results: List[ProbeResult] = []
        queries = self._queries_for(project)
        providers = [p for p in self._providers() if p.get("enabled", True)]
        if single:
            providers = providers[:1]
            queries = queries[:1]
        if not providers or not queries:
            logger.warning(
                "GEO run: nothing to do (providers=%d queries=%d) for %s",
                len(providers), len(queries), project,
            )
            return results

        for provider in providers:
            for query in queries:
                res = self.probe(provider, query, brand_terms)
                results.append(res)
                if not dry_run and not res.error:
                    self.db.insert_geo_citation(
                        project=project, provider=res.provider,
                        query=res.query, cited=res.cited,
                        snippet=res.snippet,
                        position_estimate=res.position_estimate,
                    )
        logger.info(
            "GEO run complete for %s: %d probes, %d citations (dry_run=%s)",
            project, len(results), sum(1 for r in results if r.cited), dry_run,
        )
        return results
