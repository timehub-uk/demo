"""
MetaMask Wallet Integration — Optional bridge for on-chain asset transfers.

Allows the trading bot to automatically transfer profits or specific tokens
from a Binance account to a MetaMask (EVM) wallet address via:

  1. Binance Withdrawal API  — withdraw from Binance to a MetaMask wallet address
  2. Web3 direct transfers   — (if a private key is configured) send ERC-20/native tokens
                               directly between wallets

IMPORTANT SECURITY NOTES:
  - Private keys are NEVER stored in plaintext. They are encrypted via EncryptionManager.
  - Only the wallet address (public) is needed for Binance withdrawals.
  - Private key is optional and only needed for direct Web3 transfers.
  - All transfers require explicit user confirmation unless AUTO_TRANSFER is enabled.
  - AUTO_TRANSFER only activates when profit exceeds AUTO_TRANSFER_THRESHOLD_USDT.

Configuration (stored in settings):
  metamask_address         : EVM wallet address (0x…)
  metamask_auto_transfer   : bool — enable automatic profit sweeping
  metamask_threshold_usdt  : float — USDT profit threshold to trigger auto-sweep
  metamask_network         : str — 'ethereum' | 'bsc' | 'polygon' | 'arbitrum'
  metamask_private_key_enc : encrypted private key (optional — for direct transfers)

Transfer modes:
  BINANCE_WITHDRAWAL — uses Binance withdrawal API (requires address whitelisting)
  WEB3_DIRECT        — uses web3.py to send tokens directly (requires private key)

Supported networks for Binance withdrawal:
  ETH  — Ethereum mainnet
  BSC  — BNB Smart Chain
  MATIC — Polygon
  ARB  — Arbitrum One
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Callable

from loguru import logger
from utils.logger import get_intel_logger


# Minimum transfer amount (USDT equivalent) — never transfer dust
MIN_TRANSFER_USDT = 20.0

# Supported networks and their Binance withdrawal network codes
NETWORK_CODES: dict[str, str] = {
    "ethereum": "ETH",
    "bsc":      "BSC",
    "polygon":  "MATIC",
    "arbitrum": "ARBITRUM",
    "optimism": "OP",
}

# Network-native gas token (for gas estimation display)
NETWORK_GAS_TOKEN: dict[str, str] = {
    "ethereum": "ETH",
    "bsc":      "BNB",
    "polygon":  "MATIC",
    "arbitrum": "ETH",
    "optimism": "ETH",
}


@dataclass
class TransferRequest:
    """Represents a pending or completed transfer."""
    id:             str
    asset:          str           # token symbol (e.g. USDT, ETH, BNB)
    amount:         float         # amount to transfer
    to_address:     str           # destination MetaMask address
    network:        str           # ethereum | bsc | polygon | …
    mode:           str           # BINANCE_WITHDRAWAL | WEB3_DIRECT
    status:         str = "PENDING"    # PENDING | APPROVED | SENT | CONFIRMED | FAILED
    tx_hash:        str = ""
    binance_id:     str = ""      # Binance withdrawal ID
    fee_usdt:       float = 0.0   # estimated gas/fee
    error:          str = ""
    requested_at:   str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at:   str = ""
    note:           str = ""


class MetaMaskWallet:
    """
    Optional MetaMask wallet bridge.

    Enables automatic or manual transfer of profits/tokens from Binance
    to a configured MetaMask (EVM-compatible) wallet address.

    Usage::

        wallet = MetaMaskWallet(
            binance_client=client,
            address="0xYourMetaMaskAddress",
            network="bsc",
            auto_transfer=True,
            threshold_usdt=100.0,
        )
        wallet.on_transfer(my_callback)
        wallet.enable()

        # Manual transfer
        req = wallet.request_transfer("USDT", 50.0)
        wallet.approve_transfer(req.id)
    """

    def __init__(
        self,
        binance_client=None,
        address: str = "",
        network: str = "bsc",
        auto_transfer: bool = False,
        threshold_usdt: float = 100.0,
        private_key_enc: str = "",   # encrypted private key (optional)
    ) -> None:
        self._client         = binance_client
        self._address        = address.strip()
        self._network        = network.lower()
        self._auto_transfer  = auto_transfer
        self._threshold      = max(MIN_TRANSFER_USDT, threshold_usdt)
        self._private_key_enc = private_key_enc
        self._intel          = get_intel_logger()

        self._lock      = threading.Lock()
        self._enabled   = False
        self._transfers: dict[str, TransferRequest] = {}
        self._callbacks: list[Callable[[TransferRequest], None]] = []

        # Track cumulative unrealised profit for auto-sweep
        self._pending_profit_usdt: float = 0.0

    # ── Configuration ──────────────────────────────────────────────────────────

    @property
    def address(self) -> str:
        return self._address

    @address.setter
    def address(self, value: str) -> None:
        if not self._validate_address(value):
            raise ValueError(f"Invalid EVM address: {value!r}")
        self._address = value.strip()

    @property
    def enabled(self) -> bool:
        return self._enabled and bool(self._address)

    @property
    def network(self) -> str:
        return self._network

    @property
    def auto_transfer(self) -> bool:
        return self._auto_transfer

    @auto_transfer.setter
    def auto_transfer(self, value: bool) -> None:
        self._auto_transfer = value
        self._intel.system(
            "MetaMaskWallet",
            f"Auto-transfer {'ENABLED' if value else 'DISABLED'}  "
            f"threshold={self._threshold:.2f} USDT"
        )

    def enable(self) -> None:
        """Enable the wallet bridge. Requires address to be set."""
        if not self._address:
            raise RuntimeError("MetaMask address not configured")
        if not self._validate_address(self._address):
            raise ValueError(f"Invalid MetaMask address: {self._address!r}")
        self._enabled = True
        self._intel.system(
            "MetaMaskWallet",
            f"Enabled — address={self._address[:8]}…{self._address[-6:]}  "
            f"network={self._network}  "
            f"auto={'ON' if self._auto_transfer else 'OFF'}"
        )

    def disable(self) -> None:
        self._enabled = False
        self._intel.system("MetaMaskWallet", "Disabled")

    # ── Public API ─────────────────────────────────────────────────────────────

    def on_transfer(self, cb: Callable[[TransferRequest], None]) -> None:
        """Register callback — called when transfer status changes."""
        self._callbacks.append(cb)

    def get_transfers(self) -> list[TransferRequest]:
        """Return all transfer records (newest first)."""
        with self._lock:
            return sorted(self._transfers.values(),
                          key=lambda t: t.requested_at, reverse=True)

    def get_pending(self) -> list[TransferRequest]:
        """Return transfers awaiting approval."""
        with self._lock:
            return [t for t in self._transfers.values() if t.status == "PENDING"]

    def notify_profit(self, profit_usdt: float) -> None:
        """
        Called by the trading engine when a position closes in profit.
        If auto-transfer is on and cumulative profit ≥ threshold, triggers a sweep.
        """
        if not self.enabled or not self._auto_transfer:
            return
        with self._lock:
            self._pending_profit_usdt += profit_usdt
            if self._pending_profit_usdt >= self._threshold:
                amount = self._pending_profit_usdt
                self._pending_profit_usdt = 0.0
        # Outside lock
        if amount >= self._threshold:
            self._intel.system(
                "MetaMaskWallet",
                f"Auto-sweep triggered — {amount:.2f} USDT profit ≥ threshold {self._threshold:.2f}"
            )
            req = self.request_transfer("USDT", amount, auto_approved=True)
            if req:
                self._execute_transfer(req)

    def request_transfer(
        self,
        asset: str,
        amount: float,
        auto_approved: bool = False,
    ) -> Optional[TransferRequest]:
        """
        Create a new transfer request. If auto_approved=True (auto-sweep),
        the transfer will be sent immediately without user approval.
        Otherwise it waits in PENDING state for approve_transfer().
        """
        if not self.enabled:
            logger.warning("MetaMaskWallet: not enabled — ignoring transfer request")
            return None
        if amount < MIN_TRANSFER_USDT:
            logger.warning(f"MetaMaskWallet: {amount:.2f} USDT below minimum {MIN_TRANSFER_USDT}")
            return None

        import uuid
        req = TransferRequest(
            id          = str(uuid.uuid4())[:8],
            asset       = asset.upper(),
            amount      = amount,
            to_address  = self._address,
            network     = self._network,
            mode        = "BINANCE_WITHDRAWAL",
            status      = "APPROVED" if auto_approved else "PENDING",
            note        = "Auto-sweep" if auto_approved else "Manual request",
        )

        with self._lock:
            self._transfers[req.id] = req

        self._intel.system(
            "MetaMaskWallet",
            f"Transfer request {req.id} — {amount:.4f} {asset}  "
            f"→ {self._address[:8]}…  status={req.status}"
        )
        self._notify(req)
        return req

    def approve_transfer(self, transfer_id: str) -> bool:
        """User approves a PENDING transfer — moves it to APPROVED and executes."""
        with self._lock:
            req = self._transfers.get(transfer_id)
        if not req:
            logger.warning(f"MetaMaskWallet: transfer {transfer_id} not found")
            return False
        if req.status != "PENDING":
            logger.warning(f"MetaMaskWallet: transfer {transfer_id} is not PENDING (status={req.status})")
            return False

        req.status = "APPROVED"
        self._notify(req)
        threading.Thread(
            target=self._execute_transfer,
            args=(req,),
            daemon=True,
            name=f"metamask-transfer-{transfer_id}",
        ).start()
        return True

    def cancel_transfer(self, transfer_id: str) -> bool:
        """Cancel a PENDING transfer."""
        with self._lock:
            req = self._transfers.get(transfer_id)
        if not req or req.status != "PENDING":
            return False
        req.status = "FAILED"
        req.error  = "Cancelled by user"
        req.completed_at = datetime.now(timezone.utc).isoformat()
        self._notify(req)
        return True

    # ── Transfer execution ─────────────────────────────────────────────────────

    def _execute_transfer(self, req: TransferRequest) -> None:
        """Execute an APPROVED transfer via Binance withdrawal API."""
        try:
            if req.mode == "BINANCE_WITHDRAWAL":
                self._binance_withdrawal(req)
            else:
                self._web3_direct(req)
        except Exception as exc:
            req.status       = "FAILED"
            req.error        = str(exc)
            req.completed_at = datetime.now(timezone.utc).isoformat()
            self._intel.error("MetaMaskWallet", f"Transfer {req.id} failed: {exc!r}")
            self._notify(req)

    def _binance_withdrawal(self, req: TransferRequest) -> None:
        """Execute via Binance withdrawal API."""
        if not self._client:
            # Demo mode — simulate withdrawal
            logger.info(f"MetaMaskWallet [DEMO]: would withdraw {req.amount} {req.asset} "
                        f"→ {req.to_address} via {NETWORK_CODES.get(req.network, 'ETH')}")
            req.status      = "SENT"
            req.binance_id  = "DEMO-" + req.id
            req.completed_at = datetime.now(timezone.utc).isoformat()
            self._intel.system(
                "MetaMaskWallet",
                f"[DEMO] Transfer {req.id} sent — {req.amount:.4f} {req.asset} "
                f"→ {req.to_address[:8]}…"
            )
            self._notify(req)
            return

        network_code = NETWORK_CODES.get(req.network, "ETH")

        try:
            # Binance withdrawal API call
            resp = self._client._post(
                "/sapi/v1/capital/withdraw/apply",
                signed=True,
                coin       = req.asset,
                address    = req.to_address,
                amount     = req.amount,
                network    = network_code,
            )
            wid = resp.get("id", "")
            req.binance_id   = wid
            req.status       = "SENT"
            req.completed_at = datetime.now(timezone.utc).isoformat()

            self._intel.system(
                "MetaMaskWallet",
                f"Transfer {req.id} SENT — Binance withdrawal ID: {wid}  "
                f"{req.amount:.4f} {req.asset} → {req.to_address[:8]}…"
            )
        except Exception as exc:
            raise RuntimeError(f"Binance withdrawal failed: {exc}") from exc

        self._notify(req)

    def _web3_direct(self, req: TransferRequest) -> None:
        """Direct Web3 transfer using private key (optional mode)."""
        try:
            from web3 import Web3
        except ImportError:
            raise RuntimeError("web3 package not installed — run: pip install web3")

        if not self._private_key_enc:
            raise RuntimeError("Private key not configured for Web3 direct mode")

        # Decrypt private key
        try:
            from config.encryption import EncryptionManager
            enc = EncryptionManager()
            private_key = enc.decrypt(self._private_key_enc)
        except Exception as exc:
            raise RuntimeError(f"Failed to decrypt private key: {exc}") from exc

        # Placeholder — full Web3 transfer implementation would go here
        # This would require network RPC URL configuration
        logger.warning("MetaMaskWallet: Web3 direct mode not yet fully implemented")
        req.status = "FAILED"
        req.error  = "Web3 direct mode requires RPC URL configuration"
        req.completed_at = datetime.now(timezone.utc).isoformat()
        self._notify(req)

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_address(address: str) -> bool:
        """Basic EVM address validation."""
        addr = address.strip()
        if not addr.startswith("0x"):
            return False
        if len(addr) != 42:
            return False
        try:
            int(addr, 16)
        except ValueError:
            return False
        return True

    def _notify(self, req: TransferRequest) -> None:
        for cb in self._callbacks:
            try:
                cb(req)
            except Exception as exc:
                logger.warning(f"MetaMaskWallet callback error: {exc!r}")

    # ── Wallet info ────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return current wallet status summary."""
        return {
            "enabled":        self.enabled,
            "address":        self._address,
            "network":        self._network,
            "auto_transfer":  self._auto_transfer,
            "threshold_usdt": self._threshold,
            "pending_profit": self._pending_profit_usdt,
            "total_transfers": len(self._transfers),
            "pending_count":  len(self.get_pending()),
        }
