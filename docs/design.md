# Zarfilm Telegram Bot — Design

Date: 2026-09-02
Last updated: 2026-09-06 — subtitle subsystem (SubDL), SQLite persistence,
document delivery
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

The bot has since grown a second, independent source: **SubDL**
(`api.subdl.com`) for Persian subtitles. Unlike zarfilm it is a documented JSON
API behind an API key, so that half of the bot does no scraping and holds no
session — and, because subtitle archives are small, it delivers the files
themselves rather than links (§3, "Subtitle card & delivery spec").

## 2. Goals / Non-Goals

**Goals (v1)**

- Search zarfilm from Telegram (Persian or English title).
- Show movie metadata + quality-labeled direct download links (480p/720p/1080p).
- Allowlist-only access (owner + friends), one shared zarfilm VIP account.
- Self-healing session: auto re-login on expiry; manual cookie fallback.
- Runs on the owner's Windows PC now; migratable to a free PaaS or cheap VPS later.

**Non-Goals (v1)**

- No re-uploading *movies or series* into Telegram (gigabytes, bandwidth, the
  bot upload limit) — those stay direct links. Subtitle archives are the
  deliberate exception: a few hundred KB, sent as documents and cached by
  `file_id`.
- No background crawler, no new-content alerts. The "no database" non-goal is
  retired: `repos/db.py` is a small SQLite store (users, blocks, content
  requests, subtitle `file_id` cache); the in-memory `TTLCache` still fronts
  both sources.
- No public access, no multi-account pool, no captcha-solving.

## 3. Architecture

Single Python process, layered per `CONTRIBUTING.md`:

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

**`services/subdl.py` — SubdlClient** + **`services/subdl_parsers.py`**

Second source: no session, no scraping, JSON only.

- `search(query)` → `GET /api/v1/subtitles?film_name=…&languages=FA`;
  `details(summary)` → the same endpoint keyed by `sd_id`, with `full_season=1`
  for series (retried once without it when the title has no season pack) so a
  season arrives as one zip instead of 30 single-episode files.
- Persian only, twice over: `languages=FA` on the wire *and* an `is_persian()`
  filter on the parsed rows, because the API does not always honour the
  parameter.
- `fetch_archive(url)` → streams one public `dl.subdl.com` zip: 40 MB cap
  (Bot API allows 50 MB), HTML answers rejected, 3 concurrent slots, 60 s
  timeout. Download URLs are absolute, so they bypass the API base URL and
  never carry the key.
- Disabled without `SUBDL_API_KEY`: `enabled` is False and the handlers say so
  instead of firing a request the API would reject; the rest of the bot is
  unaffected.
- `SubdlError` sits outside the `ZarfilmError` tree on purpose — a SubDL outage
  must never read as an expired zarfilm session. `ArchiveTooLargeError` extends
  it for the one failure that has a different user-facing answer.
- Parsers are pure functions over the payload (no I/O), tested against inline
  JSON rather than committed fixtures: the response shape is small and stable,
  and CI must not depend on reaching a third-party API.

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
  `[ 1080p - 2.1GB ] [ 720p - 1.4GB ] [ 480p - 800MB ]` (all `PRIMARY`,
  size included when known) → file row: URL button(s) `⬇ {size} — {host}` +
  `[ انصراف (DANGER) ]`.
- Movie without a dub: root keyboard is the quality row directly.
- Series: root keyboard is season buttons `[ فصل اول ] [ فصل دوم ] …` →
  quality row (all `PRIMARY`) → tapping a quality sends a compact text
  message listing per-episode direct links (S01E01, …), and the card keyboard
  reverts to its root state.
- `انصراف` always returns the keyboard to the card root; shallow state
  machine, no multi-level back.
- Source privacy (owner requirement): no "صفحه در زرفیلم" URL button and no
  site name in any user-facing text — messages and error texts are
  source-neutral; the source is only visible in the download URLs themselves.
- Callback data uses short in-memory keys (6-hex → selection state, TTL 1 h)
  to stay under Telegram's 64-byte `callback_data` limit and reuse parsed
  movie data without re-scraping on every tap.
- Custom emoji via `InlineKeyboardButton.icon_custom_emoji_id`, valid because
  the bot owner has Telegram Premium. Emoji IDs live in a config mapping
  (role → ID, e.g. `EMOJI_MOVIE`, `EMOJI_DUB`); unset IDs fall back to
  plain-text emoji so buttons never fail to render. Owner supplies concrete
  IDs during implementation.

**Subtitle card & delivery spec**

- Search results page exactly like the movie flow (5 per page, `◀ 1/3 ▶`), then
  a rich card (Bot API 10.1 centered metadata table: title, year, movie/series,
  seasons, file count) with one blue «دانلود …» button per file. The card is
  never edited — a *new* message carries it — so the results list survives, and
  there is no season sub-view: a season with several archives simply gets
  several buttons («فصل 1 · همه قسمت‌ها», «فصل 1 · قسمت 1–3», …).
- Buttons are callbacks (`sdl:{6-hex key}:{index}`, the index into
  `SubtitleDetails.files`), never URLs — so no source host and no API key can
  reach a message. Clients that predate rich messages get the plain-text card.
- A tap sends the archive as a **document inside a single rich message**,
  renamed `«{title} ({year}) — {label}.zip»` (unsafe characters stripped,
  100-char cap). Under it, in the same bubble, goes the one instruction every
  archive needs — «زیرنویس را از حالت فشرده خارج کنید و داخل مدیا پلیر اضافه
  کنید» — as a borderless, centered single-row table nested inside a *block*
  quotation (`InputRichBlockBlockQuotation` is the only quotation block that can
  nest another block; a pull quotation takes plain text). There is no caption: a
  caption cannot hold a table, and the instruction is the same for every title,
  season and episode, so per-file text added nothing.
- Serving order:
  1. the cached Telegram `file_id` — instant, free, and it does not count
     against SubDL's anonymous 300/day-per-IP limit;
  2. a fresh download + upload (`upload_document` chat action covers both),
     caching the returned `file_id` — read from `message.document` *or* from the
     document block inside `message.rich_message`, whichever Telegram fills in;
  3. a «🔗 لینک مستقیم دانلود» link button when the archive is oversized or
     either side fails — never a bare error.
- Degradation: if Telegram refuses a media block inside a rich message (older
  client or API), the file is sent the classic way and the quoted note follows
  as its own message, itself degrading to plain text when rich messages are
  unavailable altogether. The zip is never lost — and a failure of the document
  *itself* (an unknown `file_id`) still propagates, so the stale cache entry is
  dropped and the archive re-uploaded rather than being reported as delivered.

**`repos/cache.py` — TTLCache**

`asyncio`-safe in-memory key→value with per-entry TTL (searches: 1 h, movie
pages: 6 h) behind a tiny `Cache` protocol, so v2 can swap in SQLite without
touching callers.

**`repos/db.py` — Database**

SQLite (stdlib `sqlite3`, one connection behind a lock): users + block list,
search counters, owner-visible content requests, and `subtitle_files`
(`url` PRIMARY KEY → Telegram `file_id` + timestamp). That last table is what
makes document delivery cheap — `file_id`s are bot-specific but reusable across
chats and do not expire, so each archive is downloaded from SubDL at most once
per database. It also absorbs the quota shift: downloads now come from the
*server's* IP (a shared one on Railway), not the user's. Production needs a
persistent volume for `DB_PATH`; without it the cache resets on every redeploy.
A `file_id` Telegram stops accepting is dropped and the archive re-uploaded
once, so a rotated bot token heals itself.

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

```
subtitle text → subtitle_search handler → SubdlClient.search (FA) → cache
  → up to 5 title buttons; tap → SubdlClient.details (sd_id) → cache
  → rich card (new message) + one callback button per file
  → tap → cached file_id? re-send : fetch_archive → send document → cache id
  → oversize / SubDL error / upload error → link button as the fallback
```

Re-scraping happens only on cache miss (search 1 h, movie pages 6 h); all
drill-down taps reuse the already-parsed page. Subtitle archives go one better:
after the first delivery they never leave Telegram's storage again.

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
| Search timeout / transport error | One retry, then "منبع موقتاً در دسترس نیست؛ بعداً تلاش کن" |
| No results | "چیزی پیدا نشد" + suggest trying another spelling |
| Parse failure (site redesign) | `ParseError`, logged with the HTML sample; user sees generic error |
| Non-allowlisted user | Terse rejection; nothing executes |
| Callback for expired/unknown state key | "منقضی شده، دوباره جستجو کن" + prompt to re-search |
| Series quality with zero parsed episodes | Generic error, logged with HTML sample |
| `SUBDL_API_KEY` missing | Subtitle flow answers «غیرفعال»; dashboard names the variable; movies unaffected |
| SubDL 4xx/5xx, quota, transport error | `SubdlError` → terse Persian text, logged as a warning (no traceback) |
| Subtitle archive over 40 MB | `ArchiveTooLargeError` → public-link button instead of a document |
| Subtitle download or upload failed | Public-link button; the card and the results list stay intact |
| Cached `file_id` rejected (`TelegramBadRequest`) | Row dropped from `subtitle_files`, archive re-uploaded once |

## 5. Security

- Secrets only in `.env` (bot token, zarfilm credentials) — gitignored; session
  cookie file gitignored; never logged, never echoed into chats.
- `/login` cookie message deleted immediately after parsing.
- Hard allowlist middleware; unknown users get a rejection, no processing.
- Source privacy: the scraped site is never named in user-facing messages,
  errors, or button labels — friends see a neutral "movie bot"; the source
  appears only inside the download URLs themselves.
- `SUBDL_API_KEY` comes from the environment only and never appears in a card,
  a URL, a log line or an error message. Card buttons are callbacks, so the one
  place a SubDL URL can surface is the deliberate link fallback — built by
  `public_zip_url()`, which strips the query string (where a key would ride).
- Downloaded archives are size-capped *while streaming*, so a mislabelled or
  hostile file cannot exhaust the container's memory, and HTML answers are
  rejected so a "limit reached" interstitial is never uploaded as a subtitle.
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
- **SubdlClient**: httpx `MockTransport` over inline JSON — search, details,
  the `full_season` retry, and `fetch_archive` (declared and mid-stream size
  cap, HTML body, empty body, dead host, `Content-Disposition`/URL naming).
- **Subtitle flow**: keyboards, document naming, the quoted unpack note (one
  borderless centered row inside a blockquote), cache hit/miss/stale-id, every
  fallback branch including the rich→plain-document→plain-text degradation, and
  an end-to-end routing test through the real dispatcher asserting the uploaded
  bytes/filename and the note's shape *and* that a second tap makes no HTTP
  request at all.
- Manual acceptance: live run against zarfilm before each milestone. SubDL
  needs a live key, so its acceptance check is one real query + one real
  document delivery against Telegram.

## 7. Deployment

- v1: `python -m src.main` on the owner's PC (Windows); `.env` beside it;
  auto-restart via a simple loop or NSSM/task scheduler is optional.
- Later: same long-polling process in a slim Docker image on a cheap VPS or a
  free PaaS — no inbound ports, no storage requirements, so any tier works.
  Links are not IP-bound, so no proxying concerns.

## 8. Milestones (for the implementation plan)

1. Scaffolding: models, exceptions, config — *per `CONTRIBUTING.md`, starts with
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
  remaining UI text templates in `CONTRIBUTING.md` are still proposals until the
  owner finalizes them in this review.
