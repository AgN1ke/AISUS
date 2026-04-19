"""LLM gateway: wraps chat_once with per-turn transaction logging.

Public API:
- `log_llm_transaction(...)` — async; extracts usage from a chat_once response
  and writes one `transactions` row attributed to the supplied BillingContext.
- `chat_once_billed(...)` — async convenience wrapper that calls
  `agent.llm.chat_once` (sync) and logs the transaction after. Returns the
  raw chat_once response plus a CostBreakdown.

Stage 3 behavior: transactions are logged only when `billing_context` is
provided. Successful transactions also atomically debit the account via
`db.accounts_repository.debit_account`. Failures and zero-cost calls are
logged but never debited. A stale balance (rare, e.g. concurrent spend)
triggers a warning — the row stays logged so reconciliation can catch it.
"""
from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Any, Optional

from db.accounts_repository import InsufficientBalanceError, debit_account
from db.transactions_repository import log_transaction

from .context import BillingContext
from .pricing import CostBreakdown, compute_cost_uah

logger = logging.getLogger(__name__)


def _usage_int(container: Any, *names: str) -> int:
    for name in names:
        value = None
        if isinstance(container, dict):
            value = container.get(name)
        else:
            value = getattr(container, name, None)
        if value not in (None, ""):
            try:
                return int(value)
            except Exception:
                continue
    return 0


def _is_rate_limit_error(error_text: str | None) -> bool:
    text = (error_text or "").lower()
    if not text:
        return False
    return any(
        marker in text
        for marker in (
            "rate limit",
            "rate_limit",
            "too many requests",
            "429",
            "resource exhausted",
        )
    )


def _is_auth_error(error_text: str | None) -> bool:
    text = (error_text or "").lower()
    if not text:
        return False
    return any(
        marker in text
        for marker in (
            "api_key_invalid",
            "invalid api key",
            "api key not valid",
            "incorrect api key",
            "unauthorized",
            "authentication",
            "401",
            "403",
            "invalid_api_key",
        )
    )


def _extract_usage(response: Any) -> tuple[int, int]:
    """Best-effort extraction of (tokens_in, tokens_out) from a response object.

    Supports OpenAI-compatible Python SDK response objects and Gemini
    usageMetadata-style payloads, including thinking-token accounting.
    """
    if response is None:
        return 0, 0

    usage = getattr(response, "usage", None)
    if usage is not None:
        tokens_in = _usage_int(
            usage,
            "prompt_tokens",
            "input_tokens",
            "prompt_token_count",
            "promptTokenCount",
        )
        completion_tokens = getattr(usage, "completion_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        if completion_tokens not in (None, ""):
            tokens_out = int(completion_tokens)
        elif output_tokens not in (None, ""):
            tokens_out = int(output_tokens)
        else:
            tokens_out = _usage_int(
                usage,
                "candidates_tokens",
                "candidates_token_count",
                "candidatesTokenCount",
            ) + _usage_int(
                usage,
                "thoughts_tokens",
                "thoughts_token_count",
                "thoughtsTokenCount",
            )
        return tokens_in, tokens_out

    if isinstance(response, dict):
        usage_dict = response.get("usage") or response.get("usageMetadata") or {}
        tokens_in = _usage_int(
            usage_dict,
            "prompt_tokens",
            "input_tokens",
            "promptTokenCount",
            "prompt_token_count",
        )
        completion_tokens = usage_dict.get("completion_tokens")
        output_tokens = usage_dict.get("output_tokens")
        if completion_tokens not in (None, ""):
            tokens_out = int(completion_tokens)
        elif output_tokens not in (None, ""):
            tokens_out = int(output_tokens)
        else:
            tokens_out = _usage_int(
                usage_dict,
                "candidatesTokenCount",
                "candidates_token_count",
            ) + _usage_int(
                usage_dict,
                "thoughtsTokenCount",
                "thoughts_token_count",
            )
        return tokens_in, tokens_out

    return 0, 0


async def log_llm_transaction(
    response: Any,
    *,
    billing_context: Optional[BillingContext],
    capability: str,
    provider: str,
    model: str,
    key_id: int | None = None,
    latency_ms: int | None = None,
    status: str = "success",
    error_text: str | None = None,
    tokens_in_override: int | None = None,
    tokens_out_override: int | None = None,
    unit_count: int = 0,
    kind: str = "llm_call",
) -> Optional[CostBreakdown]:
    """Write one transactions row. No-op if billing_context is incomplete."""
    if billing_context is None or not billing_context.is_complete():
        return None

    if tokens_in_override is not None or tokens_out_override is not None:
        tokens_in = int(tokens_in_override or 0)
        tokens_out = int(tokens_out_override or 0)
    else:
        tokens_in, tokens_out = _extract_usage(response)

    pricing_kind = "llm" if kind == "llm_call" else (
        "search" if kind == "search_api" else
        "tts" if kind == "tts" else
        "stt" if kind == "stt" else
        "other"
    )
    breakdown = await compute_cost_uah(
        provider=provider,
        model=model,
        kind=pricing_kind,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        unit_count=unit_count,
    )

    try:
        await log_transaction(
            turn_id=billing_context.turn_id,
            account_id=billing_context.account_id,
            chat_id=billing_context.chat_id,
            user_id=billing_context.user_id,
            kind=kind,
            capability=capability,
            provider=provider,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            unit_count=unit_count,
            cost_usd=breakdown.cost_usd,
            cost_uah=breakdown.cost_uah,
            markup_pct=breakdown.markup_pct,
            key_id=key_id,
            latency_ms=latency_ms,
            status=status,
            error_text=error_text,
        )
    except Exception as exc:
        logger.exception("gateway.log_transaction_failed: %s", exc)
        return breakdown

    # Atomic debit — only for successful transactions with real cost.
    # Preflight (policy.check_budget) has already verified sufficient balance,
    # but we still swallow InsufficientBalanceError so the observed cost is
    # recorded even if the balance drifted (e.g. concurrent spend).
    if status == "success" and breakdown.cost_uah > 0:
        try:
            await debit_account(
                billing_context.account_id, breakdown.cost_uah
            )
        except InsufficientBalanceError as exc:
            logger.warning(
                "gateway.debit_insufficient account_id=%s cost_uah=%s: %s",
                billing_context.account_id,
                breakdown.cost_uah,
                exc,
            )
        except Exception as exc:
            logger.exception(
                "gateway.debit_failed account_id=%s cost_uah=%s: %s",
                billing_context.account_id,
                breakdown.cost_uah,
                exc,
            )

    logger.debug(
        "gateway.logged turn=%s cap=%s model=%s in=%s out=%s uah=%s src=%s",
        billing_context.turn_id,
        capability,
        model,
        tokens_in,
        tokens_out,
        breakdown.cost_uah,
        breakdown.source,
    )
    if key_id:
        try:
            from billing.keypool import (
                record_error,
                record_rate_limit,
                record_success,
            )
        except Exception:
            return breakdown

        try:
            if status == "success":
                await record_success(key_id, cost_usd=breakdown.cost_usd)
            elif _is_rate_limit_error(error_text):
                await record_rate_limit(key_id)
            elif error_text:
                await record_error(key_id, error_text, disable=_is_auth_error(error_text))
        except Exception as exc:
            logger.warning("gateway.keypool_update_failed key_id=%s: %s", key_id, exc)
    return breakdown


async def chat_once_billed(
    messages: list[dict[str, Any]],
    *,
    capability: str,
    billing_context: Optional[BillingContext] = None,
    **chat_once_kwargs: Any,
) -> tuple[Any, Optional[CostBreakdown]]:
    """Call `agent.llm.chat_once` and log the transaction.

    Returns (response, breakdown). If billing_context is incomplete the
    response still flows through; breakdown is None.
    """
    # Import here to avoid a circular import at module load time.
    from agent.llm import chat_once
    from core.provider_registry import resolve_provider_binding

    binding = resolve_provider_binding(
        capability,
        model=chat_once_kwargs.get("model"),
    )
    provider_label = binding.provider
    model_label = binding.model

    started = time.monotonic()
    response = None
    error_text: str | None = None
    status = "success"
    try:
        response = await asyncio.to_thread(
            chat_once,
            messages,
            capability=capability,
            **chat_once_kwargs,
        )
    except Exception as exc:
        status = "failed"
        error_text = str(exc)[:500]
        latency = int((time.monotonic() - started) * 1000)
        await log_llm_transaction(
            None,
            billing_context=billing_context,
            capability=capability,
            provider=provider_label,
            model=model_label,
            latency_ms=latency,
            status=status,
            error_text=error_text,
        )
        raise

    latency = int((time.monotonic() - started) * 1000)
    breakdown = await log_llm_transaction(
        response,
        billing_context=billing_context,
        capability=capability,
        provider=provider_label,
        model=model_label,
        key_id=binding.key_id,
        latency_ms=latency,
        status=status,
    )
    return response, breakdown
