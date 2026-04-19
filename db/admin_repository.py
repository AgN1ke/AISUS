from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .accounts_repository import create_account, credit_account, get_account_by_owner
from .chats_repository import get_chats_by_owner
from .connection import fetchall, fetchone
from .topups_repository import create_topup, list_topups_for_account
from .transactions_repository import get_recent_transactions, list_turns_for_account
from .users_repository import get_user, get_user_settings


_USER_SORT_MAP = {
    "username": "u.tg_username",
    "first_name": "u.first_name",
    "first_seen_at": "u.first_seen_at",
    "last_seen_at": "u.last_seen_at",
    "balance_uah": "a.balance_uah",
    "total_spent_uah": "a.total_spent_uah",
    "total_topup_uah": "a.total_topup_uah",
    "turns_total": "turns_total",
    "turns_today": "turns_today",
    "turns_7d": "turns_7d",
    "tokens_in": "tokens_in",
    "tokens_out": "tokens_out",
    "favorite_model": "favorite_model",
}

_TX_SORT_MAP = {
    "created_at": "tx.created_at",
    "id": "tx.id",
    "user_id": "tx.user_id",
    "chat_id": "tx.chat_id",
    "capability": "tx.capability",
    "provider": "tx.provider",
    "model": "tx.model",
    "kind": "tx.kind",
    "status": "tx.status",
    "cost_uah": "tx.cost_uah",
    "latency_ms": "tx.latency_ms",
    "tokens_in": "tx.tokens_in",
    "tokens_out": "tx.tokens_out",
}

_CHAT_SORT_MAP = {
    "chat_id": "c.chat_id",
    "title": "c.title",
    "tg_chat_type": "c.tg_chat_type",
    "owner": "owner_label",
    "access_mode": "cp.access_mode",
    "per_user_daily_cap_uah": "cp.per_user_daily_cap_uah",
    "per_chat_daily_cap_uah": "cp.per_chat_daily_cap_uah",
    "spent_today_uah": "spent_today_uah",
    "spent_total_uah": "spent_total_uah",
    "last_turn_at": "last_turn_at",
}

_TOPUP_SORT_MAP = {
    "created_at": "t.created_at",
    "paid_at": "t.paid_at",
    "id": "t.id",
    "amount_uah": "t.amount_uah",
    "status": "t.status",
    "user_id": "u.user_id",
    "username": "u.tg_username",
}

_KEY_SORT_MAP = {
    "id": "pk.id",
    "provider": "pk.provider",
    "label": "pk.label",
    "status": "pk.status",
    "rpm_limit": "pk.rpm_limit",
    "tpm_limit": "pk.tpm_limit",
    "total_requests": "pk.total_requests",
    "total_spent_usd": "pk.total_spent_usd",
    "last_used_at": "pk.last_used_at",
    "last_error_at": "pk.last_error_at",
    "cooldown_until": "pk.cooldown_until",
    "created_at": "pk.created_at",
}


def normalize_user_sort(sort: str | None, direction: str | None) -> tuple[str, str]:
    sort_key = (sort or "last_seen_at").strip().lower()
    if sort_key not in _USER_SORT_MAP:
        sort_key = "last_seen_at"
    sort_dir = "asc" if (direction or "").strip().lower() == "asc" else "desc"
    return sort_key, sort_dir


def normalize_transaction_sort(sort: str | None, direction: str | None) -> tuple[str, str]:
    sort_key = (sort or "created_at").strip().lower()
    if sort_key not in _TX_SORT_MAP:
        sort_key = "created_at"
    sort_dir = "asc" if (direction or "").strip().lower() == "asc" else "desc"
    return sort_key, sort_dir


def normalize_chat_sort(sort: str | None, direction: str | None) -> tuple[str, str]:
    sort_key = (sort or "last_turn_at").strip().lower()
    if sort_key not in _CHAT_SORT_MAP:
        sort_key = "last_turn_at"
    sort_dir = "asc" if (direction or "").strip().lower() == "asc" else "desc"
    return sort_key, sort_dir


def normalize_topup_sort(sort: str | None, direction: str | None) -> tuple[str, str]:
    sort_key = (sort or "created_at").strip().lower()
    if sort_key not in _TOPUP_SORT_MAP:
        sort_key = "created_at"
    sort_dir = "asc" if (direction or "").strip().lower() == "asc" else "desc"
    return sort_key, sort_dir


def normalize_key_sort(sort: str | None, direction: str | None) -> tuple[str, str]:
    sort_key = (sort or "provider").strip().lower()
    if sort_key not in _KEY_SORT_MAP:
        sort_key = "provider"
    sort_dir = "asc" if (direction or "").strip().lower() == "asc" else "desc"
    return sort_key, sort_dir


def _build_transaction_filters(
    *,
    query: str = "",
    capability: str = "",
    provider: str = "",
    model: str = "",
    status: str = "",
    kind: str = "",
    date_from: str = "",
    date_to: str = "",
) -> tuple[str, list[object]]:
    clauses: list[str] = []
    args: list[object] = []

    search = (query or "").strip()
    if search:
        like = f"%{search}%"
        clauses.append(
            "("
            "CAST(tx.id AS CHAR) LIKE %s OR CAST(tx.turn_id AS CHAR) LIKE %s OR "
            "CAST(tx.user_id AS CHAR) LIKE %s OR CAST(tx.chat_id AS CHAR) LIKE %s OR "
            "u.tg_username LIKE %s OR u.first_name LIKE %s OR u.last_name LIKE %s OR "
            "tx.capability LIKE %s OR tx.provider LIKE %s OR tx.model LIKE %s"
            ")"
        )
        args.extend([like] * 10)

    capability_clean = (capability or "").strip()
    if capability_clean:
        clauses.append("tx.capability = %s")
        args.append(capability_clean)

    provider_clean = (provider or "").strip()
    if provider_clean:
        clauses.append("tx.provider = %s")
        args.append(provider_clean)

    model_clean = (model or "").strip()
    if model_clean:
        clauses.append("tx.model = %s")
        args.append(model_clean)

    status_clean = (status or "").strip()
    if status_clean:
        clauses.append("tx.status = %s")
        args.append(status_clean)

    kind_clean = (kind or "").strip()
    if kind_clean:
        clauses.append("tx.kind = %s")
        args.append(kind_clean)

    date_from_clean = (date_from or "").strip()
    if date_from_clean:
        clauses.append("tx.created_at >= %s")
        args.append(f"{date_from_clean} 00:00:00")

    date_to_clean = (date_to or "").strip()
    if date_to_clean:
        clauses.append("tx.created_at < DATE_ADD(%s, INTERVAL 1 DAY)")
        args.append(date_to_clean)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where_sql, args


def _build_chat_filters(
    *,
    query: str = "",
    access_mode: str = "",
    tg_chat_type: str = "",
) -> tuple[str, list[object]]:
    clauses: list[str] = []
    args: list[object] = []

    search = (query or "").strip()
    if search:
        like = f"%{search}%"
        clauses.append(
            "("
            "CAST(c.chat_id AS CHAR) LIKE %s OR c.title LIKE %s OR "
            "owner.tg_username LIKE %s OR owner.first_name LIKE %s OR owner.last_name LIKE %s"
            ")"
        )
        args.extend([like, like, like, like, like])

    access_mode_clean = (access_mode or "").strip()
    if access_mode_clean:
        clauses.append("cp.access_mode = %s")
        args.append(access_mode_clean)

    chat_type_clean = (tg_chat_type or "").strip()
    if chat_type_clean:
        clauses.append("c.tg_chat_type = %s")
        args.append(chat_type_clean)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where_sql, args


def _build_topup_filters(
    *,
    query: str = "",
    status: str = "",
    date_from: str = "",
    date_to: str = "",
) -> tuple[str, list[object]]:
    clauses: list[str] = []
    args: list[object] = []

    search = (query or "").strip()
    if search:
        like = f"%{search}%"
        clauses.append(
            "("
            "CAST(t.id AS CHAR) LIKE %s OR CAST(a.account_id AS CHAR) LIKE %s OR "
            "CAST(u.user_id AS CHAR) LIKE %s OR u.tg_username LIKE %s OR "
            "u.first_name LIKE %s OR u.last_name LIKE %s OR t.note LIKE %s OR "
            "t.monopay_invoice_id LIKE %s"
            ")"
        )
        args.extend([like] * 8)

    status_clean = (status or "").strip()
    if status_clean:
        clauses.append("t.status = %s")
        args.append(status_clean)

    date_from_clean = (date_from or "").strip()
    if date_from_clean:
        clauses.append("t.created_at >= %s")
        args.append(f"{date_from_clean} 00:00:00")

    date_to_clean = (date_to or "").strip()
    if date_to_clean:
        clauses.append("t.created_at < DATE_ADD(%s, INTERVAL 1 DAY)")
        args.append(date_to_clean)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where_sql, args


def _build_key_filters(
    *,
    query: str = "",
    provider: str = "",
    status: str = "",
) -> tuple[str, list[object]]:
    clauses: list[str] = []
    args: list[object] = []

    search = (query or "").strip()
    if search:
        like = f"%{search}%"
        clauses.append(
            "("
            "CAST(pk.id AS CHAR) LIKE %s OR pk.provider LIKE %s OR "
            "pk.label LIKE %s OR pk.key_hash LIKE %s OR pk.last_error LIKE %s"
            ")"
        )
        args.extend([like, like, like, like, like])

    provider_clean = (provider or "").strip()
    if provider_clean:
        clauses.append("pk.provider = %s")
        args.append(provider_clean)

    status_clean = (status or "").strip()
    if status_clean:
        clauses.append("pk.status = %s")
        args.append(status_clean)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where_sql, args


async def list_users_with_stats(
    *,
    sort: str = "last_seen_at",
    direction: str = "desc",
    query: str = "",
    limit: int = 200,
) -> list[dict]:
    sort_key, sort_dir = normalize_user_sort(sort, direction)
    order_sql = _USER_SORT_MAP[sort_key]
    where_sql = ""
    args: list[object] = []
    search = (query or "").strip()
    if search:
        like = f"%{search}%"
        where_sql = (
            "WHERE (CAST(u.user_id AS CHAR) LIKE %s OR u.tg_username LIKE %s "
            "OR u.first_name LIKE %s OR u.last_name LIKE %s)"
        )
        args.extend([like, like, like, like])
    args.append(int(limit))
    sql = f"""
        SELECT
          u.user_id,
          u.tg_username,
          u.first_name,
          u.last_name,
          u.first_seen_at,
          u.last_seen_at,
          a.account_id,
          a.balance_uah,
          a.total_spent_uah,
          a.total_topup_uah,
          a.status AS account_status,
          COALESCE(t.turns_total, 0) AS turns_total,
          COALESCE(t.turns_today, 0) AS turns_today,
          COALESCE(t.turns_7d, 0) AS turns_7d,
          COALESCE(tx.tokens_in, 0) AS tokens_in,
          COALESCE(tx.tokens_out, 0) AS tokens_out,
          (
            SELECT tx2.model
            FROM transactions tx2
            WHERE tx2.user_id = u.user_id
              AND tx2.model IS NOT NULL
              AND tx2.model <> ''
            GROUP BY tx2.model
            ORDER BY COUNT(*) DESC, MAX(tx2.created_at) DESC
            LIMIT 1
          ) AS favorite_model
        FROM users u
        LEFT JOIN accounts a ON a.account_id = (
          SELECT a2.account_id
          FROM accounts a2
          WHERE a2.owner_user_id = u.user_id
            AND a2.status <> 'deleted'
          ORDER BY a2.account_id ASC
          LIMIT 1
        )
        LEFT JOIN (
          SELECT
            user_id,
            COUNT(*) AS turns_total,
            SUM(CASE WHEN created_at >= CURDATE() THEN 1 ELSE 0 END) AS turns_today,
            SUM(CASE WHEN created_at >= DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 7 DAY) THEN 1 ELSE 0 END) AS turns_7d
          FROM turns
          GROUP BY user_id
        ) t ON t.user_id = u.user_id
        LEFT JOIN (
          SELECT
            user_id,
            SUM(tokens_in) AS tokens_in,
            SUM(tokens_out) AS tokens_out
          FROM transactions
          GROUP BY user_id
        ) tx ON tx.user_id = u.user_id
        {where_sql}
        ORDER BY {order_sql} {sort_dir}, u.user_id ASC
        LIMIT %s
    """
    return await fetchall(sql, tuple(args)) or []


async def list_transactions_with_stats(
    *,
    sort: str = "created_at",
    direction: str = "desc",
    query: str = "",
    capability: str = "",
    provider: str = "",
    model: str = "",
    status: str = "",
    kind: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 300,
) -> list[dict]:
    sort_key, sort_dir = normalize_transaction_sort(sort, direction)
    where_sql, args = _build_transaction_filters(
        query=query,
        capability=capability,
        provider=provider,
        model=model,
        status=status,
        kind=kind,
        date_from=date_from,
        date_to=date_to,
    )
    args.append(int(limit))
    sql = f"""
        SELECT
          tx.id,
          tx.turn_id,
          tx.account_id,
          tx.chat_id,
          tx.user_id,
          tx.kind,
          tx.capability,
          tx.provider,
          tx.model,
          tx.tokens_in,
          tx.tokens_out,
          tx.unit_count,
          tx.cost_usd,
          tx.cost_uah,
          tx.markup_pct,
          tx.key_id,
          tx.latency_ms,
          tx.status,
          tx.error_text,
          tx.created_at,
          u.tg_username,
          u.first_name,
          u.last_name,
          c.title AS chat_title,
          c.tg_chat_type
        FROM transactions tx
        LEFT JOIN users u ON u.user_id = tx.user_id
        LEFT JOIN chats c ON c.chat_id = tx.chat_id
        {where_sql}
        ORDER BY {_TX_SORT_MAP[sort_key]} {sort_dir}, tx.id DESC
        LIMIT %s
    """
    return await fetchall(sql, tuple(args)) or []


async def get_transactions_summary(
    *,
    query: str = "",
    capability: str = "",
    provider: str = "",
    model: str = "",
    status: str = "",
    kind: str = "",
    date_from: str = "",
    date_to: str = "",
) -> dict:
    where_sql, args = _build_transaction_filters(
        query=query,
        capability=capability,
        provider=provider,
        model=model,
        status=status,
        kind=kind,
        date_from=date_from,
        date_to=date_to,
    )
    sql = f"""
        SELECT
          COUNT(*) AS total_rows,
          COALESCE(SUM(tx.cost_uah), 0) AS total_cost_uah,
          COALESCE(SUM(tx.tokens_in), 0) AS total_tokens_in,
          COALESCE(SUM(tx.tokens_out), 0) AS total_tokens_out,
          COALESCE(SUM(CASE WHEN tx.status = 'success' THEN 1 ELSE 0 END), 0) AS success_count,
          COALESCE(SUM(CASE WHEN tx.status = 'failed' THEN 1 ELSE 0 END), 0) AS failed_count,
          COALESCE(SUM(CASE WHEN tx.status = 'rate_limited' THEN 1 ELSE 0 END), 0) AS rate_limited_count,
          ROUND(AVG(CASE WHEN tx.latency_ms IS NOT NULL THEN tx.latency_ms END), 1) AS avg_latency_ms
        FROM transactions tx
        LEFT JOIN users u ON u.user_id = tx.user_id
        {where_sql}
    """
    return await fetchone(sql, tuple(args)) or {
        "total_rows": 0,
        "total_cost_uah": 0,
        "total_tokens_in": 0,
        "total_tokens_out": 0,
        "success_count": 0,
        "failed_count": 0,
        "rate_limited_count": 0,
        "avg_latency_ms": None,
    }


async def list_chats_with_stats(
    *,
    sort: str = "last_turn_at",
    direction: str = "desc",
    query: str = "",
    access_mode: str = "",
    tg_chat_type: str = "",
    limit: int = 300,
) -> list[dict]:
    sort_key, sort_dir = normalize_chat_sort(sort, direction)
    where_sql, args = _build_chat_filters(
        query=query,
        access_mode=access_mode,
        tg_chat_type=tg_chat_type,
    )
    args.append(int(limit))
    sql = f"""
        SELECT
          c.chat_id,
          c.title,
          c.lang,
          c.tg_chat_type,
          c.owner_account_id,
          cp.access_mode,
          cp.per_user_daily_cap_uah,
          cp.per_chat_daily_cap_uah,
          cp.alert_threshold_pct,
          owner.user_id AS owner_user_id,
          owner.tg_username AS owner_username,
          owner.first_name AS owner_first_name,
          owner.last_name AS owner_last_name,
          CONCAT_WS(' · ',
            CASE WHEN owner.tg_username IS NOT NULL AND owner.tg_username <> '' THEN CONCAT('@', owner.tg_username) ELSE NULL END,
            NULLIF(CONCAT_WS(' ', owner.first_name, owner.last_name), '')
          ) AS owner_label,
          COALESCE(tx.spent_today_uah, 0) AS spent_today_uah,
          COALESCE(tx.spent_total_uah, 0) AS spent_total_uah,
          tx.last_turn_at,
          COALESCE(acc.allowed_count, 0) AS allowed_count,
          COALESCE(acc.banned_count, 0) AS banned_count,
          COALESCE(acc.delegated_admin_count, 0) AS delegated_admin_count
        FROM chats c
        LEFT JOIN chat_policies cp ON cp.chat_id = c.chat_id
        LEFT JOIN accounts a ON a.account_id = c.owner_account_id
        LEFT JOIN users owner ON owner.user_id = a.owner_user_id
        LEFT JOIN (
          SELECT
            chat_id,
            SUM(CASE WHEN created_at >= CURDATE() THEN cost_uah ELSE 0 END) AS spent_today_uah,
            SUM(cost_uah) AS spent_total_uah,
            MAX(created_at) AS last_turn_at
          FROM transactions
          GROUP BY chat_id
        ) tx ON tx.chat_id = c.chat_id
        LEFT JOIN (
          SELECT
            chat_id,
            SUM(CASE WHEN role = 'allowed' THEN 1 ELSE 0 END) AS allowed_count,
            SUM(CASE WHEN role = 'banned' THEN 1 ELSE 0 END) AS banned_count,
            SUM(CASE WHEN role = 'delegated_admin' THEN 1 ELSE 0 END) AS delegated_admin_count
          FROM chat_access
          GROUP BY chat_id
        ) acc ON acc.chat_id = c.chat_id
        {where_sql}
        ORDER BY {_CHAT_SORT_MAP[sort_key]} {sort_dir}, c.chat_id ASC
        LIMIT %s
    """
    return await fetchall(sql, tuple(args)) or []


async def get_chats_summary(
    *,
    query: str = "",
    access_mode: str = "",
    tg_chat_type: str = "",
) -> dict:
    where_sql, args = _build_chat_filters(
        query=query,
        access_mode=access_mode,
        tg_chat_type=tg_chat_type,
    )
    sql = f"""
        SELECT
          COUNT(*) AS total_chats,
          COALESCE(SUM(CASE WHEN c.owner_account_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS owned_chats,
          COALESCE(SUM(CASE WHEN cp.access_mode IS NOT NULL AND cp.access_mode <> 'open' THEN 1 ELSE 0 END), 0) AS restricted_chats,
          COALESCE(SUM(tx.spent_today_uah), 0) AS total_spent_today_uah,
          COALESCE(SUM(tx.spent_total_uah), 0) AS total_spent_uah
        FROM chats c
        LEFT JOIN chat_policies cp ON cp.chat_id = c.chat_id
        LEFT JOIN accounts a ON a.account_id = c.owner_account_id
        LEFT JOIN users owner ON owner.user_id = a.owner_user_id
        LEFT JOIN (
          SELECT
            chat_id,
            SUM(CASE WHEN created_at >= CURDATE() THEN cost_uah ELSE 0 END) AS spent_today_uah,
            SUM(cost_uah) AS spent_total_uah
          FROM transactions
          GROUP BY chat_id
        ) tx ON tx.chat_id = c.chat_id
        {where_sql}
    """
    return await fetchone(sql, tuple(args)) or {
        "total_chats": 0,
        "owned_chats": 0,
        "restricted_chats": 0,
        "total_spent_today_uah": 0,
        "total_spent_uah": 0,
    }


async def list_topups_with_stats(
    *,
    sort: str = "created_at",
    direction: str = "desc",
    query: str = "",
    status: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 300,
) -> list[dict]:
    sort_key, sort_dir = normalize_topup_sort(sort, direction)
    where_sql, args = _build_topup_filters(
        query=query,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    args.append(int(limit))
    sql = f"""
        SELECT
          t.id,
          t.account_id,
          t.amount_uah,
          t.monopay_invoice_id,
          t.monopay_url,
          t.status,
          t.note,
          t.created_at,
          t.paid_at,
          u.user_id,
          u.tg_username,
          u.first_name,
          u.last_name
        FROM topups t
        LEFT JOIN accounts a ON a.account_id = t.account_id
        LEFT JOIN users u ON u.user_id = a.owner_user_id
        {where_sql}
        ORDER BY {_TOPUP_SORT_MAP[sort_key]} {sort_dir}, t.id DESC
        LIMIT %s
    """
    return await fetchall(sql, tuple(args)) or []


async def get_topups_summary(
    *,
    query: str = "",
    status: str = "",
    date_from: str = "",
    date_to: str = "",
) -> dict:
    where_sql, args = _build_topup_filters(
        query=query,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    sql = f"""
        SELECT
          COUNT(*) AS total_topups,
          COALESCE(SUM(t.amount_uah), 0) AS total_amount_uah,
          COALESCE(SUM(CASE WHEN t.status = 'success' THEN t.amount_uah ELSE 0 END), 0) AS success_amount_uah,
          COALESCE(SUM(CASE WHEN t.status = 'manual' THEN t.amount_uah ELSE 0 END), 0) AS manual_amount_uah,
          COALESCE(SUM(CASE WHEN t.status = 'pending' THEN 1 ELSE 0 END), 0) AS pending_count
        FROM topups t
        LEFT JOIN accounts a ON a.account_id = t.account_id
        LEFT JOIN users u ON u.user_id = a.owner_user_id
        {where_sql}
    """
    return await fetchone(sql, tuple(args)) or {
        "total_topups": 0,
        "total_amount_uah": 0,
        "success_amount_uah": 0,
        "manual_amount_uah": 0,
        "pending_count": 0,
    }


async def list_provider_keys_with_stats(
    *,
    sort: str = "provider",
    direction: str = "asc",
    query: str = "",
    provider: str = "",
    status: str = "",
    limit: int = 300,
) -> list[dict]:
    sort_key, sort_dir = normalize_key_sort(sort, direction)
    where_sql, args = _build_key_filters(
        query=query,
        provider=provider,
        status=status,
    )
    args.append(int(limit))
    sql = f"""
        SELECT
          pk.id,
          pk.provider,
          pk.label,
          pk.key_hash,
          pk.encrypted_key,
          pk.status,
          pk.rpm_limit,
          pk.tpm_limit,
          pk.total_requests,
          pk.total_spent_usd,
          pk.last_used_at,
          pk.last_error_at,
          pk.last_error,
          pk.cooldown_until,
          pk.created_at
        FROM provider_keys pk
        {where_sql}
        ORDER BY {_KEY_SORT_MAP[sort_key]} {sort_dir}, pk.id DESC
        LIMIT %s
    """
    return await fetchall(sql, tuple(args)) or []


async def get_provider_keys_summary(
    *,
    query: str = "",
    provider: str = "",
    status: str = "",
) -> dict:
    where_sql, args = _build_key_filters(
        query=query,
        provider=provider,
        status=status,
    )
    sql = f"""
        SELECT
          COUNT(*) AS total_keys,
          COALESCE(SUM(CASE WHEN pk.status = 'active' THEN 1 ELSE 0 END), 0) AS active_keys,
          COALESCE(SUM(CASE WHEN pk.status = 'disabled' THEN 1 ELSE 0 END), 0) AS disabled_keys,
          COALESCE(SUM(CASE WHEN pk.status = 'rate_limited' THEN 1 ELSE 0 END), 0) AS rate_limited_keys,
          COALESCE(SUM(CASE WHEN pk.status = 'invalid' THEN 1 ELSE 0 END), 0) AS invalid_keys,
          COALESCE(SUM(pk.total_requests), 0) AS total_requests,
          COALESCE(SUM(pk.total_spent_usd), 0) AS total_spent_usd
        FROM provider_keys pk
        {where_sql}
    """
    return await fetchone(sql, tuple(args)) or {
        "total_keys": 0,
        "active_keys": 0,
        "disabled_keys": 0,
        "rate_limited_keys": 0,
        "invalid_keys": 0,
        "total_requests": 0,
        "total_spent_usd": 0,
    }


async def get_user_admin_detail(user_id: int) -> Optional[dict]:
    sql = """
        SELECT
          u.user_id,
          u.tg_username,
          u.first_name,
          u.last_name,
          u.lang_code,
          u.first_seen_at,
          u.last_seen_at,
          a.account_id,
          a.balance_uah,
          a.total_spent_uah,
          a.total_topup_uah,
          a.status AS account_status,
          (
            SELECT COUNT(*)
            FROM chats c
            WHERE c.owner_account_id = a.account_id
          ) AS owned_chats_count,
          (
            SELECT COUNT(*)
            FROM turns t
            WHERE t.user_id = u.user_id
          ) AS turns_total,
          (
            SELECT COUNT(*)
            FROM turns t
            WHERE t.user_id = u.user_id
              AND t.created_at >= CURDATE()
          ) AS turns_today,
          (
            SELECT COALESCE(SUM(tx.tokens_in), 0)
            FROM transactions tx
            WHERE tx.user_id = u.user_id
          ) AS tokens_in,
          (
            SELECT COALESCE(SUM(tx.tokens_out), 0)
            FROM transactions tx
            WHERE tx.user_id = u.user_id
          ) AS tokens_out
        FROM users u
        LEFT JOIN accounts a ON a.account_id = (
          SELECT a2.account_id
          FROM accounts a2
          WHERE a2.owner_user_id = u.user_id
            AND a2.status <> 'deleted'
          ORDER BY a2.account_id ASC
          LIMIT 1
        )
        WHERE u.user_id = %s
        LIMIT 1
    """
    row = await fetchone(sql, (int(user_id),))
    if not row:
        return None
    account_id = row.get("account_id")
    row["owned_chats"] = await get_chats_by_owner(int(account_id)) if account_id else []
    row["recent_turns"] = (
        await list_turns_for_account(int(account_id), limit=20) if account_id else []
    )
    row["recent_transactions"] = (
        await get_recent_transactions(int(account_id), limit=50) if account_id else []
    )
    row["recent_topups"] = (
        await list_topups_for_account(int(account_id), limit=20) if account_id else []
    )
    row["user_settings"] = await get_user_settings(int(user_id))
    return row


async def credit_account_admin(
    *,
    user_id: int,
    amount_uah: Decimal | float | int,
    note: str,
    actor: str,
) -> dict:
    user = await get_user(int(user_id))
    if not user:
        raise ValueError(f"user {user_id} not found")

    amount = Decimal(str(amount_uah))
    if amount <= 0:
        raise ValueError("amount must be positive")
    note_clean = (note or "").strip()
    if not note_clean:
        raise ValueError("note is required")

    account = await get_account_by_owner(int(user_id))
    if not account:
        account_id = await create_account(int(user_id), initial_balance_uah=0)
        account = {"account_id": account_id}

    account_id = int(account["account_id"])
    topup_id = await create_topup(
        account_id=account_id,
        amount_uah=amount,
        status="manual",
        note=f"admin_manual:{actor}:{note_clean}"[:255],
    )
    new_balance = await credit_account(
        account_id,
        amount,
        count_as_topup=True,
    )
    return {
        "user": user,
        "account_id": account_id,
        "topup_id": topup_id,
        "amount_uah": amount,
        "new_balance_uah": new_balance,
    }
