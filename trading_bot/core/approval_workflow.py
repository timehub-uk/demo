"""
Approval Workflow Engine  (Layer 10 – Module 75)
=================================================
Requires sign-off for new strategies, leverage changes,
wallet permissions, and model promotion.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional

from loguru import logger


class ApprovalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass
class ApprovalRequest:
    request_id: str
    request_type: str          # "strategy_enable", "model_promote", "leverage_change", etc.
    requester: str
    description: str
    payload: dict              # what will be executed on approval
    required_approvers: List[str]
    approvals: List[str] = field(default_factory=list)
    rejections: List[str] = field(default_factory=list)
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 86400)
    resolved_at: Optional[float] = None
    resolution_notes: str = ""

    @property
    def is_quorum_met(self) -> bool:
        needed = max(1, len(self.required_approvers) // 2 + 1)
        return len(self.approvals) >= needed

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    @property
    def is_open(self) -> bool:
        return self.status == ApprovalStatus.PENDING and not self.is_expired


class ApprovalWorkflowEngine:
    """
    Multi-approver workflow for high-impact system changes.

    Supported request types:
    - strategy_enable:      Enable a new trading strategy
    - strategy_promote:     Move strategy from staging to active
    - model_promote:        Promote ML model to production
    - leverage_change:      Increase leverage limits
    - wallet_permission:    Grant wallet signing permissions
    - kill_switch_clear:    Clear an active kill switch
    - secrets_rotate:       Rotate API credentials
    """

    def __init__(self, access_control=None):
        self._access_control = access_control
        self._requests: Dict[str, ApprovalRequest] = {}
        self._callbacks: List[Callable] = []
        self._lock = threading.RLock()
        self._expiry_thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        self._running = True
        self._expiry_thread = threading.Thread(
            target=self._expiry_loop, daemon=True, name="approval-workflow"
        )
        self._expiry_thread.start()

    def stop(self) -> None:
        self._running = False

    def on_event(self, callback: Callable) -> None:
        self._callbacks.append(callback)

    def submit(
        self,
        request_type: str,
        requester: str,
        description: str,
        payload: dict,
        required_approvers: Optional[List[str]] = None,
        expire_hours: float = 24.0,
    ) -> ApprovalRequest:
        req = ApprovalRequest(
            request_id=f"REQ-{uuid.uuid4().hex[:8].upper()}",
            request_type=request_type,
            requester=requester,
            description=description,
            payload=payload,
            required_approvers=required_approvers or ["admin"],
            expires_at=time.time() + expire_hours * 3600,
        )
        with self._lock:
            self._requests[req.request_id] = req

        logger.info(
            f"[Workflow] New request {req.request_id} type={request_type} "
            f"by={requester}: {description}"
        )
        self._fire("submitted", req)
        return req

    def approve(self, request_id: str, approver: str,
                notes: str = "") -> Optional[ApprovalRequest]:
        with self._lock:
            req = self._requests.get(request_id)
            if not req or not req.is_open:
                return None
            if approver in req.approvals:
                return req  # already approved by this user
            req.approvals.append(approver)

            if req.is_quorum_met:
                req.status = ApprovalStatus.APPROVED
                req.resolved_at = time.time()
                req.resolution_notes = notes
                logger.info(
                    f"[Workflow] {request_id} APPROVED by quorum "
                    f"({len(req.approvals)}/{len(req.required_approvers)})"
                )
                self._fire("approved", req)
                self._execute(req)

        return req

    def reject(self, request_id: str, rejector: str,
               reason: str = "") -> Optional[ApprovalRequest]:
        with self._lock:
            req = self._requests.get(request_id)
            if not req or not req.is_open:
                return None
            req.rejections.append(rejector)
            req.status = ApprovalStatus.REJECTED
            req.resolved_at = time.time()
            req.resolution_notes = reason

        logger.warning(f"[Workflow] {request_id} REJECTED by {rejector}: {reason}")
        self._fire("rejected", req)
        return req

    def cancel(self, request_id: str, actor: str) -> bool:
        with self._lock:
            req = self._requests.get(request_id)
            if not req or not req.is_open:
                return False
            req.status = ApprovalStatus.CANCELLED
        self._fire("cancelled", req)
        return True

    def get_pending(self) -> List[ApprovalRequest]:
        with self._lock:
            return [r for r in self._requests.values() if r.is_open]

    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        with self._lock:
            return self._requests.get(request_id)

    def get_all(self, limit: int = 100) -> List[ApprovalRequest]:
        with self._lock:
            return list(self._requests.values())[-limit:]

    def _execute(self, req: ApprovalRequest) -> None:
        """Execute the approved action. Override for custom handlers."""
        logger.info(f"[Workflow] Executing approved action: {req.request_type} {req.payload}")

    def _expiry_loop(self) -> None:
        while self._running:
            time.sleep(60)
            with self._lock:
                for req in self._requests.values():
                    if req.is_open and req.is_expired:
                        req.status = ApprovalStatus.EXPIRED
                        req.resolved_at = time.time()
                        self._fire("expired", req)
                        logger.warning(f"[Workflow] {req.request_id} expired")

    def _fire(self, event_type: str, req: ApprovalRequest) -> None:
        for cb in self._callbacks:
            try:
                cb(event_type, req)
            except Exception as exc:
                logger.warning(f"[Workflow] callback error on {event_type}: {exc}")
