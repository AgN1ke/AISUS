from __future__ import annotations


def current_runtime_user_settings() -> dict[str, str]:
    try:
        from billing.runtime import current_billing_context
    except Exception:
        return {}

    ctx = current_billing_context()
    if ctx is None:
        return {}
    meta = getattr(ctx, "meta", None)
    if not isinstance(meta, dict):
        return {}
    settings = meta.get("user_settings")
    return settings if isinstance(settings, dict) else {}
