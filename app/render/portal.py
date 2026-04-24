"""Portal page renderers (user-facing, logged-in context).

Split out from ``app.admin_ui`` to keep the module tree manageable. Helpers
live in ``admin_ui``; we access them through a lazy resolver ``_au()`` so
direct ``import app.render.portal`` paths don't hit a circular import.
"""
from __future__ import annotations

import html
import json


def _au():
    from app import admin_ui
    return admin_ui


def _portal_flash_html(flash: str, flash_kind: str) -> str:
    return _au()._flash_block(flash, flash_kind)


def render_user_portal_landing(
    values: dict[str, str],
    *,
    flash: str = "",
    flash_kind: str = "info",
    login_nonce: str = "",
) -> str:
    client_id = _au().telegram_login_client_id(values)
    flash_html = _portal_flash_html(flash, flash_kind)
    login_ready = bool(client_id)
    login_note = (
        "Telegram Login library готова: браузер отримує `id_token`, а бекенд верифікує його через JWKS."
        if login_ready
        else "Telegram Login ще не готовий: потрібен валідний `TG_BOT_TOKEN` або `TELEGRAM_LOGIN_CLIENT_ID`."
    )
    login_cta = (
        '<button class="btn btn-main" type="button" id="tg-login-btn">Увійти через Telegram</button>'
        if login_ready
        else '<button class="btn btn-main" type="button" disabled>Увійти через Telegram</button>'
    )
    client_id_js = json.dumps(client_id, ensure_ascii=False)
    login_nonce_js = json.dumps(login_nonce, ensure_ascii=False)
    return f"""{_au()._shared_head("Smartest Portal", extra_head='<script src="https://oauth.telegram.org/js/telegram-login.js?3" async></script>')}
<body>
<script>window.SmartestTelegram = {{ client_id: {client_id_js}, nonce: {login_nonce_js} }};</script>
<script src="/static/admin.js" defer></script>
<div class="portal-landing">
  <div class="ctx-badge ctx-badge--portal">Portal</div>
  {flash_html}
  <section class="hero">
    <div class="card">
      <h1>Smartest<br>Portal</h1>
      <p>Користувацький портал для multitenant-бота: баланс, історія turn-ів, деталізація витрат і персональні налаштування. Вхід іде через нову Telegram Login library: popup повертає <code>id_token</code>, а бекенд верифікує його через JWKS.</p>
      <div class="cta">
        {login_cta}
      </div>
      <div id="tg-login-status" class="status">{html.escape(login_note)}</div>
      <div class="foot">
        <span class="mono">client_id: {html.escape(client_id or '—')}</span>
        <span class="mono">endpoint: /auth/telegram</span>
      </div>
    </div>
    <div class="card meta">
      <div class="meta-item"><span>Що вже є</span>Баланс, історія turn-ів, turn breakdown і user settings.</div>
      <div class="meta-item"><span>Що ще далі</span>Telegram Login для `/admin`, topup flows і повний portal polish.</div>
      <div class="meta-item"><span>Важливо</span>Для login потрібні Allowed URLs у `@BotFather → Web Login`: домен порталу. <code>client_secret</code> для library-flow не потрібний.</div>
    </div>
  </section>
  <div class="portal-legal-links">
    <a href="/tos">Умови користування</a> ·
    <a href="/privacy">Політика конфіденційності</a> ·
    <a href="/refund">Політика повернення коштів</a>
  </div>
</div>
</body>
</html>"""


def render_portal_shell(
    *,
    title: str,
    user: dict,
    body: str,
    flash: str = "",
    flash_kind: str = "info",
) -> str:
    flash_html = _portal_flash_html(flash, flash_kind)
    display_name = (
        user.get("first_name")
        or user.get("tg_username")
        or f"user {user.get('user_id')}"
    )
    safe_name = html.escape(str(display_name))
    safe_username = html.escape("@" + user["tg_username"]) if user.get("tg_username") else "—"
    admin_link = '<a class="nav-cross" href="/admin">В адмінку</a>' if user.get("is_admin") else ""
    return f"""{_au()._shared_head(f"{title} · Smartest")}
<body>
<div class="wrap">
  <div class="ctx-badge ctx-badge--portal">Portal</div>
  <div class="topbar">
    <div>
      <h1>{html.escape(title)}</h1>
      <p>{safe_name} · {safe_username}</p>
    </div>
    <div class="nav">
      <a href="/">Огляд</a>
      <a href="/history">Історія</a>
      <a href="/settings">Налаштування</a>
      <a href="/topup">Поповнення</a>
      {admin_link}
      <form class="nav-form" method="post" action="/logout">
        <button type="submit">Вийти</button>
      </form>
    </div>
  </div>
  {flash_html}
  {body}
  <div class="portal-legal-links">
    <a href="/tos">Умови користування</a> ·
    <a href="/privacy">Політика конфіденційності</a> ·
    <a href="/refund">Політика повернення коштів</a>
  </div>
</div>
</body>
</html>"""


def render_portal_dashboard_page(
    user: dict,
    account: dict,
    turns: list[dict],
    settings: dict[str, str],
    *,
    flash: str = "",
    flash_kind: str = "info",
) -> str:
    rows = ""
    for turn in turns:
        rows += f"""<tr>
          <td class="mono"><a href="/history/{html.escape(turn['turn_id'])}">{html.escape(turn['turn_id'][:8])}</a></td>
          <td>{html.escape(str(turn.get('capability') or '—'))}</td>
          <td>{html.escape(str(turn.get('route') or '—'))}</td>
          <td>{html.escape(str(turn.get('status') or '—'))}</td>
          <td>{_au()._fmt_money(turn.get('total_cost_uah'))} грн</td>
          <td>{_au()._fmt_dt(turn.get('created_at'))}</td>
        </tr>"""
    if not rows:
        rows = '<tr><td colspan="6" class="empty">Ще немає жодного turn-а.</td></tr>'
    settings_preview = "".join(
        f'<span class="tag">{html.escape(key)}={html.escape(str(value))}</span> '
        for key, value in sorted(settings.items())[:6]
    ) or '<span class="empty">user_settings ще порожні.</span>'
    body = f"""
<section class="panel">
  <h2>Огляд акаунта</h2>
  <div class="meta-grid">
    <div class="stat"><span class="lbl">Account ID</span><div class="val mono">{html.escape(str(account.get('account_id')))}</div></div>
    <div class="stat"><span class="lbl">Баланс</span><div class="val">{_au()._fmt_money(account.get('balance_uah'))} грн</div></div>
    <div class="stat"><span class="lbl">Витрачено всього</span><div class="val">{_au()._fmt_money(account.get('total_spent_uah'))} грн</div></div>
    <div class="stat"><span class="lbl">Поповнено всього</span><div class="val">{_au()._fmt_money(account.get('total_topup_uah'))} грн</div></div>
  </div>
</section>
<section class="panel">
  <h2>Персональні налаштування</h2>
  <div>{settings_preview}</div>
</section>
<section class="panel">
  <h2>Останні turn-и</h2>
  <table class="data-table">
    <thead><tr><th>Turn</th><th>Capability</th><th>Route</th><th>Status</th><th>Cost</th><th>Created</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>"""
    return render_portal_shell(
        title="Smartest Portal",
        user=user,
        body=body,
        flash=flash,
        flash_kind=flash_kind,
    )


def render_portal_history_page(
    user: dict,
    account: dict,
    turns: list[dict],
    *,
    flash: str = "",
    flash_kind: str = "info",
) -> str:
    rows = ""
    for turn in turns:
        preview = html.escape(str(turn.get("user_message_text") or "")[:120] or "—")
        rows += f"""<tr>
          <td class="mono"><a href="/history/{html.escape(turn['turn_id'])}">{html.escape(turn['turn_id'])}</a></td>
          <td>{html.escape(str(turn.get('capability') or '—'))}</td>
          <td>{html.escape(str(turn.get('status') or '—'))}</td>
          <td>{_au()._fmt_money(turn.get('total_cost_uah'))} грн</td>
          <td>{preview}</td>
          <td>{_au()._fmt_dt(turn.get('created_at'))}</td>
        </tr>"""
    if not rows:
        rows = '<tr><td colspan="6" class="empty">Історія ще порожня.</td></tr>'
    body = f"""
<section class="panel">
  <h2>Історія turn-ів</h2>
  <p class="muted">Account <span class="mono">{html.escape(str(account.get('account_id')))}</span></p>
  <table class="data-table">
    <thead><tr><th>Turn ID</th><th>Capability</th><th>Status</th><th>Cost</th><th>User text</th><th>Created</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>"""
    return render_portal_shell(
        title="Історія turn-ів",
        user=user,
        body=body,
        flash=flash,
        flash_kind=flash_kind,
    )


def render_portal_turn_page(
    user: dict,
    turn: dict | None,
    transactions: list[dict],
    ambiguous_matches: list[dict],
    *,
    flash: str = "",
    flash_kind: str = "info",
) -> str:
    if ambiguous_matches:
        items = "".join(
            f'<li><a href="/history/{html.escape(match["turn_id"])}">{html.escape(match["turn_id"])}</a> · {_au()._fmt_dt(match.get("created_at"))}</li>'
            for match in ambiguous_matches
        )
        body = f"""<section class="panel"><h2>Неоднозначний turn id</h2><p class="muted">Префікс збігається з кількома turn-ами. Уточни повніший id.</p><ul>{items}</ul></section>"""
    elif turn is None:
        body = '<section class="panel"><h2>Turn не знайдено</h2><p class="muted">Для цього акаунта немає turn-а з таким id або префіксом.</p></section>'
    else:
        tx_rows = ""
        for tx in transactions:
            tx_rows += f"""<tr>
              <td>{html.escape(str(tx.get('capability') or '—'))}</td>
              <td>{html.escape(str(tx.get('provider') or '—'))}</td>
              <td>{html.escape(str(tx.get('model') or '—'))}</td>
              <td>{_au()._fmt_int(tx.get('tokens_in'))}</td>
              <td>{_au()._fmt_int(tx.get('tokens_out'))}</td>
              <td>{_au()._fmt_money(tx.get('cost_uah'), places=4)} грн</td>
              <td>{html.escape(str(tx.get('status') or '—'))}</td>
            </tr>"""
        if not tx_rows:
            tx_rows = '<tr><td colspan="7" class="empty">У цього turn-а ще немає sub-транзакцій.</td></tr>'
        user_text = html.escape(str(turn.get("user_message_text") or "—"))
        body = f"""
<section class="panel">
  <h2>Turn {html.escape(turn['turn_id'])}</h2>
  <div class="meta-grid">
    <div class="stat"><span class="lbl">Status</span><div class="val">{html.escape(str(turn.get('status') or '—'))}</div></div>
    <div class="stat"><span class="lbl">Route</span><div class="val">{html.escape(str(turn.get('route') or '—'))}</div></div>
    <div class="stat"><span class="lbl">Capability</span><div class="val">{html.escape(str(turn.get('capability') or '—'))}</div></div>
    <div class="stat"><span class="lbl">Total cost</span><div class="val">{_au()._fmt_money(turn.get('total_cost_uah'))} грн</div></div>
  </div>
  <p class="muted" style="margin-top:14px;">{user_text}</p>
</section>
<section class="panel">
  <h2>Sub-транзакції</h2>
  <table class="data-table">
    <thead><tr><th>Capability</th><th>Provider</th><th>Model</th><th>In</th><th>Out</th><th>Cost</th><th>Status</th></tr></thead>
    <tbody>{tx_rows}</tbody>
  </table>
</section>"""
    return render_portal_shell(
        title="Turn breakdown",
        user=user,
        body=body,
        flash=flash,
        flash_kind=flash_kind,
    )


def render_portal_settings_page(
    user: dict,
    account: dict,
    settings: dict[str, str],
    catalog: dict,
    *,
    flash: str = "",
    flash_kind: str = "info",
) -> str:
    rows = ""
    for key, value in sorted(settings.items()):
        rows += f"<tr><td class=\"mono\">{html.escape(key)}</td><td>{html.escape(str(value))}</td></tr>"
    if not rows:
        rows = '<tr><td colspan="2" class="empty">Ще немає персональних налаштувань.</td></tr>'
    phone = settings.get("profile_phone_number") or "—"
    group_sections = ""
    for group in catalog.get("groups", []):
        options_html = "".join(
            (
                f'<option value="{html.escape(str(choice.get("value") or ""))}"'
                f'{" selected" if str(choice.get("value") or "") == str(group.get("current_value") or "") else ""}>'
                f'{html.escape(str(choice.get("label") or ""))}</option>'
            )
            for choice in group.get("choices", [])
        )
        group_sections += f"""
    <label class="portal-field">
      <span class="portal-field-title">{html.escape(str(group.get('title') or 'Група'))}</span>
      <small class="portal-help">{html.escape(str(group.get('description') or ''))}</small>
      <select name="{html.escape(str(group.get('field_name') or ''))}">
        {options_html}
      </select>
    </label>"""

    voices = catalog.get("voices", {})
    voice_options_html = "".join(
        (
            f'<option value="{html.escape(str(choice.get("value") or ""))}"'
            f'{" selected" if str(choice.get("value") or "") == str(voices.get("current_value") or "") else ""}>'
            f'{html.escape(str(choice.get("label") or ""))}</option>'
        )
        for choice in voices.get("choices", [])
    )
    personas = catalog.get("personas", {})
    persona_options_html = "".join(
        (
            f'<option value="{html.escape(str(choice.get("value") or ""))}"'
            f'{" selected" if str(choice.get("value") or "") == str(personas.get("current_value") or "") else ""}>'
            f'{html.escape(str(choice.get("label") or ""))}</option>'
        )
        for choice in personas.get("choices", [])
    )
    body = f"""
<section class="panel">
  <h2>Профіль</h2>
  <div class="meta-grid">
    <div class="stat"><span class="lbl">Telegram ID</span><div class="val mono">{html.escape(str(user.get('user_id')))}</div></div>
    <div class="stat"><span class="lbl">Username</span><div class="val">{html.escape('@' + user['tg_username']) if user.get('tg_username') else '—'}</div></div>
    <div class="stat"><span class="lbl">Phone</span><div class="val">{html.escape(str(phone))}</div></div>
    <div class="stat"><span class="lbl">Account</span><div class="val mono">{html.escape(str(account.get('account_id')))}</div></div>
  </div>
</section>
<section class="panel">
  <h2>Персональні налаштування</h2>
  <p class="muted portal-copy">Тут редагуються тільки твої user-specific override-и. Якщо вибрано <b>Server default</b>, runtime бере глобальний server policy.</p>
  <form class="portal-form" method="post" action="/settings">
    <div class="portal-form-grid">
    {group_sections}
    <label class="portal-field">
      <span class="portal-field-title">🎙 Голос</span>
      <small class="portal-help">Окремий user-specific голос для TTS. Якщо лишити Server default, озвучка бере глобальний server policy.</small>
      <select name="{html.escape(str(voices.get('field_name') or 'voice_id'))}">
        {voice_options_html}
      </select>
    </label>
    <label class="portal-field">
      <span class="portal-field-title">🎭 Persona</span>
      <small class="portal-help">Персона впливає на тон і те, як саме бот формулює фінальні відповіді.</small>
      <select name="{html.escape(str(personas.get('field_name') or 'persona_slug'))}">
        {persona_options_html}
      </select>
    </label>
    </div>
    <div class="portal-form-actions">
      <button class="btn btn-main" type="submit">Зберегти</button>
    </div>
  </form>
</section>
<section class="panel">
  <h2>Raw user settings</h2>
  <table class="data-table">
    <thead><tr><th>Key</th><th>Value</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>"""
    return render_portal_shell(
        title="Налаштування",
        user=user,
        body=body,
        flash=flash,
        flash_kind=flash_kind,
    )


def render_portal_topup_page(
    user: dict,
    account: dict,
    topups: list[dict],
    *,
    flash: str = "",
    flash_kind: str = "info",
) -> str:
    rows = ""
    for topup in topups:
        note = (topup.get("note") or "").strip()
        note_cell = html.escape(note[:160] + ("…" if len(note) > 160 else "")) if note else "—"
        rows += f"""<tr>
      <td class="mono">{html.escape(str(topup.get('id') or '—'))}</td>
      <td>{html.escape(str(topup.get('status') or '—'))}</td>
      <td>{_au()._fmt_money(topup.get('amount_uah'))} грн</td>
      <td>{_au()._fmt_dt(topup.get('created_at'))}</td>
      <td>{_au()._fmt_dt(topup.get('paid_at'))}</td>
      <td title="{html.escape(note)}">{note_cell}</td>
    </tr>"""
    if not rows:
        rows = '<tr><td colspan="6" class="empty">Ще немає жодного topup-запису.</td></tr>'
    body = f"""
<section class="panel">
  <h2>Поповнення</h2>
  <div class="meta-grid">
    <div class="stat"><span class="lbl">Баланс</span><div class="val">{_au()._fmt_money(account.get('balance_uah'))} грн</div></div>
    <div class="stat"><span class="lbl">Поповнено всього</span><div class="val">{_au()._fmt_money(account.get('total_topup_uah'))} грн</div></div>
    <div class="stat"><span class="lbl">Витрачено</span><div class="val">{_au()._fmt_money(account.get('total_spent_uah'))} грн</div></div>
  </div>
  <p class="muted portal-copy">Monobank acquiring ще не підключений. Зараз портал уміє створити лише запит на ручне поповнення, який адміністратор бачить у `/admin/topups`.</p>
  <form class="portal-form" method="post" action="/topup">
    <div class="portal-form-grid portal-form-grid--compact">
    <label class="portal-field">
      <span class="portal-field-title">Сума, грн</span>
      <small class="portal-help">Сума запиту на ручне поповнення балансу.</small>
      <input type="number" name="amount_uah" min="0.01" step="0.01" placeholder="100.00" required>
    </label>
    <label class="portal-field">
      <span class="portal-field-title">Нотатка</span>
      <small class="portal-help">Коротке пояснення для адміна: навіщо саме це поповнення.</small>
      <input type="text" name="note" maxlength="180" placeholder="Напр. поповнення на тиждень">
    </label>
    </div>
    <div class="portal-form-actions">
      <button class="btn btn-main" type="submit">Створити запит</button>
    </div>
  </form>
</section>
<section class="panel">
  <h2>Останні topup-и</h2>
  <table class="data-table">
    <thead><tr><th>ID</th><th>Status</th><th>Сума</th><th>Створено</th><th>Оплачено</th><th>Нотатка</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>"""
    return render_portal_shell(
        title="Поповнення",
        user=user,
        body=body,
        flash=flash,
        flash_kind=flash_kind,
    )
