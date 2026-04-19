from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional


@dataclass(frozen=True)
class BillingContext:
    """Identity object passed through the LLM pipeline for per-turn attribution.

    All LLM/API calls executed while handling a single user message share the
    same `turn_id`; the collection of resulting `transactions` rows is the
    authoritative breakdown for `/balance` display.

    None-valued fields signal "not attributable yet" — the gateway records a
    transaction without account/chat/user linkage only in the testing/bootstrap
    path. Production code paths always populate all four ids.
    """

    turn_id: Optional[str]
    account_id: int
    chat_id: int
    user_id: int
    capability_hint: Optional[str] = None
    meta: dict = field(default_factory=dict)

    def with_capability(self, capability: str) -> "BillingContext":
        return replace(self, capability_hint=capability)

    def is_complete(self) -> bool:
        return bool(self.turn_id and self.account_id and self.chat_id and self.user_id)
