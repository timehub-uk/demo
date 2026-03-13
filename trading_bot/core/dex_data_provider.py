"""
DEX Data Provider – CoinGecko DEX API + Codex GraphQL integration.

Provides on-chain liquidity, OHLCV, and pool data to:
  • ML feature engineering (on-chain signals as training features)
  • Arbitrage detector (DEX vs CEX spread / cross-DEX opportunities)

Rate limiting
-------------
Free-tier monthly quotas are automatically split into per-hour budgets:
  - CoinGecko Demo: 10 000 calls/month → 10 000 / 30 / 24 ≈ 13 calls/hr
  - Codex free:     varies – defaults to 500 calls/month

The hourly budget is enforced by ApiRateLimiter; once exhausted the call
returns an empty result and logs a warning rather than blocking.

Usage
-----
    provider = DexDataProvider()
    if provider.coingecko_active:
        pools  = provider.get_top_pools("eth", limit=10)
        ohlcv  = provider.get_dex_ohlcv("0xpool…", days=1)
    if provider.codex_active:
        trades = provider.get_codex_recent_trades("0xtoken…")
        info   = provider.get_codex_token_info("0xtoken…")
"""

from __future__ import annotations

import calendar
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from typing import Any, Callable

from loguru import logger


# ══════════════════════════════════════════════════════════════════════════════
# API Rate Limiter
# ══════════════════════════════════════════════════════════════════════════════

# Free-tier monthly call quotas by plan
_COINGECKO_MONTHLY_QUOTAS: dict[str, int] = {
    "Demo (free)": 10_000,
    "Analyst":     500_000,
    "Lite":        500_000,
    "Pro":         1_000_000,
    "Enterprise":  10_000_000,
}
_CODEX_MONTHLY_QUOTA_FREE = 500   # conservative default for free Codex tier


class ApiRateLimiter:
    """
    Hourly token-bucket rate limiter derived from a monthly quota.

    Monthly quota is divided evenly across days and hours:
        hourly_budget = monthly_quota / days_in_month / 24

    Tokens replenish at the start of each UTC hour.  When the bucket
    is empty the call is refused (returns False from .acquire()).
    """

    def __init__(self, monthly_quota: int, name: str = "API") -> None:
        self._name    = name
        self._lock    = threading.Lock()
        self.set_monthly_quota(monthly_quota)

    def set_monthly_quota(self, monthly_quota: int) -> None:
        now   = datetime.utcnow()
        days  = calendar.monthrange(now.year, now.month)[1]
        self._hourly_budget = max(1, monthly_quota // (days * 24))
        with self._lock:
            self._tokens    = self._hourly_budget
            self._reset_at  = self._next_hour_ts()
        logger.debug(
            f"{self._name} rate limiter: {monthly_quota}/month "
            f"→ {self._hourly_budget}/hr"
        )

    @staticmethod
    def _next_hour_ts() -> float:
        now = time.time()
        return now + (3600 - now % 3600)

    def acquire(self) -> bool:
        """Try to consume one token.  Returns True if allowed, False if quota exhausted."""
        with self._lock:
            if time.time() >= self._reset_at:
                self._tokens   = self._hourly_budget
                self._reset_at = self._next_hour_ts()
            if self._tokens <= 0:
                logger.warning(
                    f"{self._name} hourly quota exhausted ({self._hourly_budget}/hr). "
                    f"Resets at {datetime.utcfromtimestamp(self._reset_at).strftime('%H:%M UTC')}"
                )
                return False
            self._tokens -= 1
            return True

    @property
    def tokens_remaining(self) -> int:
        with self._lock:
            if time.time() >= self._reset_at:
                return self._hourly_budget
            return max(0, self._tokens)

    @property
    def hourly_budget(self) -> int:
        return self._hourly_budget


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get(url: str, headers: dict[str, str], timeout: int = 10) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _post(url: str, payload: dict, headers: dict[str, str], timeout: int = 10) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


# ── Main class ────────────────────────────────────────────────────────────────

class DexDataProvider:
    """
    Unified DEX data client for CoinGecko DEX API and Codex GraphQL.

    Instantiate once and check .coingecko_active / .codex_active before calling
    the respective methods.  All methods return empty dicts/lists on failure so
    callers don't need to guard every call.
    """

    def __init__(self) -> None:
        self._cg_limiter  = ApiRateLimiter(_COINGECKO_MONTHLY_QUOTAS["Demo (free)"],
                                            "CoinGecko")
        self._cx_limiter  = ApiRateLimiter(_CODEX_MONTHLY_QUOTA_FREE, "Codex")
        self._reload_config()

    def _reload_config(self) -> None:
        try:
            from config import get_settings
            s = get_settings()
            cg = s.coingecko
            cx = s.codex
        except Exception:
            cg = cx = None

        # CoinGecko
        if cg and cg.enabled:
            self._cg_key     = cg.api_key.strip()
            self._cg_base    = cg.base_url.rstrip("/")
            self._cg_timeout = int(cg.timeout)
            self._cg_nets    = [n.strip() for n in cg.networks.split(",") if n.strip()]
            self.coingecko_active = True
            # Update quota based on plan
            monthly = _COINGECKO_MONTHLY_QUOTAS.get(cg.plan,
                       _COINGECKO_MONTHLY_QUOTAS["Demo (free)"])
            self._cg_limiter.set_monthly_quota(monthly)
        else:
            self.coingecko_active = False
            self._cg_key = self._cg_base = ""
            self._cg_timeout = 10
            self._cg_nets = []

        # Codex
        if cx and cx.enabled and cx.api_key.strip():
            self._cx_key     = cx.api_key.strip()
            self._cx_url     = cx.base_url.strip()
            self.codex_active = True
        else:
            self.codex_active = False
            self._cx_key = self._cx_url = ""

    @property
    def coingecko_quota_info(self) -> dict:
        """Returns hourly budget and remaining tokens for UI display."""
        return {
            "hourly_budget":    self._cg_limiter.hourly_budget,
            "tokens_remaining": self._cg_limiter.tokens_remaining,
        }

    @property
    def codex_quota_info(self) -> dict:
        return {
            "hourly_budget":    self._cx_limiter.hourly_budget,
            "tokens_remaining": self._cx_limiter.tokens_remaining,
        }

    # ── Internal HTTP helpers ─────────────────────────────────────────────────

    def _cg_headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Accept": "application/json"}
        if self._cg_key:
            h["x-cg-pro-api-key"] = self._cg_key
        return h

    def _cx_headers(self) -> dict[str, str]:
        return {"Authorization": self._cx_key, "Content-Type": "application/json"}

    def _cg_get(self, path: str, params: dict | None = None) -> dict | list:
        if not self._cg_limiter.acquire():
            return {}   # quota exhausted this hour
        url = f"{self._cg_base}/{path.lstrip('/')}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        try:
            return _get(url, self._cg_headers(), self._cg_timeout)
        except Exception as exc:
            logger.debug(f"CoinGecko GET {path} failed: {exc}")
            return {}

    def _cx_query(self, query: str, variables: dict | None = None) -> dict:
        if not self._cx_limiter.acquire():
            return {}   # quota exhausted this hour
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables
        try:
            return _post(self._cx_url, payload, self._cx_headers(), 15)
        except Exception as exc:
            logger.debug(f"Codex query failed: {exc}")
            return {}

    # ══════════════════════════════════════════════════════════════════════════
    # CoinGecko DEX API  —  https://www.coingecko.com/en/api/dex
    # ══════════════════════════════════════════════════════════════════════════

    def get_networks(self) -> list[dict]:
        """List all supported DEX networks."""
        result = self._cg_get("onchain/networks")
        return result.get("data", []) if isinstance(result, dict) else []

    def get_top_pools(self, network: str = "eth", limit: int = 20) -> list[dict]:
        """Return top liquidity pools on a network by volume."""
        result = self._cg_get(f"onchain/networks/{network}/trending_pools",
                              {"include": "base_token,quote_token", "page": 1})
        pools = result.get("data", []) if isinstance(result, dict) else []
        return pools[:limit]

    def get_pool_info(self, network: str, pool_address: str) -> dict:
        """Full pool info including reserve sizes, token prices, and 24h volume."""
        result = self._cg_get(
            f"onchain/networks/{network}/pools/{pool_address}",
            {"include": "base_token,quote_token,dex"}
        )
        return result.get("data", {}) if isinstance(result, dict) else {}

    def get_dex_ohlcv(
        self,
        network: str,
        pool_address: str,
        timeframe: str = "hour",
        aggregate: int = 1,
        limit: int = 100,
    ) -> list[dict]:
        """
        Fetch OHLCV candlestick data for a DEX pool.

        timeframe: "day" | "hour" | "minute"
        Returns list of dicts with keys: timestamp, open, high, low, close, volume
        """
        result = self._cg_get(
            f"onchain/networks/{network}/pools/{pool_address}/ohlcv/{timeframe}",
            {"aggregate": aggregate, "limit": limit, "currency": "usd"}
        )
        raw = result.get("data", {}).get("attributes", {}).get("ohlcv_list", []) \
              if isinstance(result, dict) else []
        return [
            {"timestamp": r[0], "open": r[1], "high": r[2],
             "low": r[3], "close": r[4], "volume": r[5]}
            for r in raw
        ]

    def get_token_pools(self, network: str, token_address: str,
                        limit: int = 10) -> list[dict]:
        """All pools containing a specific token on a network."""
        result = self._cg_get(
            f"onchain/networks/{network}/tokens/{token_address}/pools",
            {"page": 1}
        )
        return (result.get("data", []) if isinstance(result, dict) else [])[:limit]

    def get_recent_trades(self, network: str, pool_address: str,
                          limit: int = 50) -> list[dict]:
        """Recent on-chain trades for a pool."""
        result = self._cg_get(
            f"onchain/networks/{network}/pools/{pool_address}/trades",
        )
        return (result.get("data", []) if isinstance(result, dict) else [])[:limit]

    def get_global_dex_stats(self) -> dict:
        """Global DEX overview: total DEX volume, top protocols."""
        return self._cg_get("onchain/global")

    def get_trending_tokens(self, network: str = "eth") -> list[dict]:
        """Trending tokens on a network (by recent trade volume)."""
        result = self._cg_get(f"onchain/networks/{network}/trending_pools",
                               {"page": 1})
        return result.get("data", []) if isinstance(result, dict) else []

    # ══════════════════════════════════════════════════════════════════════════
    # Codex GraphQL API  —  https://www.codex.io
    # ══════════════════════════════════════════════════════════════════════════

    def get_codex_token_info(self, token_address: str, network_id: int = 1) -> dict:
        """On-chain token metadata: price, market cap, liquidity, holder count."""
        q = """
        query TokenInfo($address: String!, $networkId: Int!) {
          token(input: {address: $address, networkId: $networkId}) {
            address
            name
            symbol
            networkId
            info {
              circulatingSupply
              totalSupply
            }
          }
        }
        """
        data = self._cx_query(q, {"address": token_address, "networkId": network_id})
        return data.get("data", {}).get("token") or {}

    def get_codex_recent_trades(
        self,
        pair_address: str,
        network_id: int = 1,
        limit: int = 50,
    ) -> list[dict]:
        """Recent on-chain swap events for a pair."""
        q = """
        query RecentTrades($pairAddress: String!, $networkId: Int!, $limit: Int) {
          getTokenEvents(input: {
            address: $pairAddress,
            networkId: $networkId,
            limit: $limit
          }) {
            items {
              timestamp
              eventDisplayType
              priceUsd
              amountUsd
              transactionHash
            }
          }
        }
        """
        data = self._cx_query(q, {"pairAddress": pair_address,
                                   "networkId": network_id, "limit": limit})
        return data.get("data", {}).get("getTokenEvents", {}).get("items", [])

    def get_codex_pair_stats(self, pair_address: str, network_id: int = 1) -> dict:
        """24h stats for a trading pair: price, volume, buys, sells."""
        q = """
        query PairStats($pairAddress: String!, $networkId: Int!) {
          pairMetadata(pairAddress: $pairAddress, networkId: $networkId) {
            price
            volume24
            liquidity
            buyCount24
            sellCount24
            priceChange24
          }
        }
        """
        data = self._cx_query(q, {"pairAddress": pair_address, "networkId": network_id})
        return data.get("data", {}).get("pairMetadata") or {}

    def get_codex_ohlcv(
        self,
        pair_address: str,
        network_id: int = 1,
        resolution: str = "60",   # minutes as string
        from_ts: int | None = None,
        to_ts: int | None = None,
    ) -> list[dict]:
        """OHLCV bars from Codex for a DEX pair."""
        now = int(time.time())
        from_ts = from_ts or (now - 24 * 3600)
        to_ts   = to_ts   or now
        q = """
        query OHLCV($address: String!, $networkId: Int!,
                    $resolution: String!, $from: Int!, $to: Int!) {
          getBars(address: $address, networkId: $networkId,
                  resolution: $resolution, from: $from, to: $to,
                  countback: 200, removeLeadingNullValues: true) {
            t o h l c v
          }
        }
        """
        data = self._cx_query(q, {
            "address": pair_address, "networkId": network_id,
            "resolution": resolution, "from": from_ts, "to": to_ts,
        })
        raw = data.get("data", {}).get("getBars", {})
        if not raw or not raw.get("t"):
            return []
        return [
            {"timestamp": raw["t"][i], "open": raw["o"][i], "high": raw["h"][i],
             "low": raw["l"][i], "close": raw["c"][i], "volume": raw["v"][i]}
            for i in range(len(raw["t"]))
        ]

    # ══════════════════════════════════════════════════════════════════════════
    # Composite helpers for ML and Arbitrage
    # ══════════════════════════════════════════════════════════════════════════

    def get_dex_features_for_symbol(self, symbol: str) -> dict[str, float]:
        """
        Build a dict of on-chain features for a CEX symbol (e.g. "ETHUSDT").
        Used by ML feature engineering to enrich training data.

        Returns empty dict if no API is active.
        """
        features: dict[str, float] = {}

        base = symbol.replace("USDT", "").replace("USDC", "").replace("BUSD", "")
        network_map = {
            "ETH": ("eth", "weth"),
            "BNB": ("bsc", "wbnb"),
            "MATIC": ("polygon_pos", "wmatic"),
            "ARB": ("arbitrum", "arb"),
        }
        network, _ = network_map.get(base.upper(), ("eth", base.lower()))

        if self.coingecko_active:
            try:
                pools = self.get_top_pools(network, limit=5)
                if pools:
                    # aggregate top-pool liquidity and volume
                    total_vol = sum(
                        float(p.get("attributes", {}).get("volume_usd", {}).get("h24", 0) or 0)
                        for p in pools
                    )
                    total_liq = sum(
                        float(p.get("attributes", {}).get("reserve_in_usd", 0) or 0)
                        for p in pools
                    )
                    features["dex_volume_24h_usd"]    = total_vol
                    features["dex_liquidity_usd"]     = total_liq
                    features["dex_vol_liq_ratio"]     = total_vol / total_liq if total_liq else 0
                    features["dex_pool_count_top5"]   = float(len(pools))
            except Exception as exc:
                logger.debug(f"CoinGecko features for {symbol} failed: {exc}")

        if self.codex_active:
            try:
                # Use Codex pair stats for well-known pairs on Ethereum mainnet
                # In production, maintain a mapping from CEX symbol → Codex pair address
                pass   # Skipped without address mapping — see arbitrage DEX scan below
            except Exception:
                pass

        return features

    def scan_dex_arbitrage_opportunities(
        self,
        cached_pools: dict[str, list] | None = None,
    ) -> list[dict]:
        """
        Scan on-chain pools for DEX↔CEX price discrepancies.

        Parameters
        ----------
        cached_pools : dict, optional
            Pre-fetched pool lists keyed by network id, e.g.
            {"eth": [...], "bsc": [...]}.  When provided the method works
            entirely from cache — zero API calls consumed.  If a network is
            missing from the dict (or is empty) the scheduler's budget is used
            to fetch it on demand.

        Returns list of opportunity dicts:
        {
            "type": "dex_cex_spread",
            "symbol": "ETHUSDT",
            "cex_price": 2500.0,
            "dex_price": 2510.0,
            "spread_pct": 0.4,
            "network": "eth",
            "pool_address": "0x...",
            "liquidity_usd": 1_000_000,
            "confidence": 0.7,
        }
        """
        opportunities: list[dict] = []

        if not self.coingecko_active:
            return opportunities

        cached_pools = cached_pools or {}

        for network in self._cg_nets[:4]:   # up to 4 networks
            try:
                # Prefer cached data (free); fall back to live call only if cache empty
                pools = cached_pools.get(network) or self.get_top_pools(network, limit=15)
                for pool in pools:
                    attrs  = pool.get("attributes", {})
                    base   = pool.get("relationships", {}).get("base_token", {})
                    name   = attrs.get("name", "")
                    price_usd   = float(attrs.get("base_token_price_usd", 0) or 0)
                    liq_usd     = float(attrs.get("reserve_in_usd", 0) or 0)
                    vol_24h     = float(attrs.get("volume_usd", {}).get("h24", 0) or 0)
                    pool_addr   = attrs.get("address", "")

                    if price_usd <= 0 or liq_usd < 50_000:
                        continue

                    # Identify CEX symbol from pool name (e.g. "WETH / USDC" → ETHUSDT)
                    cex_symbol = _pool_name_to_cex_symbol(name)
                    if not cex_symbol:
                        continue

                    # Fetch CEX mid price (best-effort via Binance ticker)
                    cex_price = _fetch_binance_price(cex_symbol)
                    if not cex_price:
                        continue

                    spread_pct = abs(cex_price - price_usd) / cex_price * 100
                    if spread_pct < 0.15:
                        continue   # Too small to trade after fees

                    confidence = min(0.9, 0.4 + (liq_usd / 1_000_000) * 0.1
                                         + (vol_24h / 500_000) * 0.1
                                         + min(spread_pct / 2, 0.3))

                    opportunities.append({
                        "type":         "dex_cex_spread",
                        "symbol":       cex_symbol,
                        "network":      network,
                        "pool_address": pool_addr,
                        "cex_price":    cex_price,
                        "dex_price":    price_usd,
                        "spread_pct":   round(spread_pct, 4),
                        "liquidity_usd": liq_usd,
                        "volume_24h_usd": vol_24h,
                        "confidence":   round(confidence, 3),
                        "source":       "coingecko_dex",
                    })
            except Exception as exc:
                logger.debug(f"DEX arb scan on {network} failed: {exc}")

        # Sort by spread descending
        opportunities.sort(key=lambda x: x["spread_pct"], reverse=True)
        return opportunities


# ── Utility functions ─────────────────────────────────────────────────────────

_POOL_SYMBOL_MAP: dict[str, str] = {
    "WETH": "ETH", "WBTC": "BTC", "WBNB": "BNB",
    "WMATIC": "MATIC", "WAVAX": "AVAX",
}
_STABLES = {"USDT", "USDC", "BUSD", "DAI", "FRAX", "TUSD", "USDP", "FDUSD"}


def _pool_name_to_cex_symbol(pool_name: str) -> str:
    """Convert e.g. 'WETH / USDC' → 'ETHUSDT', or '' if unrecognised."""
    parts = [p.strip().upper() for p in pool_name.replace("-", "/").split("/")]
    if len(parts) != 2:
        return ""
    a, b = parts
    a = _POOL_SYMBOL_MAP.get(a, a)
    b = _POOL_SYMBOL_MAP.get(b, b)
    if b in _STABLES:
        return f"{a}USDT"
    if a in _STABLES:
        return f"{b}USDT"
    return ""


_price_cache: dict[str, tuple[float, float]] = {}   # symbol → (price, ts)
_PRICE_CACHE_TTL = 30  # seconds


def _fetch_binance_price(symbol: str) -> float:
    """Lightweight Binance ticker price fetch with 30 s cache."""
    cached = _price_cache.get(symbol)
    if cached and time.time() - cached[1] < _PRICE_CACHE_TTL:
        return cached[0]
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        data = _get(url, {}, timeout=5)
        price = float(data.get("price", 0))
        if price:
            _price_cache[symbol] = (price, time.time())
        return price
    except Exception:
        return 0.0


# ══════════════════════════════════════════════════════════════════════════════
# DEX Call Scheduler
# ══════════════════════════════════════════════════════════════════════════════
#
# Budget strategy for CoinGecko Demo (≈13 calls/hr):
#
#   12 scheduled slots  — evenly spaced at 5-minute intervals.
#                         Each slot calls the highest-density endpoint available
#                         (list endpoints > single-item calls).
#    1 emergency slot   — reserved; only consumed when a live arbitrage signal
#                         needs an immediate deep-dive on a specific pool.
#
# Slot priority tiers:
#   ★★★  List endpoints (top_pools, trending_tokens)  — 1 call → 20+ data pts
#   ★★   Time-series (dex_ohlcv)                      — 1 call → 100 OHLCV bars
#   ★    Single-item (pool_info, recent_trades)        — 1 call → 1 data point
#
# 12-slot hourly schedule:
#   min  0  get_top_pools(eth)           ★★★  most liquid, highest arb probability
#   min  5  get_top_pools(bsc)           ★★★  second-largest DEX ecosystem
#   min 10  get_trending_tokens(eth)     ★★★  spot momentum before it hits CEX
#   min 15  get_top_pools(arbitrum)      ★★★  L2 — often leads CEX price moves
#   min 20  get_dex_ohlcv(top_eth_pool) ★★   ML training: ETH price action
#   min 25  get_recent_trades(top_pool) ★    real-time on-chain signal window 1
#   min 30  get_top_pools(eth)           ★★★  30-min refresh (critical ETH repeat)
#   min 35  get_trending_tokens(bsc)     ★★★  cross-chain trend detection
#   min 40  get_dex_ohlcv(top_bsc_pool) ★★   ML training: BSC price action
#   min 45  get_recent_trades(top_pool) ★    real-time on-chain signal window 2
#   min 50  get_top_pools(polygon_pos)   ★★★  L2 coverage for unique arb
#   min 55  get_global_dex_stats()       ★★   hour-end context for ML features
#
#   + emergency reserve → triggered by arbitrage detector → get_pool_info()
#
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ScheduledCall:
    """One slot in the hourly call plan."""
    minute_offset: int          # Minute within the hour when this fires (0-59)
    label: str                  # Human-readable description
    priority: int               # 3=list ★★★, 2=series ★★, 1=single ★
    fn_name: str                # DexDataProvider method name
    fn_args: tuple = dc_field(default_factory=tuple)
    fn_kwargs: dict = dc_field(default_factory=dict)
    cache_key: str = ""         # Key under which to store the result
    cache_ttl: int = 360        # Result TTL in seconds (default 6 min)


# The 12-slot hourly plan (minute offsets within each hour)
_HOURLY_PLAN: list[ScheduledCall] = [
    ScheduledCall( 0, "ETH top pools (1st pass)",  3, "get_top_pools",
                   ("eth",), {"limit": 20}, "top_pools_eth",  360),
    ScheduledCall( 5, "BSC top pools",             3, "get_top_pools",
                   ("bsc",), {"limit": 20}, "top_pools_bsc",  360),
    ScheduledCall(10, "ETH trending tokens",       3, "get_trending_tokens",
                   ("eth",), {},            "trending_eth",    360),
    ScheduledCall(15, "Arbitrum top pools",        3, "get_top_pools",
                   ("arbitrum",), {"limit": 20}, "top_pools_arb", 360),
    ScheduledCall(20, "ETH top-pool OHLCV",        2, "get_dex_ohlcv",
                   ("eth", "__top_eth_pool__",), {},  "ohlcv_eth",  600),
    ScheduledCall(25, "Top-pool recent trades",    1, "get_recent_trades",
                   ("eth", "__top_eth_pool__",), {}, "trades_eth",  300),
    ScheduledCall(30, "ETH top pools (30-min refresh)", 3, "get_top_pools",
                   ("eth",), {"limit": 20}, "top_pools_eth",  360),
    ScheduledCall(35, "BSC trending tokens",       3, "get_trending_tokens",
                   ("bsc",), {},            "trending_bsc",    360),
    ScheduledCall(40, "BSC top-pool OHLCV",        2, "get_dex_ohlcv",
                   ("bsc", "__top_bsc_pool__",), {}, "ohlcv_bsc",  600),
    ScheduledCall(45, "Top-pool recent trades (2nd)", 1, "get_recent_trades",
                   ("eth", "__top_eth_pool__",), {}, "trades_eth2", 300),
    ScheduledCall(50, "Polygon top pools",         3, "get_top_pools",
                   ("polygon_pos",), {"limit": 20}, "top_pools_poly", 360),
    ScheduledCall(55, "Global DEX stats",          2, "get_global_dex_stats",
                   (), {},                 "global_dex_stats", 3600),
]


class DexCallScheduler:
    """
    Executes the 12-slot hourly call plan against a DexDataProvider, caches
    results, and reserves the 13th slot as an emergency budget for ad-hoc
    high-priority lookups (e.g. deep-dive on an arbitrage opportunity).

    All scheduled calls run in a background daemon thread.
    Call results are stored in self.cache[key] and remain valid for cache_ttl
    seconds — consumers should always read from cache, not call APIs directly.

    Usage
    -----
        sched = DexCallScheduler(provider)
        sched.start()

        # Read cached data (always safe, never blocks):
        pools = sched.get("top_pools_eth", default=[])

        # Trigger emergency deep-dive (uses the reserved 13th slot):
        sched.emergency_call("get_pool_info", ("eth", "0xpool..."),
                              cache_key="arb_pool_info")
    """

    def __init__(self, provider: "DexDataProvider") -> None:
        self._provider     = provider
        self._cache: dict[str, tuple[Any, float]] = {}   # key → (value, expires_at)
        self._lock         = threading.Lock()
        self._running      = False
        self._thread: threading.Thread | None = None
        # Track which slots have fired this hour
        self._last_fired: dict[int, float] = {}   # minute_offset → last fired ts
        # Emergency call queue
        self._emergency_queue: list[tuple[str, tuple, dict, str]] = []
        self._emergency_used_this_hour = 0

    # ── Cache access ──────────────────────────────────────────────────────────

    def get(self, key: str, default=None) -> Any:
        """Return cached value if still valid, else default."""
        with self._lock:
            entry = self._cache.get(key)
            if entry and time.time() < entry[1]:
                return entry[0]
        return default

    def _store(self, key: str, value: Any, ttl: int) -> None:
        with self._lock:
            self._cache[key] = (value, time.time() + ttl)

    def cache_snapshot(self) -> dict[str, dict]:
        """Return metadata about all cache entries (for status display)."""
        now = time.time()
        snap = {}
        with self._lock:
            for k, (v, exp) in self._cache.items():
                snap[k] = {
                    "valid":    exp > now,
                    "expires_in": max(0, int(exp - now)),
                    "has_data": bool(v),
                }
        return snap

    # ── Scheduler control ─────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="dex-scheduler"
        )
        self._thread.start()
        logger.info("DexCallScheduler started — 12 slots/hr + 1 emergency reserve")

    def stop(self) -> None:
        self._running = False

    # ── Emergency reserve ─────────────────────────────────────────────────────

    def emergency_call(
        self,
        fn_name: str,
        args: tuple = (),
        kwargs: dict | None = None,
        cache_key: str = "_emergency",
        ttl: int = 300,
    ) -> bool:
        """
        Request an immediate out-of-schedule API call using the reserved 13th
        token.  Returns True if the call was queued, False if this hour's
        emergency slot is already spent.
        """
        # Reset counter at the top of each hour
        if time.time() >= self._provider._cg_limiter._reset_at:
            self._emergency_used_this_hour = 0

        if self._emergency_used_this_hour >= 1:
            logger.warning(
                "DexCallScheduler: emergency reserve already used this hour — "
                "queued call deferred to next hour"
            )
            return False
        with self._lock:
            self._emergency_queue.append((fn_name, args, kwargs or {}, cache_key, ttl))
        logger.info(f"DexCallScheduler: emergency call queued → {fn_name}{args}")
        return True

    # ── Background loop ───────────────────────────────────────────────────────

    def _loop(self) -> None:
        while self._running:
            now    = time.time()
            minute = int((now % 3600) // 60)   # minute within current hour

            # Fire any scheduled slots that are due
            for slot in _HOURLY_PLAN:
                # Fire if we're within ±30s of the target minute and haven't
                # fired this slot in the last 4 minutes (avoid double-firing)
                delta = minute - slot.minute_offset
                last  = self._last_fired.get(slot.minute_offset, 0)
                if abs(delta) <= 0 and now - last > 240:
                    self._fire_slot(slot)
                    self._last_fired[slot.minute_offset] = now

            # Process emergency queue
            with self._lock:
                pending = self._emergency_queue[:]
                self._emergency_queue.clear()

            for fn_name, args, kwargs, cache_key, ttl in pending:
                self._fire_emergency(fn_name, args, kwargs, cache_key, ttl)

            time.sleep(30)   # check every 30 s for slot alignment

    def _fire_slot(self, slot: ScheduledCall) -> None:
        """Execute one scheduled slot, resolving dynamic pool address tokens."""
        try:
            args = self._resolve_args(slot.fn_args)
            if args is None:
                return   # dynamic arg not yet available — skip this slot
            fn = getattr(self._provider, slot.fn_name)
            result = fn(*args, **slot.fn_kwargs)
            if result:
                self._store(slot.cache_key, result, slot.cache_ttl)
                logger.debug(
                    f"DexCallScheduler ✓ [{slot.priority}★] {slot.label} "
                    f"→ {slot.cache_key} ({_result_size(result)} items)"
                )
            else:
                logger.debug(f"DexCallScheduler — {slot.label}: empty result")
        except Exception as exc:
            logger.debug(f"DexCallScheduler slot '{slot.label}' error: {exc}")

    def _fire_emergency(
        self, fn_name: str, args: tuple, kwargs: dict,
        cache_key: str, ttl: int
    ) -> None:
        try:
            fn = getattr(self._provider, fn_name)
            result = fn(*args, **kwargs)
            if result:
                self._store(cache_key, result, ttl)
            self._emergency_used_this_hour += 1
            logger.info(
                f"DexCallScheduler ★ emergency {fn_name}({args!r}) → {cache_key}"
            )
        except Exception as exc:
            logger.warning(f"DexCallScheduler emergency call error: {exc}")

    def _resolve_args(self, args: tuple) -> tuple | None:
        """
        Replace __top_eth_pool__ / __top_bsc_pool__ tokens with the actual
        best pool address from the cache.  Returns None if not yet available.
        """
        resolved = []
        for arg in args:
            if arg == "__top_eth_pool__":
                addr = self._best_pool_address("top_pools_eth")
                if not addr:
                    return None
                resolved.append(addr)
            elif arg == "__top_bsc_pool__":
                addr = self._best_pool_address("top_pools_bsc")
                if not addr:
                    return None
                resolved.append(addr)
            else:
                resolved.append(arg)
        return tuple(resolved)

    def _best_pool_address(self, cache_key: str) -> str:
        """Return the pool address with the highest 24h volume from a cached pool list."""
        pools = self.get(cache_key, [])
        if not pools:
            return ""
        best = max(
            pools,
            key=lambda p: float(
                p.get("attributes", {}).get("volume_usd", {}).get("h24", 0) or 0
            ),
            default=None,
        )
        return best.get("attributes", {}).get("address", "") if best else ""

    # ── Public status info ────────────────────────────────────────────────────

    @property
    def schedule_summary(self) -> list[dict]:
        """Return the 12-slot plan with last-fired times — for UI display."""
        now = time.time()
        rows = []
        for slot in _HOURLY_PLAN:
            last = self._last_fired.get(slot.minute_offset, 0)
            cache_valid = False
            with self._lock:
                entry = self._cache.get(slot.cache_key)
                if entry:
                    cache_valid = now < entry[1]
            rows.append({
                "minute":     slot.minute_offset,
                "label":      slot.label,
                "priority":   slot.priority,
                "last_fired": int(now - last) if last else None,
                "cache_valid": cache_valid,
                "cache_key":  slot.cache_key,
            })
        return rows

    @property
    def emergency_available(self) -> bool:
        return self._emergency_used_this_hour < 1


def _result_size(v: Any) -> int:
    if isinstance(v, (list, dict)):
        return len(v)
    return 1


# ── Singleton accessor ────────────────────────────────────────────────────────

_provider: DexDataProvider | None = None
_scheduler: DexCallScheduler | None = None


def get_dex_provider() -> DexDataProvider:
    """Return (or create) the global DexDataProvider singleton."""
    global _provider
    if _provider is None:
        _provider = DexDataProvider()
    return _provider


def get_dex_scheduler() -> DexCallScheduler:
    """Return (or create) the global DexCallScheduler — starts it if needed."""
    global _scheduler
    if _scheduler is None:
        _scheduler = DexCallScheduler(get_dex_provider())
        _scheduler.start()
    return _scheduler


def reload_dex_provider() -> DexDataProvider:
    """Re-read config and reset the singleton — call after settings save."""
    global _provider, _scheduler
    if _provider is not None:
        _provider._reload_config()
    else:
        _provider = DexDataProvider()
    # Restart scheduler with updated provider config
    if _scheduler is not None:
        _scheduler._provider = _provider
    return _provider
