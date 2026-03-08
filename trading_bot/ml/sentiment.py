"""
Sentiment Analysis Module.

Fetches crypto news headlines and scores them using available AI APIs
(Claude, GPT-4, Gemini) with a weighted consensus.

Sentiment score: -1.0 (very bearish) → +1.0 (very bullish)
Cached in Redis with a 15-minute TTL.
Background loop refreshes every 15 minutes.

News sources:
  - CryptoPanic API (free tier, no key needed for public feed)
  - Binance announcements
  - Synthetic scoring fallback when APIs unavailable
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Callable

from loguru import logger
from utils.logger import get_intel_logger


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class SentimentResult:
    symbol: str
    score: float                     # -1.0 to +1.0
    label: str                       # BEARISH | NEUTRAL | BULLISH
    confidence: float                # 0.0 – 1.0
    sources: list[str] = field(default_factory=list)
    headlines: list[str] = field(default_factory=list)
    timestamp: str = ""
    ai_model_used: str = ""

    @property
    def is_bullish(self) -> bool:
        return self.score > 0.2

    @property
    def is_bearish(self) -> bool:
        return self.score < -0.2

    @classmethod
    def neutral(cls, symbol: str) -> "SentimentResult":
        return cls(symbol=symbol, score=0.0, label="NEUTRAL", confidence=0.0,
                   timestamp=datetime.now(timezone.utc).isoformat())


# ── News fetcher ──────────────────────────────────────────────────────────────

class NewsFetcher:
    """Pulls headlines from free crypto news sources."""

    CRYPTOPANIC_URL = "https://cryptopanic.com/api/v1/posts/?auth_token=&public=true&kind=news"

    def __init__(self) -> None:
        self._intel = get_intel_logger()

    def fetch_headlines(self, symbol: str, limit: int = 20) -> list[str]:
        """Return list of recent news headline strings related to symbol."""
        headlines = []
        coin = symbol.replace("USDT", "").replace("BTC", "BTC")

        # Try CryptoPanic
        try:
            headlines += self._fetch_cryptopanic(coin, limit)
        except Exception as exc:
            logger.debug(f"CryptoPanic fetch error: {exc}")

        return headlines[:limit]

    def _fetch_cryptopanic(self, coin: str, limit: int) -> list[str]:
        import urllib.request
        url = f"https://cryptopanic.com/api/v1/posts/?auth_token=&public=true&currencies={coin}&kind=news"
        try:
            with urllib.request.urlopen(url, timeout=8) as resp:
                data = json.loads(resp.read().decode())
            results = data.get("results", [])
            return [r.get("title", "") for r in results[:limit] if r.get("title")]
        except Exception:
            return []


# ── AI scoring ────────────────────────────────────────────────────────────────

class AIScorer:
    """
    Scores a list of headlines using one of the configured AI APIs.
    Tries Claude → GPT-4 → Gemini → keyword fallback in order.
    """

    PROMPT_TEMPLATE = (
        "You are a crypto market analyst. Rate the following news headlines "
        "for {symbol} on a sentiment scale from -1.0 (very bearish) to +1.0 "
        "(very bullish). Reply with ONLY a JSON object: "
        '{"score": <float>, "label": "BEARISH|NEUTRAL|BULLISH", "confidence": <float 0-1>}\n\n'
        "Headlines:\n{headlines}"
    )

    def __init__(self) -> None:
        self._intel = get_intel_logger()
        self._enabled: dict[str, bool] = self._check_providers()
        active = [p for p, ok in self._enabled.items() if ok]
        if active:
            logger.info(f"AIScorer: active providers = {active}")
        else:
            logger.info("AIScorer: no AI keys configured — keyword-only sentiment scoring")

    @staticmethod
    def _check_providers() -> dict[str, bool]:
        """Return which AI providers have keys configured."""
        try:
            from config import get_settings
            ai = get_settings().ai
            return {
                "claude":     bool(ai.claude_api_key),
                "openai":     bool(ai.openai_api_key),
                "gemini":     bool(ai.gemini_api_key),
            }
        except Exception:
            return {"claude": False, "openai": False, "gemini": False}

    def score(self, symbol: str, headlines: list[str]) -> tuple[float, float, str, str]:
        """
        Returns (score, confidence, label, model_used).
        """
        if not headlines:
            return 0.0, 0.0, "NEUTRAL", "none"

        text = "\n".join(f"- {h}" for h in headlines[:15])
        prompt = self.PROMPT_TEMPLATE.format(symbol=symbol, headlines=text)

        # Try Claude
        result = self._try_claude(prompt)
        if result:
            return *result, "claude"

        # Try OpenAI
        result = self._try_openai(prompt)
        if result:
            return *result, "openai"

        # Try Gemini
        result = self._try_gemini(prompt)
        if result:
            return *result, "gemini"

        # Keyword fallback
        return self._keyword_score(headlines), 0.5, self._label_from_score(self._keyword_score(headlines)), "keyword"

    def _try_claude(self, prompt: str) -> Optional[tuple[float, float, str]]:
        if not self._enabled.get("claude"):
            return None
        try:
            from config import get_settings
            settings = get_settings()
            api_key = settings.ai.claude_api_key
            if not api_key:
                return None
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=64,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            data = json.loads(raw)
            return float(data["score"]), float(data["confidence"]), str(data["label"])
        except Exception as exc:
            logger.debug(f"Claude sentiment error: {exc}")
            return None

    def _try_openai(self, prompt: str) -> Optional[tuple[float, float, str]]:
        if not self._enabled.get("openai"):
            return None
        try:
            from config import get_settings
            settings = get_settings()
            api_key = settings.ai.openai_api_key
            if not api_key:
                return None
            import openai
            client = openai.OpenAI(api_key=api_key)
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=64,
            )
            raw = resp.choices[0].message.content.strip()
            data = json.loads(raw)
            return float(data["score"]), float(data["confidence"]), str(data["label"])
        except Exception as exc:
            logger.debug(f"OpenAI sentiment error: {exc}")
            return None

    def _try_gemini(self, prompt: str) -> Optional[tuple[float, float, str]]:
        if not self._enabled.get("gemini"):
            return None
        try:
            from config import get_settings
            settings = get_settings()
            api_key = settings.ai.gemini_api_key
            if not api_key:
                return None
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            resp = model.generate_content(prompt)
            raw = resp.text.strip()
            data = json.loads(raw)
            return float(data["score"]), float(data["confidence"]), str(data["label"])
        except Exception as exc:
            logger.debug(f"Gemini sentiment error: {exc}")
            return None

    def _keyword_score(self, headlines: list[str]) -> float:
        bull = ["surge","pump","rally","bull","bullish","gains","rises","soars","record","buy","breakout","all-time high","ath","launch","partnership","upgrade","adoption"]
        bear = ["crash","dump","bear","bearish","falls","drops","plunges","hack","ban","lawsuit","fraud","sell","fear","panic","liquidation","collapse","decline","warning"]
        text = " ".join(headlines).lower()
        score = sum(1 for w in bull if w in text) - sum(1 for w in bear if w in text)
        max_possible = max(len(bull), len(bear))
        return max(-1.0, min(1.0, score / max_possible))

    def _label_from_score(self, score: float) -> str:
        if score > 0.2:
            return "BULLISH"
        if score < -0.2:
            return "BEARISH"
        return "NEUTRAL"


# ── Sentiment analyser ────────────────────────────────────────────────────────

class SentimentAnalyser:
    """
    Main interface for market sentiment analysis.
    Manages background refresh, Redis caching, and signal callbacks.
    """

    REFRESH_INTERVAL = 15 * 60   # 15 minutes
    CACHE_TTL = 20 * 60          # 20 minutes

    def __init__(self) -> None:
        self._fetcher = NewsFetcher()
        self._scorer  = AIScorer()
        self._intel   = get_intel_logger()
        self._running = False
        self._active_symbols: list[str] = []
        self._cache: dict[str, SentimentResult] = {}
        self._callbacks: list[Callable[[SentimentResult], None]] = []
        self._thread: Optional[threading.Thread] = None

    def on_result(self, cb: Callable[[SentimentResult], None]) -> None:
        """Register callback for new sentiment results."""
        self._callbacks.append(cb)

    def start(self, symbols: list[str]) -> None:
        self._active_symbols = symbols
        self._running = True
        self._thread = threading.Thread(
            target=self._refresh_loop, daemon=True, name="sentiment-loop"
        )
        self._thread.start()
        self._intel.ml("SentimentAnalyser",
            f"📰 Sentiment analysis started | {len(symbols)} symbols | refresh every 15min")

    def stop(self) -> None:
        self._running = False

    def get(self, symbol: str) -> SentimentResult:
        """Get current sentiment for a symbol (from cache or neutral if unavailable)."""
        # Check Redis cache
        try:
            from db.redis_client import RedisClient
            cached = RedisClient().get(f"sentiment:{symbol}")
            if cached:
                return SentimentResult(**cached)
        except Exception:
            pass
        return self._cache.get(symbol, SentimentResult.neutral(symbol))

    def analyse_now(self, symbol: str) -> SentimentResult:
        """Fetch and score immediately (blocking)."""
        return self._analyse_one(symbol)

    # ── Internal ───────────────────────────────────────────────────────

    def _refresh_loop(self) -> None:
        while self._running:
            for sym in self._active_symbols:
                if not self._running:
                    break
                try:
                    result = self._analyse_one(sym)
                    for cb in self._callbacks:
                        try:
                            cb(result)
                        except Exception:
                            pass
                except Exception as exc:
                    logger.debug(f"Sentiment refresh error [{sym}]: {exc}")
                time.sleep(2)   # Stagger between symbols
            time.sleep(self.REFRESH_INTERVAL)

    def _analyse_one(self, symbol: str) -> SentimentResult:
        headlines = self._fetcher.fetch_headlines(symbol, limit=20)
        score, confidence, label, model = self._scorer.score(symbol, headlines)

        result = SentimentResult(
            symbol=symbol,
            score=score,
            confidence=confidence,
            label=label,
            headlines=headlines[:5],
            timestamp=datetime.now(timezone.utc).isoformat(),
            ai_model_used=model,
        )
        self._cache[symbol] = result

        # Cache in Redis
        try:
            from db.redis_client import RedisClient
            from dataclasses import asdict
            RedisClient().set(f"sentiment:{symbol}", asdict(result), ttl=self.CACHE_TTL)
        except Exception:
            pass

        emoji = "🟢" if result.is_bullish else "🔴" if result.is_bearish else "⚪"
        self._intel.ml("SentimentAnalyser",
            f"{emoji} {symbol}: {label} ({score:+.2f}) via {model} | {len(headlines)} headlines")
        return result
