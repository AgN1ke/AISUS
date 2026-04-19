"""ContextVar-backed propagation of BillingContext through the async pipeline.

Why a ContextVar instead of threading a parameter through every function:
the LLM call graph fans out across planner → search composer → search
evaluator → final synthesis → memory summarizer → vision → … and adding an
explicit `billing_context` parameter to every signature is ~30 files of
mostly mechanical churn that obscures real changes. ContextVar solves the
same problem with one set/reset at the turn boundary, and asyncio copies
the context on `create_task` so spawned tasks inherit it automatically.

Usage at the turn boundary:

    async with use_billing_context(ctx):
        await execute_plan(...)

Usage from a logger hook (e.g. inside chat_once):

    ctx = current_billing_context()
    if ctx is not None:
        await log_llm_transaction(response, billing_context=ctx, ...)
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from typing import Optional

from .context import BillingContext

logger = logging.getLogger(__name__)

_BILLING_CTX: ContextVar[Optional[BillingContext]] = ContextVar(
    "smartest_billing_ctx",
    default=None,
)


def current_billing_context() -> Optional[BillingContext]:
    return _BILLING_CTX.get()


def set_billing_context(ctx: Optional[BillingContext]) -> Token:
    return _BILLING_CTX.set(ctx)


def reset_billing_context(token: Token) -> None:
    try:
        _BILLING_CTX.reset(token)
    except (LookupError, ValueError):
        pass


@asynccontextmanager
async def use_billing_context(ctx: Optional[BillingContext]):
    token = set_billing_context(ctx)
    try:
        yield ctx
    finally:
        reset_billing_context(token)
