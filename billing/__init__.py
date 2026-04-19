"""Billing layer for Smartest multitenant runtime.

Provides:
- BillingContext: per-turn accounting identity passed through the pipeline
- pricing: USD→UAH conversion with markup, pricing table CRUD
- gateway: wraps LLM calls with transaction logging
- keypool: encrypted provider key rotation (Stage 2 scaffold, full wiring in later stage)
- crypto: AES-backed encryption for provider keys at rest

See docs/project/multitenant-plan.md for the design.
"""
from __future__ import annotations

from .context import BillingContext

__all__ = ["BillingContext"]
