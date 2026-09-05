# Contributing

Personal Telegram bot for searching zarfilm.com and retrieving direct download
links, restricted to a small allowlist (owner + friends). Zarfilm has no API;
the bot scrapes its WordPress pages over HTTPS with a logged-in session.
Persian subtitles are the exception: they come from the SubDL API.

## Architecture

Layered, exactly this layout:

```
src/
    handlers/       # aiogram routers: search, callbacks, common (start/help/errors), middleware
    services/       # zarfilm (HTML) + SubDL (JSON) clients and parsers, message formatting
    repos/          # in-memory TTL cache (v1). No database yet — a later SQLite index goes behind the same interface
    models/         # Pydantic models: MovieSummary, MovieDetails, DownloadLink, SubtitleDetails, Config
    exceptions.py   # ZarfilmError base + AuthError, SessionExpiredError, ParseError, NotFoundError; SubdlError for the subtitle API
    main.py         # entrypoint: build dispatcher, register routers, long polling
```

## Code style

- Explicit type hints and Pydantic models across every layer.
- Comments explain *why*, never *what*. Self-documenting code by default.
- Apply patterns (repository, factory) only where they earn their keep.
- Handle edge cases, timeouts, and failures explicitly.

## Domain rules

- Direct links only for movies and series: those files are gigabytes, so the bot sends zarfilm URLs and never re-uploads them. Subtitles are the deliberate exception — an archive is a few hundred KB, so the bot downloads it and sends it as a Telegram document, caching the returned `file_id` in SQLite (one download per archive, ever) and falling back to the public link when the file is oversized or either side fails.
- Subtitles: SubDL API, Persian (`FA`) only. `SUBDL_API_KEY` comes from the environment and stays server-side. Cards show no download URL at all — buttons are callbacks, the file arrives as a document, and the public `dl.subdl.com` zip (query string stripped, so it can never carry the key) appears only as the failure fallback. Server-side downloads share SubDL's anonymous 300/day-per-IP limit, which the `file_id` cache keeps from ever being hit twice for the same archive. No key means the subtitle flow answers "unavailable" and the owner dashboard says why; the rest of the bot is unaffected.
- Cookie-only sessions: the zarfilm login form is captcha-protected, so credentials are never used or stored and captchas are never solved. The only session supply is the `/login` admin command (owner pastes a browser cookie; the message is deleted immediately after reading it). The client restores the cookie from `session.json` and, on expiry, asks the owner to re-run `/login`.
- Secrets (`.env`, session files) are never committed, never logged, never echoed into chats.
- Scraping etiquette: in-memory TTL cache for searches and pages; space out requests; one search in flight per user.
- Allowlist-only: Telegram user IDs not in `ALLOWED_USER_IDS` are ignored with a terse rejection.

## UI & formatting

Persian-first, RTL.

- Bot text formatting: compact single message per movie, RTL Persian labels, HTML parse mode:

  ```
  🎬 {title_en} — {title_fa} ({year})
  ⭐ {imdb} · 🎭 {genres}
  📄 {plot truncated to ~300 chars}…
  ```

- Interaction flow (drill-down; every step edits the same message's keyboard in place):
  - Search is gated: free text never triggers a site request. The user taps [ جستجو ] → bot enters listening state («نام فیلم یا سریال رو بنویس…») → the next text message is the search query → mode auto-resets after results/no-results. Free text while not listening gets a hint to tap جستجو; nothing hits the site.
  - Search feedback: on a cache miss the bot posts «🔍 در حال جستجو…» and edits it into the results (cache hits answer directly). The results message header echoes the query («نتایج برای «query»:») and shows the visible range («نمایش ۶–۱۰ از ۲۳») when results span pages.
  - Pagination: 5 results per page with a nav row [◀] [۲/۳] [▶]; pages are rebuilt from a TTL-stored SearchEntry (no re-query), callback data `pg:<key>:<page>` (indicator uses `pg:<key>:i`, a silent no-op).
  - Search fallback: WordPress matches whole words, so compound queries («spiderman») can miss phrase titles («Spider Man»). When the site returns nothing, the client retries once with a stem of the longest word («spid») and filters results by normalized containment (case/punctuation/space-insensitive); unfiltered stem results are returned best-effort when nothing strictly matches. At most one extra request per search.
  - Search cards: the parser accepts any `.item_body_widget` card regardless of its `data-type` (movies and series use different types) and detects series cards by «سریال»/«مجموعه» in the card title.
  - Welcome: /start sends a formatted welcome card (bot purpose + short راهنما) with the [ جستجو ] button attached.
  - Quality buttons stack vertically, one per row, label format «{quality} - {size}» (e.g. «1080p - 2.1GB»); file URL buttons follow the same vertical layout.
  - Movie with a Persian dub on zarfilm: card shows [ دانلود با زبان اصلی (PRIMARY) ] [ دانلود با دوبله فارسی (SUCCESS) ] → tapping one edits the keyboard to vertically stacked quality buttons [ 1080p - 2.1GB ] [ 720p - 1.4GB ] [ 480p - 800MB ] (all PRIMARY, size included when known) → tapping a quality edits again to file URL button(s) labeled «⬇ {quality} · {size} — {host}» plus [ انصراف (DANGER) ].
  - Movie without a dub: quality buttons appear directly on the card.
  - TV series: card shows season buttons [ فصل اول ] [ فصل دوم ] … → season → quality buttons (PRIMARY) → tapping a quality sends text message(s) with per-episode direct links (S01E01, …), headed by «📂 {season} · {quality} — {n} قسمت» and chunked under Telegram's 4096-char limit; the card keyboard reverts to root.
  - Posters: when the movie page exposes a poster URL, the card is sent as a NEW photo message (caption = card text, keyboard attached) so the search-results list stays usable for other results; if Telegram rejects the photo URL, fall back to editing the results message in place.
  - انصراف (DANGER) always returns the keyboard to the card's root state; no multi-level back.
- Source privacy: never mention the site name to users — no "صفحه در زرفیلم" URL button, no zarfilm branding in messages or error texts. User-facing text is source-neutral; the source is visible only in the actual download URLs.
- Callback data: short in-memory keys (e.g. 6-hex) mapping to selection state — never raw slugs (Telegram's 64-byte callback_data limit).
- Custom emoji: inline buttons use premium custom emojis via `icon_custom_emoji_id` (owner has Telegram Premium, so bot-sent messages qualify). Emoji IDs are supplied by the owner and kept in a config mapping (role → ID); when an ID is unset or missing, buttons fall back to plain-text emoji so the bot never breaks.
- Rich metadata message example:

  ```
  🎬 Interstellar — میان‌ستاره‌ای (2014)
  ⭐ 8.7 · 🎭 درام، علمی‌تخیلی
  📄 در آینده‌ای نزدیک، زمین دیگر قابل کشت نیست و…
  ```

## Workflow

- Work in small, reviewable increments — one module at a time, not whole-project drops.
- Sketch the shape of a component (types, function signatures) before implementing it.
- Tests first: every change lands with a test that failed before it.
- Run the suite from the repo root: `python -m pytest -q`.
- Conventional commit messages (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`).
- The design doc is `docs/design.md`; keep it in sync when behaviour changes.
