"""
Symbol and Contract Mapper  (Layer 3 – Module 20)
===================================================
Maps assets across tickers, wrapped assets, chains, and exchange naming mismatches.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from loguru import logger


class SymbolMapper:
    """
    Unified symbol resolution across exchanges and chains.

    Examples:
    - BTC/USDT (Binance) == BTCUSDT == bitcoin (CoinGecko) == 0x2260... (WBTC on ETH)
    - ETH/USDT == ETHUSDT == ethereum == 0xC02aaA... (WETH)
    """

    # Canonical symbol → exchange variants
    _DEFAULTS: Dict[str, Dict[str, str]] = {
        "BTC": {
            "binance_spot": "BTCUSDT",
            "binance_perp": "BTCUSDT",
            "coingecko": "bitcoin",
            "eth_address": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",  # WBTC
        },
        "ETH": {
            "binance_spot": "ETHUSDT",
            "binance_perp": "ETHUSDT",
            "coingecko": "ethereum",
            "eth_address": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",  # WETH
        },
        "SOL": {
            "binance_spot": "SOLUSDT",
            "binance_perp": "SOLUSDT",
            "coingecko": "solana",
        },
        "BNB": {
            "binance_spot": "BNBUSDT",
            "binance_perp": "BNBUSDT",
            "coingecko": "binancecoin",
            "bsc_address": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",  # WBNB
        },
    }

    def __init__(self):
        self._map: Dict[str, Dict[str, str]] = dict(self._DEFAULTS)
        self._reverse: Dict[str, str] = {}  # exchange_symbol → canonical
        self._build_reverse()

    def _build_reverse(self) -> None:
        for canonical, variants in self._map.items():
            for _exchange, sym in variants.items():
                self._reverse[sym.upper()] = canonical

    def to_binance(self, canonical: str, market: str = "spot") -> Optional[str]:
        key = f"binance_{market}"
        return self._map.get(canonical.upper(), {}).get(key)

    def to_canonical(self, exchange_symbol: str) -> str:
        """Convert any exchange symbol to canonical form."""
        upper = exchange_symbol.upper().replace("/", "").replace("-", "")
        # Remove USDT/BUSD/USDC suffix
        for quote in ("USDT", "BUSD", "USDC", "USD", "BTC", "ETH", "BNB"):
            if upper.endswith(quote) and upper != quote:
                base = upper[: -len(quote)]
                return self._reverse.get(base, base)
        return self._reverse.get(upper, upper)

    def register(self, canonical: str, variants: Dict[str, str]) -> None:
        canonical = canonical.upper()
        self._map.setdefault(canonical, {}).update(variants)
        for sym in variants.values():
            self._reverse[sym.upper()] = canonical

    def get_all_canonical(self) -> List[str]:
        return list(self._map.keys())

    def get_variants(self, canonical: str) -> Dict[str, str]:
        return dict(self._map.get(canonical.upper(), {}))

    def normalize_binance_pair(self, pair: str) -> str:
        """BTCUSDT, BTC/USDT, BTC-USDT → BTCUSDT"""
        return pair.upper().replace("/", "").replace("-", "").replace("_", "")


# Singleton
_mapper: Optional[SymbolMapper] = None


def get_symbol_mapper() -> SymbolMapper:
    global _mapper
    if _mapper is None:
        _mapper = SymbolMapper()
    return _mapper
