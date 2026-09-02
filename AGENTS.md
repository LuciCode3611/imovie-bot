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
- Cookie-only sessions: the zarfilm login form is captcha-protected, so credentials are never used or stored and captchas are never solved. The only session supply is the `/login` admin command (owner pastes a browser cookie; the message is deleted immediately after reading it). The client restores the cookie from `session.json` and, on expiry, asks the owner to re-run `/login`.
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

- Interaction flow (drill-down; every step edits the same message's keyboard in place):
  - Movie with a Persian dub on zarfilm: card shows [ دانلود با زبان اصلی (PRIMARY) ] [ دانلود با دوبله فارسی (SUCCESS) ] → tapping one edits the keyboard to quality buttons [ 1080p - 2.1GB ] [ 720p - 1.4GB ] [ 480p - 800MB ] (all PRIMARY, size included when known) → tapping a quality edits again to file URL button(s) labeled «⬇ {size} — {host}» plus [ انصراف (DANGER) ].
  - Movie without a dub: quality buttons appear directly on the card.
  - TV series: card shows season buttons [ فصل اول ] [ فصل دوم ] … → season → quality buttons (PRIMARY) → tapping a quality sends a compact text message with per-episode direct links (S01E01, …) and the card keyboard reverts to root.
  - انصراف (DANGER) always returns the keyboard to the card's root state; no multi-level back.
- Source privacy: never mention the site name to users — no "صفحه در زرفیلم" URL button, no zarfilm branding in messages or error texts. User-facing text is source-neutral; the source is visible only in the actual download URLs.
- Callback data: short in-memory keys (e.g. 6-hex) mapping to selection state — never raw slugs (Telegram's 64-byte callback_data limit).
- Custom emoji: inline buttons use premium custom emojis via `icon_custom_emoji_id` (owner has Telegram Premium, so bot-sent messages qualify). Emoji IDs are supplied by the owner and kept in a config mapping (role → ID); when an ID is unset or missing, buttons fall back to plain-text emoji so the bot never breaks.
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
