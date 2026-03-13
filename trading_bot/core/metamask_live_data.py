"""
MetaMask Live Data Provider.

Polls an EVM wallet address using FREE public JSON-RPC endpoints
(no API key required, no cost, no rate-limit concerns for normal use).

Data collected every poll cycle:
  • Native balance  (ETH / BNB / MATIC …)
  • ERC-20 token balances for a configurable watchlist
  • Current gas price and suggested fast/standard/slow tiers
  • Latest block number (connectivity proof)
  • Transaction count (nonce — useful for pending tx detection)

Public RPC endpoints used (no auth, run by node providers):
  ethereum : https://cloudflare-eth.com
  bsc      : https://bsc-dataseed.binance.org
  polygon  : https://polygon-rpc.com
  arbitrum : https://arb1.arbitrum.io/rpc
  optimism : https://mainnet.optimism.io
  base     : https://mainnet.base.org

Usage
-----
    live = MetaMaskLiveData(address="0xYour…", network="ethereum")
    live.start()                    # begins background polling
    snap = live.snapshot()          # always returns latest cached data
    live.on_update(my_callback)     # called on each new snapshot
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from loguru import logger


# ── Public RPC endpoints (free, no auth) ─────────────────────────────────────

PUBLIC_RPC: dict[str, str] = {
    "ethereum": "https://cloudflare-eth.com",
    "bsc":      "https://bsc-dataseed.binance.org",
    "polygon":  "https://polygon-rpc.com",
    "arbitrum": "https://arb1.arbitrum.io/rpc",
    "optimism": "https://mainnet.optimism.io",
    "base":     "https://mainnet.base.org",
}

NATIVE_TOKEN: dict[str, str] = {
    "ethereum": "ETH",
    "bsc":      "BNB",
    "polygon":  "MATIC",
    "arbitrum": "ETH",
    "optimism": "ETH",
    "base":     "ETH",
}

# Common ERC-20 addresses by network
ERC20_WATCHLIST: dict[str, dict[str, str]] = {
    "ethereum": {
        "USDT":  "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "USDC":  "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "WBTC":  "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
        "DAI":   "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        "LINK":  "0x514910771AF9Ca656af840dff83E8264EcF986CA",
        "UNI":   "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
        "AAVE":  "0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9",
        "WETH":  "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    },
    "bsc": {
        "USDT":  "0x55d398326f99059fF775485246999027B3197955",
        "USDC":  "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
        "BUSD":  "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56",
        "WBNB":  "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
        "CAKE":  "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82",
    },
    "polygon": {
        "USDT":  "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
        "USDC":  "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
        "WETH":  "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        "WMATIC":"0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
    },
}

# ERC-20 balanceOf(address) function selector
_BALANCE_OF_SELECTOR = "0x70a08231"   # balanceOf(address)
_DECIMALS_SELECTOR   = "0x313ce567"   # decimals()


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class TokenBalance:
    symbol:   str
    address:  str   # contract address
    balance:  float
    decimals: int   = 18
    usd_value: float = 0.0


@dataclass
class WalletSnapshot:
    address:          str
    network:          str
    native_symbol:    str
    native_balance:   float
    native_usd:       float
    token_balances:   list[TokenBalance] = field(default_factory=list)
    gas_price_gwei:   float = 0.0
    gas_fast_gwei:    float = 0.0
    block_number:     int   = 0
    tx_count:         int   = 0
    total_usd:        float = 0.0
    timestamp:        str   = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    rpc_latency_ms:   float = 0.0
    error:            str   = ""

    def to_dict(self) -> dict:
        return {
            "address":        self.address,
            "network":        self.network,
            "native_symbol":  self.native_symbol,
            "native_balance": self.native_balance,
            "native_usd":     self.native_usd,
            "tokens":         [
                {"symbol": t.symbol, "balance": t.balance,
                 "usd_value": t.usd_value}
                for t in self.token_balances
            ],
            "gas_price_gwei": self.gas_price_gwei,
            "gas_fast_gwei":  self.gas_fast_gwei,
            "block_number":   self.block_number,
            "tx_count":       self.tx_count,
            "total_usd":      self.total_usd,
            "timestamp":      self.timestamp,
            "rpc_latency_ms": self.rpc_latency_ms,
        }


# ── JSON-RPC helpers ──────────────────────────────────────────────────────────

def _rpc_call(rpc_url: str, method: str, params: list, timeout: int = 8) -> any:
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": method, "params": params
    }).encode()
    req = urllib.request.Request(
        rpc_url, data=payload,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    if "error" in data:
        raise RuntimeError(f"RPC error: {data['error']}")
    return data.get("result")


def _hex_to_int(h: str) -> int:
    return int(h, 16) if h and h != "0x" else 0


def _wei_to_ether(wei: int, decimals: int = 18) -> float:
    return wei / (10 ** decimals)


def _encode_balance_call(wallet_address: str) -> str:
    """Encode ERC-20 balanceOf(address) calldata."""
    addr_padded = wallet_address.lower().replace("0x", "").zfill(64)
    return _BALANCE_OF_SELECTOR + addr_padded


# ── Main class ────────────────────────────────────────────────────────────────

class MetaMaskLiveData:
    """
    Background poller for a MetaMask (EVM) wallet address.

    Uses only free public JSON-RPC — no API key, no cost.
    """

    def __init__(
        self,
        address: str = "",
        network: str = "ethereum",
        poll_interval: int = 30,   # seconds between polls
    ) -> None:
        self._address       = address.strip()
        self._network       = network.lower()
        self._poll_interval = poll_interval
        self._callbacks: list[Callable[[WalletSnapshot], None]] = []
        self._snapshot: WalletSnapshot | None = None
        self._lock    = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

    # ── Config ────────────────────────────────────────────────────────────────

    def configure(self, address: str, network: str,
                  poll_interval: int = 30) -> None:
        self._address       = address.strip()
        self._network       = network.lower()
        self._poll_interval = poll_interval

    # ── Control ───────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running or not self._address:
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="metamask-live"
        )
        self._thread.start()
        logger.info(
            f"MetaMaskLiveData: polling {self._address[:10]}… on {self._network} "
            f"every {self._poll_interval}s"
        )

    def stop(self) -> None:
        self._running = False

    def on_update(self, cb: Callable[[WalletSnapshot], None]) -> None:
        self._callbacks.append(cb)

    def snapshot(self) -> WalletSnapshot | None:
        with self._lock:
            return self._snapshot

    # ── Background loop ───────────────────────────────────────────────────────

    def _loop(self) -> None:
        while self._running:
            try:
                snap = self._poll()
                with self._lock:
                    self._snapshot = snap
                for cb in self._callbacks:
                    try:
                        cb(snap)
                    except Exception:
                        pass
            except Exception as exc:
                logger.debug(f"MetaMaskLiveData poll error: {exc}")
            time.sleep(self._poll_interval)

    def _poll(self) -> WalletSnapshot:
        rpc_url = PUBLIC_RPC.get(self._network, PUBLIC_RPC["ethereum"])
        native  = NATIVE_TOKEN.get(self._network, "ETH")
        addr    = self._address

        t0 = time.perf_counter()

        # 1. Latest block + native balance + gas price + tx count in parallel
        block_num    = _hex_to_int(_rpc_call(rpc_url, "eth_blockNumber", []))
        wei_balance  = _hex_to_int(_rpc_call(rpc_url, "eth_getBalance",
                                              [addr, "latest"]))
        gas_wei      = _hex_to_int(_rpc_call(rpc_url, "eth_gasPrice", []))
        tx_count     = _hex_to_int(_rpc_call(rpc_url, "eth_getTransactionCount",
                                              [addr, "latest"]))

        latency_ms = (time.perf_counter() - t0) * 1000

        native_bal = _wei_to_ether(wei_balance, 18)
        gas_gwei   = gas_wei / 1e9

        # 2. ERC-20 token balances
        token_balances: list[TokenBalance] = []
        watchlist = ERC20_WATCHLIST.get(self._network, {})
        for symbol, contract in watchlist.items():
            try:
                raw = _rpc_call(rpc_url, "eth_call", [
                    {"to": contract, "data": _encode_balance_call(addr)},
                    "latest"
                ])
                decimals_raw = _rpc_call(rpc_url, "eth_call", [
                    {"to": contract, "data": _DECIMALS_SELECTOR},
                    "latest"
                ])
                decimals = _hex_to_int(decimals_raw) if decimals_raw else 18
                bal = _wei_to_ether(_hex_to_int(raw), decimals)
                if bal > 0:
                    token_balances.append(TokenBalance(
                        symbol=symbol, address=contract,
                        balance=bal, decimals=decimals
                    ))
            except Exception:
                pass   # skip tokens we can't read

        # 3. USD valuation via CoinGecko DEX cache (free — reads scheduler cache)
        native_usd = self._get_native_usd_price(native)
        for tok in token_balances:
            tok.usd_value = tok.balance * self._get_token_usd_price(tok.symbol)

        native_usd_val = native_bal * native_usd
        total_usd = native_usd_val + sum(t.usd_value for t in token_balances)

        return WalletSnapshot(
            address=addr,
            network=self._network,
            native_symbol=native,
            native_balance=native_bal,
            native_usd=native_usd_val,
            token_balances=token_balances,
            gas_price_gwei=round(gas_gwei, 2),
            gas_fast_gwei=round(gas_gwei * 1.2, 2),
            block_number=block_num,
            tx_count=tx_count,
            total_usd=round(total_usd, 2),
            rpc_latency_ms=round(latency_ms, 1),
        )

    # ── Price helpers (reads DexDataProvider scheduler cache — zero API calls) ─

    @staticmethod
    def _get_native_usd_price(symbol: str) -> float:
        """Read native token USD price from scheduler cache or Binance price cache."""
        cex_map = {"ETH": "ETHUSDT", "BNB": "BNBUSDT", "MATIC": "MATICUSDT"}
        cex_sym = cex_map.get(symbol.upper(), f"{symbol}USDT")
        try:
            from core.dex_data_provider import _fetch_binance_price
            return _fetch_binance_price(cex_sym)
        except Exception:
            return 0.0

    @staticmethod
    def _get_token_usd_price(symbol: str) -> float:
        stables = {"USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD"}
        if symbol.upper() in stables:
            return 1.0
        try:
            from core.dex_data_provider import _fetch_binance_price
            return _fetch_binance_price(f"{symbol}USDT") or 0.0
        except Exception:
            return 0.0


# ── Singleton ─────────────────────────────────────────────────────────────────

_live_data: MetaMaskLiveData | None = None


def get_metamask_live_data() -> MetaMaskLiveData:
    """Return (or create) the global MetaMaskLiveData singleton."""
    global _live_data
    if _live_data is None:
        _live_data = _create_from_config()
    return _live_data


def reload_metamask_live_data() -> MetaMaskLiveData:
    """Re-read config — call after settings save."""
    global _live_data
    try:
        from config import get_settings
        s = get_settings()
        mm = getattr(s, "metamask", None)
        if _live_data is None:
            _live_data = MetaMaskLiveData()
        addr    = getattr(mm, "address", "") if mm else ""
        network = getattr(mm, "network",  "ethereum") if mm else "ethereum"
        _live_data.configure(addr, network)
        if addr and not _live_data._running:
            _live_data.start()
        elif not addr:
            _live_data.stop()
    except Exception:
        pass
    return _live_data


def _create_from_config() -> MetaMaskLiveData:
    live = MetaMaskLiveData()
    try:
        from config import get_settings
        s = get_settings()
        mm = getattr(s, "metamask", None)
        if mm:
            addr    = getattr(mm, "address", "")
            network = getattr(mm, "network",  "ethereum")
            if addr:
                live.configure(addr, network)
                live.start()
    except Exception:
        pass
    return live
