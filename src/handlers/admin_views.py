"""Owner dashboard views: overview, user management and request management.

Rendered both as Bot API 10.1 rich messages (tables) with a plain-text
fallback, and always with an inline keyboard of management actions.
"""

from html import escape

from aiogram.enums.button_style import ButtonStyle
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputRichBlockSectionHeading,
    InputRichBlockTable,
    InputRichMessage,
    RichBlockTableCell,
)

from src.repos.db import RequestRow, UserRow

def persian_ttl(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    days, rem = divmod(int(seconds), 86400)
    hours = rem // 3600
    parts = []
    if days:
        parts.append(f"{days} روز")
    if hours:
        parts.append(f"{hours} ساعت")
    if not parts:
        return f"{int(seconds) // 60} دقیقه"
    return " و ".join(parts)


USERS_PAGE = 6
REQUESTS_PAGE = 6


def _cell(text: str, *, header: bool = False) -> RichBlockTableCell:
    return RichBlockTableCell(text=text, align="center", valign="middle", is_header=header)


# ---------- keyboards -------------------------------------------------------


def overview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 به‌روزرسانی", callback_data="dash:check"),
                InlineKeyboardButton(text="🔑 کوکی", callback_data="dash:login"),
            ],
            [
                InlineKeyboardButton(text="👥 کاربران", callback_data="adm:users:0"),
                InlineKeyboardButton(text="📥 درخواست‌ها", callback_data="adm:reqs:0"),
            ],
            [InlineKeyboardButton(text="✖ بستن", callback_data="dash:close", style=ButtonStyle.DANGER)],
        ]
    )


def users_keyboard(users: list[UserRow], page: int, total: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    pages = max(1, (total + USERS_PAGE - 1) // USERS_PAGE)
    for user in users:
        if user.blocked:
            action = InlineKeyboardButton(
                text="✅ رفع مسدودی", callback_data=f"adm:unblk:{user.user_id}"
            )
        else:
            action = InlineKeyboardButton(
                text="🚫 مسدود", callback_data=f"adm:blk:{user.user_id}", style=ButtonStyle.DANGER
            )
        rows.append(
            [
                InlineKeyboardButton(text=f"👤 {user.user_id}", callback_data=f"adm:noop:{user.user_id}"),
                action,
            ]
        )
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"adm:users:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="adm:nop"))
    if (page + 1) * USERS_PAGE < total:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"adm:users:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔙 داشبورد", callback_data="dash:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def requests_keyboard(requests: list[RequestRow], page: int, total: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    pages = max(1, (total + REQUESTS_PAGE - 1) // REQUESTS_PAGE)
    for req in requests:
        rows.append(
            [
                InlineKeyboardButton(text="✅ انجام شد", callback_data=f"adm:rdone:{req.id}", style=ButtonStyle.SUCCESS),
                InlineKeyboardButton(text="🗑 رد شد", callback_data=f"adm:rrej:{req.id}", style=ButtonStyle.DANGER),
            ]
        )
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"adm:reqs:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="adm:nop"))
    if (page + 1) * REQUESTS_PAGE < total:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"adm:reqs:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔙 داشبورد", callback_data="dash:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------- rich / plain rendering ------------------------------------------


def subtitle_status(stats: dict) -> str:
    """One line for the subtitle source: is the SubDL key there, and how much of
    it has been used since startup (owner-only view, so the variable name is fine).

    «کش» counts archives already uploaded to Telegram — those are re-sent by
    file_id and never touch the source's per-IP download limit again.
    """
    if not stats.get("sub_enabled"):
        return "🔴 غیرفعال — SUBDL_API_KEY تنظیم نشده"
    return (
        f"🟢 فعال — جستجو {stats.get('sub_searches', 0)} · عنوان {stats.get('sub_titles', 0)}"
        f" · ارسال {stats.get('sub_downloads', 0)} · کش {stats.get('subtitle_files', 0)}"
    )


def overview_rich(stats: dict) -> InputRichMessage:
    online = "🟢 آنلاین" if stats.get("online") else "🔴 آفلاین"
    if not stats.get("session_present"):
        cookie = "🔴 بدون کوکی"
    elif stats.get("session_valid") is True:
        cookie = "🟢 معتبر"
    elif stats.get("session_valid") is False:
        cookie = "🔴 منقضی شده"
    else:
        cookie = "🟡 نامشخص"

    def s(value: str, header: bool = False) -> RichBlockTableCell:
        return _cell(value, header=header)

    rows = [
        [s("وضعیت ربات", header=True), s(online)],
        [s("کوکی نشست", header=True), s(cookie)],
        [s("اعتبار باقی‌مانده", header=True), s(stats.get("ttl_human") or "—")],
        [s("مدت روشن بودن", header=True), s(stats.get("uptime_human") or "—")],
        [s("دسترسی کاربران", header=True), s("🔓 باز برای همه" if stats.get("open_mode") else "🔒 فقط لیست مجاز")],
        [s("پروکسی", header=True), s("🟢 فعال" if stats.get("proxy") else "—")],
        [s("کاربران", header=True), s(f"👥 {stats.get('users', 0)} (فعال ۷ روز: {stats.get('active_7d', 0)})")],
        [s("کاربران مسدود", header=True), s(f"🚫 {stats.get('blocked', 0)}")],
        [s("جستجوها (ربات)", header=True), s(f"🔍 {stats.get('searches', 0)}")],
        [s("جستجوها (کل کاربران)", header=True), s(f"📊 {stats.get('searches_total', 0)}")],
        [s("صفحه‌های باز شده", header=True), s(f"🎬 {stats.get('movies', 0)}")],
        [s("زیرنویس", header=True), s(f"📝 {subtitle_status(stats)}")],
        [s("درخواست‌های باز", header=True), s(f"📥 {stats.get('requests_open', 0)}")],
        [s("کل درخواست‌ها", header=True), s(f"🗂 {stats.get('requests_total', 0)}")],
    ]
    table = InputRichBlockTable(is_bordered=False, is_compact=True, cells=rows)
    return InputRichMessage(
        blocks=[InputRichBlockSectionHeading(text="🛠 داشبورد مدیریت ربات", size=2), table],
        is_rtl=True,
    )


def overview_text(stats: dict) -> str:
    lines = [
        "🛠 داشبورد مدیریت ربات",
        "",
        f"👥 کاربران: {stats.get('users', 0)} (فعال ۷ روز: {stats.get('active_7d', 0)})",
        f"🚫 مسدود: {stats.get('blocked', 0)}",
        f"🔍 جستجوها: ربات {stats.get('searches', 0)} · کل {stats.get('searches_total', 0)}",
        f"🎬 صفحه‌های باز شده: {stats.get('movies', 0)}",
        f"📝 زیرنویس: {subtitle_status(stats)}",
        f"📥 درخواست‌های باز: {stats.get('requests_open', 0)} از {stats.get('requests_total', 0)}",
    ]
    return "\n".join(lines)


def users_rich(users: list[UserRow], page: int, total: int) -> InputRichMessage:
    rows: list[list[RichBlockTableCell]] = [
        [_cell("نام", header=True), _cell("آیدی", header=True), _cell("جستجو", header=True), _cell("وضعیت", header=True)]
    ]
    for user in users:
        rows.append(
            [
                _cell(user.full_name[:20] or "—"),
                _cell(str(user.user_id)),
                _cell(str(user.searches)),
                _cell("🚫 مسدود" if user.blocked else "✅ فعال"),
            ]
        )
    table = InputRichBlockTable(is_bordered=False, is_compact=True, cells=rows)
    heading = InputRichBlockSectionHeading(text=f"👥 کاربران — {total} نفر", size=2)
    return InputRichMessage(blocks=[heading, table], is_rtl=True)


def users_text(users: list[UserRow], page: int, total: int) -> str:
    lines = [f"👥 کاربران — {total} نفر", ""]
    for user in users:
        mark = "🚫" if user.blocked else "✅"
        name = escape(user.full_name) or "—"
        lines.append(f"{mark} {name} (<code>{user.user_id}</code>) — 🔍 {user.searches}")
    return "\n".join(lines)


def requests_rich(requests: list[RequestRow], page: int, total: int) -> InputRichMessage:
    rows: list[list[RichBlockTableCell]] = [
        [_cell("عنوان", header=True), _cell("درخواست‌دهنده", header=True)]
    ]
    for req in requests:
        rows.append([_cell(req.title[:40]), _cell(f"{req.user_name[:20]} · {req.user_id}")])
    table = InputRichBlockTable(is_bordered=False, is_compact=True, cells=rows)
    heading = InputRichBlockSectionHeading(text=f"📥 درخواست‌های باز — {total} مورد", size=2)
    return InputRichMessage(blocks=[heading, table], is_rtl=True)


def requests_text(requests: list[RequestRow], page: int, total: int) -> str:
    lines = [f"📥 درخواست‌های باز — {total} مورد", ""]
    for req in requests:
        name = escape(req.user_name)
        lines.append(f"• {escape(req.title)} — {name} (<code>{req.user_id}</code>)")
    if not requests:
        lines.append("درخواست بازی وجود نداره ✅")
    return "\n".join(lines)
