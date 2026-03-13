"""
0x Protocol API integration.

Provides DEX swap price discovery and optimal routing across all major DEXs
(Uniswap, Curve, Balancer, SushiSwap, etc.) via the 0x Swap API.

Pricing: https://0x.org/pricing
  • Free account  : API key required (create at https://dashboard.0x.org)
                    Rate limit: ~1 req/s (conservative)
  • Standard      : $1,000/month — 5 req/s
  • Custom        : $2,500+/month — higher volume

API v2 base URL : https://api.0x.org
Key header      : 0x-api-key: <your_key>
Chain header    : 0x-chain-id: <chain_id>

Supported chains:
  1      Ethereum mainnet
  56     BNB Smart Chain
  137    Polygon
  42161  Arbitrum One
  10     Optimism
  8453   Base

Key endpoints:
  GET /swap/permit2/price   — indicative price (no signature required, cheaper)
  GET /swap/permit2/quote   — firm executable quote (more expensive, use sparingly)
  GET /swap/v1/sources      — list of available liquidity sources

Usage
-----
    zx = ZeroXProvider()
    if zx.active:
        price = zx.get_price("USDC", "ETH", sell_amount_usd=100)
        # → {"price": "0.000038", "estimated_price_impact": "0.01", ...}
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Any

from loguru import logger


# ── Chain configuration ───────────────────────────────────────────────────────

CHAIN_IDS: dict[str, int] = {
    "ethereum": 1,
    "bsc":      56,
    "polygon":  137,
    "arbitrum": 42161,
    "optimism": 10,
    "base":     8453,
}

# Well-known token addresses per chain (for sell/buy token params)
TOKEN_ADDRESSES: dict[int, dict[str, str]] = {
    1: {   # Ethereum
        "ETH":  "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "DAI":  "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        "WBTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
        "LINK": "0x514910771AF9Ca656af840dff83E8264EcF986CA",
        "UNI":  "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
    },
    56: {  # BSC
        "BNB":  "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        "WBNB": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
        "USDT": "0x55d398326f99059fF775485246999027B3197955",
        "USDC": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
        "BUSD": "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56",
    },
    137: { # Polygon
        "MATIC":"0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        "WMATIC":"0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
        "USDT": "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
        "USDC": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
        "WETH": "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
    },
    42161: {  # Arbitrum
        "ETH":  "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        "USDT": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",
        "USDC": "0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8",
        "WBTC": "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f",
    },
}

# Rate limits per plan (calls per second)
_ZEROX_RATE_LIMITS: dict[str, float] = {
    "Free":       1.0,
    "Standard":   5.0,
    "Custom":    20.0,
}

_ZEROX_BASE_URL = "https://api.0x.org"


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _get(url: str, headers: dict[str, str], timeout: int = 10) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


# ── Main class ────────────────────────────────────────────────────────────────

class ZeroXProvider:
    """
    0x Protocol Swap API client.

    Fetches the best available price/quote for a token swap across all
    integrated DEX liquidity sources.

    Adds a simple per-second rate limiter based on the configured plan.
    """

    def __init__(self) -> None:
        self._api_key  = ""
        self._chain    = "ethereum"
        self._plan     = "Free"
        self._base_url = _ZEROX_BASE_URL
        self.active    = False
        self._last_call = 0.0    # timestamp of last API call
        self._reload_config()

    def _reload_config(self) -> None:
        try:
            from config import get_settings
            s   = get_settings()
            cfg = getattr(s, "zerox", None)
            if cfg and cfg.enabled and cfg.api_key.strip():
                self._api_key  = cfg.api_key.strip()
                self._chain    = getattr(cfg, "chain", "ethereum")
                self._plan     = getattr(cfg, "plan",  "Free")
                self._base_url = getattr(cfg, "base_url", _ZEROX_BASE_URL).rstrip("/")
                self.active    = True
                logger.debug(
                    f"ZeroXProvider active: chain={self._chain} plan={self._plan} "
                    f"rate={_ZEROX_RATE_LIMITS.get(self._plan, 1.0)}/s"
                )
            else:
                self.active = False
        except Exception:
            self.active = False

    # ── Rate limiter ──────────────────────────────────────────────────────────

    def _wait_rate_limit(self) -> None:
        """Block until it's safe to make another call (per-second budget)."""
        rps = _ZEROX_RATE_LIMITS.get(self._plan, 1.0)
        min_gap = 1.0 / rps
        elapsed = time.time() - self._last_call
        if elapsed < min_gap:
            time.sleep(min_gap - elapsed)
        self._last_call = time.time()

    # ── Headers ───────────────────────────────────────────────────────────────

    def _headers(self, chain: str | None = None) -> dict[str, str]:
        chain_id = CHAIN_IDS.get(chain or self._chain, 1)
        return {
            "0x-api-key":    self._api_key,
            "0x-chain-id":   str(chain_id),
            "Accept":        "application/json",
        }

    # ── Token address resolution ──────────────────────────────────────────────

    def _token_address(self, symbol: str, chain: str | None = None) -> str:
        """Return checksummed token address, or pass through if already 0x…"""
        if symbol.startswith("0x"):
            return symbol
        chain_id = CHAIN_IDS.get(chain or self._chain, 1)
        return TOKEN_ADDRESSES.get(chain_id, {}).get(symbol.upper(), symbol)

    # ── Public API ────────────────────────────────────────────────────────────

    def get_price(
        self,
        sell_token: str,
        buy_token:  str,
        sell_amount_usd: float = 100.0,
        chain: str | None = None,
    ) -> dict:
        """
        Get indicative swap price (no signing required — cheapest endpoint).

        Parameters
        ----------
        sell_token : str  Symbol (e.g. "USDC") or contract address
        buy_token  : str  Symbol (e.g. "ETH")  or contract address
        sell_amount_usd : float  Approximate USD value to sell (used to calc wei amount)
        chain : str | None  Override chain from config

        Returns dict with keys:
            price, estimated_price_impact_pct, gas_estimate,
            sources (list of {name, proportion}), sell_token, buy_token
        """
        if not self.active:
            return {}
        try:
            self._wait_rate_limit()
            sell_addr = self._token_address(sell_token, chain)
            buy_addr  = self._token_address(buy_token,  chain)

            # Rough sell amount in smallest unit (assuming 6 decimals for stables,
            # 18 for everything else)
            decimals = 6 if sell_token.upper() in ("USDT","USDC","BUSD") else 18
            sell_amount_wei = int(sell_amount_usd * (10 ** decimals))

            params = urllib.parse.urlencode({
                "sellToken":   sell_addr,
                "buyToken":    buy_addr,
                "sellAmount":  str(sell_amount_wei),
            })
            url  = f"{self._base_url}/swap/permit2/price?{params}"
            data = _get(url, self._headers(chain))

            return {
                "sell_token":               sell_token,
                "buy_token":                buy_token,
                "price":                    data.get("price"),
                "gross_buy_amount":         data.get("grossBuyAmount"),
                "estimated_price_impact":   data.get("estimatedPriceImpact"),
                "gas":                      data.get("gas"),
                "gas_price":                data.get("gasPrice"),
                "sources":                  data.get("route", {}).get("fills", []),
                "fees":                     data.get("fees", {}),
                "chain":                    chain or self._chain,
                "timestamp":                time.time(),
            }
        except Exception as exc:
            logger.debug(f"0x get_price {sell_token}→{buy_token} failed: {exc}")
            return {}

    def get_quote(
        self,
        sell_token:  str,
        buy_token:   str,
        sell_amount_usd: float = 100.0,
        taker_address: str = "",
        chain: str | None = None,
    ) -> dict:
        """
        Get a firm, executable swap quote (use sparingly — costs more quota).
        Requires taker_address for permit2 quotes.
        """
        if not self.active:
            return {}
        try:
            self._wait_rate_limit()
            sell_addr = self._token_address(sell_token, chain)
            buy_addr  = self._token_address(buy_token,  chain)
            decimals  = 6 if sell_token.upper() in ("USDT","USDC","BUSD") else 18
            sell_amount_wei = int(sell_amount_usd * (10 ** decimals))

            params: dict[str, Any] = {
                "sellToken":   sell_addr,
                "buyToken":    buy_addr,
                "sellAmount":  str(sell_amount_wei),
            }
            if taker_address:
                params["takerAddress"] = taker_address

            url  = f"{self._base_url}/swap/permit2/quote?" + urllib.parse.urlencode(params)
            data = _get(url, self._headers(chain))
            return data
        except Exception as exc:
            logger.debug(f"0x get_quote {sell_token}→{buy_token} failed: {exc}")
            return {}

    def get_liquidity_sources(self, chain: str | None = None) -> list[dict]:
        """List all liquidity sources available on a chain."""
        if not self.active:
            return []
        try:
            self._wait_rate_limit()
            url  = f"{self._base_url}/swap/v1/sources"
            data = _get(url, self._headers(chain))
            return list(data.get("sources", {}).keys())
        except Exception as exc:
            logger.debug(f"0x get_liquidity_sources failed: {exc}")
            return []

    def get_best_price_for_pair(self, symbol: str, chain: str | None = None) -> dict:
        """
        Convenience: get the 0x best-route price for a CEX symbol like 'ETHUSDT'.
        Returns {price, sources, impact_pct} or {} if unavailable.
        """
        if not self.active or len(symbol) < 6:
            return {}
        # Map ETHUSDT → sell USDC, buy ETH
        stables = {"USDT", "USDC", "BUSD", "DAI"}
        for stable in stables:
            if symbol.endswith(stable):
                base = symbol[:-len(stable)]
                return self.get_price("USDC", base, sell_amount_usd=1000, chain=chain)
        return {}

    def test_connection(self) -> tuple[bool, str]:
        """Quick connectivity test — returns (ok, message)."""
        if not self._api_key:
            return False, "No API key configured"
        try:
            self._wait_rate_limit()
            url  = f"{self._base_url}/swap/v1/sources"
            data = _get(url, self._headers())
            sources = list(data.get("sources", {}).keys())
            return True, f"Connected — {len(sources)} liquidity sources on {self._chain}"
        except Exception as exc:
            return False, str(exc)[:100]


# ── Singleton ─────────────────────────────────────────────────────────────────

_zerox: ZeroXProvider | None = None


def get_zerox_provider() -> ZeroXProvider:
    global _zerox
    if _zerox is None:
        _zerox = ZeroXProvider()
    return _zerox


def reload_zerox_provider() -> ZeroXProvider:
    global _zerox
    if _zerox is not None:
        _zerox._reload_config()
    else:
        _zerox = ZeroXProvider()
    return _zerox
