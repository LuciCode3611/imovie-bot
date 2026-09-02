# Zarfilm Telegram Bot (movie_bot)

Personal Telegram bot for searching zarfilm.com and retrieving direct download
links, restricted to a small allowlist (owner + friends). Zarfilm has no API;
the bot scrapes its WordPress pages over HTTPS with a logged-in session.

## Architecture & Structure

Pragmatic layered architecture, exactly this layout:

```
src/
    handlers/       # aiogram routers: search, callbacks, common (start/help/errors), middleware
    services/       # zarfilm HTTP client + parsers, message formatting
    repos/          # in-memory TTL cache (v1). No database yet — a later SQLite index goes behind the same interface
    models/         # Pydantic models: MovieSummary, MovieDetails, DownloadLink, Config
    exceptions.py   # ZarfilmError base + AuthError, SessionExpiredError, ParseError, NotFoundError
    main.py         # entrypoint: build dispatcher, register routers, long polling
```

## Code Quality & Style Rules

- Type safety: explicit Python type hints and Pydantic models across every layer.
- Minimal comments: self-documenting code. No obvious or conversational comments.
- Pragmatic architecture: apply patterns (repository, factory) only where actually needed. No over-engineering.
- Production standards: handle edge cases, timeouts, and failures cleanly. Hand-crafted quality — no generic AI boilerplate, no preachy inline docs.

## Domain Rules

- Direct links only: the bot sends zarfilm download URLs; it never re-uploads files to Telegram.
- One zarfilm account (owner's VIP). The client logs in with credentials from `.env`, persists cookies locally, and re-logins automatically on session expiry. Fallback: `/login` admin command that accepts a pasted cookie and deletes the message immediately after reading it.
- Secrets (`.env`, session files) are never committed, never logged, never echoed into chats.
- Scraping etiquette: in-memory TTL cache for searches and pages; space out requests; one search in flight per user.
- Allowlist-only: Telegram user IDs not in `ALLOWED_USER_IDS` are ignored with a terse rejection.

## UI & UX Formatting Specs

(Proposed defaults — being reviewed against the design doc. Persian-first, RTL.)

- Bot text formatting: compact single message per movie, RTL Persian labels, HTML parse mode:

  ```
  🎬 {title_en} — {title_fa} ({year})
  ⭐ {imdb} · 🎭 {genres} · ⏱ {runtime}
  📄 {plot truncated to ~300 chars}…
  ```

- Inline button layout: one row of quality buttons (480p / 720p / 1080p, labels in Persian), plus a "صفحه در زرفیلم" URL button.
- Custom emoji: inline buttons use premium custom emojis via `icon_custom_emoji_id` (owner has Telegram Premium, so bot-sent messages qualify). Emoji IDs are supplied by the owner and kept in a config mapping (role → ID); when an ID is unset or missing, buttons fall back to plain-text emoji so the bot never breaks.
- Button colors via `ButtonStyle`: 480p → PRIMARY, 720p → LINK, 1080p → SUCCESS (best quality highlighted), URL button → LINK, destructive/disabled or missing-link states → DANGER.
- Rich metadata message example:

  ```
  🎬 Interstellar — میان‌ستاره‌ای (2014)
  ⭐ 8.7 · 🎭 درام، علمی‌تخیلی · ⏱ ۲ ساعت و ۴۹ دقیقه
  📄 در آینده‌ای نزدیک، زمین دیگر قابل کشت نیست و…
  ```

## Development Workflow Rules

- Do NOT generate the entire project at once. Work incrementally, one file or module at a time.
- Before writing code for any component, outline the proposed implementation for that component, get explicit confirmation, then proceed.
- Implementation follows the approved design doc in `docs/superpowers/specs/` and its derived implementation plan. First implementation step: propose the structure and schemas for `src/models/` and `src/exceptions.py`.
