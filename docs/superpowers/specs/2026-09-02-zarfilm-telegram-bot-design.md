# Zarfilm Telegram Bot — Design

Date: 2026-09-02
Status: Draft for review
Owner: rezal

## 1. Overview

A private Telegram bot that searches zarfilm.com (Persian movie/series download
site) and returns direct download links for the owner and a small group of
friends. Zarfilm has no API and a disabled WordPress REST endpoint, so the bot
scrapes its server-rendered HTML with a logged-in session.

Verified facts from probing (2026-09-02):

- WordPress site, `wp-json` returns 404, no Cloudflare/anti-bot on basic pages.
- Search lives at `/?s=<query>`; movie pages live at `/<slug>-<year>/`.
- Pages embed Yoast schema.org JSON-LD: English + Persian title, poster URL,
  IMDb rating, genres, plot — free structured metadata.
- Download links are hidden behind sign-in (VIP tariffs) but are **ungated URLs
  once generated** and **not IP-bound** (owner verified by sharing a link).
- Page generation takes ~4–5 s; caching matters for UX.

## 2. Goals / Non-Goals

**Goals (v1)**

- Search zarfilm from Telegram (Persian or English title).
- Show movie metadata + quality-labeled direct download links (480p/720p/1080p).
- Allowlist-only access (owner + friends), one shared zarfilm VIP account.
- Self-healing session: auto re-login on expiry; manual cookie fallback.
- Runs on the owner's Windows PC now; migratable to a free PaaS or cheap VPS later.

**Non-Goals (v1)**

- No re-uploading files into Telegram (Telegram file limits + bandwidth).
- No database, no background crawler, no new-content alerts (natural v2; the
  cache interface is designed so a SQLite index can replace it).
- No public access, no multi-account pool, no captcha-solving.

## 3. Architecture

Single Python process, layered per `AGENTS.md`:

```
src/
    handlers/    # aiogram routers + middleware
    services/    # zarfilm client, parsers, formatting
    repos/       # in-memory TTL cache (repository interface)
    models/      # Pydantic models
    exceptions.py
    main.py
```

Stack: Python 3.12, aiogram 3 (long polling — no inbound ports, PaaS-friendly),
httpx (async HTTP, cookie jar), selectolax (fast HTML parsing) + stdlib `json`
for JSON-LD, pydantic-settings for config, pytest for tests.

### Components

**`services/zarfilm.py` — ZarfilmClient**

Owns the one logged-in httpx session. Responsibilities:

- `login(username, password)`: POST to the sign-in form; persist cookies to a
  local file (`session.json`) so restarts don't re-login.
- `search(query) -> list[MovieSummary]`: GET `/?s=<query>`, parse result cards.
- `movie(slug) -> MovieDetails`: GET `/<slug>/`, parse JSON-LD + download box.
- Session-expiry detection: response redirects to `/sign-in` or the download
  box is absent → transparent re-login once, then retry the request; if
  re-login fails → `AuthError`.
- All requests: 20 s timeout, one retry on transport error, polite pacing
  (no concurrent requests to zarfilm; serialized via an asyncio lock).

**`services/parsers.py`**

Pure functions from HTML/JSON-LD strings to Pydantic models. No I/O, fully
unit-testable against saved fixture pages.

**`services/formatting.py`**

Models → Telegram HTML (RTL Persian, parse mode `HTML`) and inline keyboard
markup. Pure functions.

**Interaction & button spec** (owner-defined; colors verified against aiogram
3.31 / Bot API):

Drill-down keyboards edit the card message in place
(`edit_message_reply_markup`); no new card messages are sent except the
series episode list.

- Movie with a Persian dub: root keyboard `[ دانلود با زبان اصلی (PRIMARY) ]`
  `[ دانلود با دوبله فارسی (SUCCESS) ]` → quality row
  `[ 1080p ] [ 720p ] [ 480p ]` (all `PRIMARY`, size hint in label when
  known) → file row: URL button(s) `⬇ {size} — {host}` + `[ انصراف (DANGER) ]`.
- Movie without a dub: root keyboard is the quality row directly.
- Series: root keyboard is season buttons `[ فصل اول ] [ فصل دوم ] …` →
  quality row (all `PRIMARY`) → tapping a quality sends a compact text
  message listing per-episode direct links (S01E01, …), and the card keyboard
  reverts to its root state.
- `انصراف` always returns the keyboard to the card root; shallow state
  machine, no multi-level back. The card root also carries a
  "صفحه در زرفیلم" URL button.
- Callback data uses short in-memory keys (6-hex → selection state, TTL 1 h)
  to stay under Telegram's 64-byte `callback_data` limit and reuse parsed
  movie data without re-scraping on every tap.
- Custom emoji via `InlineKeyboardButton.icon_custom_emoji_id`, valid because
  the bot owner has Telegram Premium. Emoji IDs live in a config mapping
  (role → ID, e.g. `EMOJI_MOVIE`, `EMOJI_DUB`); unset IDs fall back to
  plain-text emoji so buttons never fail to render. Owner supplies concrete
  IDs during implementation.

**`repos/cache.py` — TTLCache**

`asyncio`-safe in-memory key→value with per-entry TTL (searches: 1 h, movie
pages: 6 h) behind a tiny `Cache` protocol, so v2 can swap in SQLite without
touching callers.

**`handlers/`**

- `common.py`: `/start`, `/help`; rejection text for non-allowlisted users.
- `search.py`: text message → search → reply with numbered inline buttons
  (up to 5 results).
- `details.py`: callback query → drill-down keyboard navigation (language →
  quality → file URL buttons; season → quality → episode-list message),
  state kept in `repos/state.py`, every step edits the card in place.
- `admin.py`: `/login` (owner only) accepting a pasted cookie; deletes the
  message immediately after reading it.
- `middleware.py`: allowlist check; per-user search debounce (one in-flight
  search per user); global error handler → terse Persian error text, logged
  with traceback.

**`repos/state.py` — CallbackState**

In-memory store: short key (6-hex, TTL 1 h) → the parsed `MovieDetails` plus
the user's current drill-down selection (language / season / quality). Lets
every button tap re-render keyboards without re-scraping zarfilm and keeps
`callback_data` under Telegram's 64-byte limit. Swept lazily on write.

**`models/`**

`MovieSummary` (slug, title_en, title_fa, year, poster_url, kind:
movie|series), `DownloadLink` (quality, url, size_hint, host),
`MovieDetails` (summary + imdb, genres, runtime, plot; for movies:
`originals`/`dubs` lists of `DownloadLink`, dub absent when none; for series:
`seasons` list of `Season(label, qualities)`, `QualityPack(quality,
episodes)`, `EpisodeLink(episode_label, url, size_hint, host)`), `Config`
(bot token, zarfilm credentials, `ALLOWED_USER_IDS`, emoji role→ID mapping,
cache/state TTLs, session path).

**`exceptions.py`**

`ZarfilmError` base; `AuthError`, `SessionExpiredError`, `NotFoundError`,
`ParseError`.

### Data flow

```
user text → allowlist middleware → search handler
  → cache miss → ZarfilmClient.search() → parsers → cache
  → up to 5 result buttons; tapping one fetches the page once
  → metadata card + root keyboard (language / qualities / seasons)
card button tap → callback handler → CallbackState lookup (short key)
  → drill-down: edit_message_reply_markup per tap
  → movie quality tap: edit to file URL buttons (size/host labels)
  → series quality tap: send episode-list message, keyboard reverts to root
  → انصراف: revert to card root
```

Re-scraping happens only on cache miss (search 1 h, movie pages 6 h); all
drill-down taps reuse the already-parsed page.

### Session & anti-detection posture

No protection to evade (plain WordPress). Posture is purely etiquette:
serialized requests, TTL caches, realistic browser User-Agent, modest request
volume (friends scale). If zarfilm later adds a captcha at login, the cookie
fallback is the designed escape hatch — the bot never attempts captcha
solving.

## 4. Error Handling

| Failure | Behavior |
|---|---|
| Session expired | Auto re-login once, retry request; on failure `AuthError` |
| Login blocked (captcha/HTML change) | Notify owner in chat; `/login` cookie fallback |
| Search timeout / transport error | One retry, then "زرفیلم در دسترس نیست، بعداً تلاش کن" |
| No results | "چیزی پیدا نشد" + suggest trying another spelling |
| Parse failure (site redesign) | `ParseError`, logged with the HTML sample; user sees generic error |
| Non-allowlisted user | Terse rejection; nothing executes |
| Callback for expired/unknown state key | "منقضی شده، دوباره جستجو کن" + prompt to re-search |
| Series quality with zero parsed episodes | Generic error, logged with HTML sample |

## 5. Security

- Secrets only in `.env` (bot token, zarfilm credentials) — gitignored; session
  cookie file gitignored; never logged, never echoed into chats.
- `/login` cookie message deleted immediately after parsing.
- Hard allowlist middleware; unknown users get a rejection, no processing.
- Repo contains no credentials; log files excluded from git.

## 6. Testing

- **Parsers**: pytest against committed HTML fixtures (one search page, one
  movie page, one series page, one logged-out variant). Pure functions, fast
  and deterministic.
- **ZarfilmClient**: httpx `MockTransport` — search, details, session-expiry →
  re-login retry, transport-error retry, NotFound.
- **Formatting**: snapshot-style tests for card text and every keyboard state
  (root, qualities, file URLs, seasons, cancel), including style/icon
  fallback when custom emoji IDs are unset.
- **Drill-down state**: CallbackState TTL expiry, key collisions, cancel
  revert.
- **Handlers**: aiogram's dispatcher test utilities for allowlist, debounce,
  and error middleware.
- Manual acceptance: live run against zarfilm before each milestone.

## 7. Deployment

- v1: `python -m src.main` on the owner's PC (Windows); `.env` beside it;
  auto-restart via a simple loop or NSSM/task scheduler is optional.
- Later: same long-polling process in a slim Docker image on a cheap VPS or a
  free PaaS — no inbound ports, no storage requirements, so any tier works.
  Links are not IP-bound, so no proxying concerns.

## 8. Milestones (for the implementation plan)

1. Scaffolding: models, exceptions, config — *per AGENTS.md, starts with
   `src/models/` + `src/exceptions.py` structure proposal*.
2. `ZarfilmClient` login + session persistence (+ live smoke test).
3. Parsers for search + movie page (+ fixtures).
4. Cache + formatting.
5. Handlers: allowlist middleware, search, card, drill-down navigation, errors.
6. Admin `/login` fallback.
7. Polish: debounce, logging, README, Dockerfile for later hosting.

## 9. Open Items

- Exact login endpoint/field names and download-box markup need a
  logged-in capture (owner's credentials) during implementation milestone 2 —
  the parser design accommodates the download box being behind login.
- Series episode-list rendering needs one sample series page with a Persian
  dub to confirm how zarfilm labels season/dub links (milestone 3 fixture).
- Custom emoji IDs for button icons are supplied by the owner at
  implementation time and go into the config mapping (Section 3); the
  remaining UI text templates in `AGENTS.md` are still proposals until the
  owner finalizes them in this review.
