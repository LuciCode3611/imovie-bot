# Movie Bot

A private Telegram bot for finding movies and series: tap **جستجو**, type a Persian or English title, then follow inline buttons (audio → quality → episodes) to get direct download links.

## Setup

1. Install:

   ```bash
   pip install -e ".[dev]"
   ```

2. Copy `.env.example` to `.env` and fill in the values:

   | Variable | Purpose |
   | --- | --- |
   | `BOT_TOKEN` | Telegram bot token from [@BotFather](https://t.me/BotFather) |
   | `ALLOWED_USER_IDS` | Comma-separated Telegram user IDs allowed to use the bot; the first one is the owner. **Leave empty to allow everyone** (open bot). |
   | `OWNER_ID` | Owner Telegram ID: receives session-expiry alerts and is the /login account (falls back to the first `ALLOWED_USER_IDS` entry) |
   | `EMOJI` | Optional JSON map of role → custom emoji ID for button labels (roles: `original`, `dub`, `season`, `quality`, `result`). Roles without an ID — or an unset `EMOJI` — fall back to built-in unicode icons, so the bot never breaks either way |
   | `SESSION_PATH` | Optional path for the stored login session (default `session.json` in the working directory); in Docker, point it at a mounted volume |
   | `PROXY_URL` | Optional; if Telegram is blocked on the host, set this to your local proxy endpoint, e.g. `socks5://127.0.0.1:10808` or `http://127.0.0.1:10809` |
   | `SUBDL_API_KEY` | SubDL API key for the Persian subtitle search — free key from the [SubDL panel](https://subdl.com/panel/api) (2,000 requests/day). Without it the bot still runs and the subtitle section reports itself unavailable |
   | `SUBDL_BASE_URL` / `SUBDL_DOWNLOAD_URL` | Optional; SubDL API origin (default `https://api.subdl.com`) and public download origin (default `https://dl.subdl.com`) |

   > **Note:** When `ALLOWED_USER_IDS` is set, `OWNER_ID` alone does NOT grant access — the allowlist middleware only reads `ALLOWED_USER_IDS`, so the owner's Telegram ID must ALSO appear in it or every request (including `/login`) is rejected. For example: `ALLOWED_USER_IDS=5441961764` with `OWNER_ID=5441961764`. **If `ALLOWED_USER_IDS` is empty the bot is OPEN TO EVERY user** (and logs an info line at startup); in that open mode set `OWNER_ID` explicitly if you want `/login` and session alerts.

   Cards use Bot API 10.1 **rich messages** (poster + centered borderless metadata table + centered story pull-quote). On Telegram clients older than that the bot automatically falls back to the classic photo card. Subtitle cards are table-only — SubDL returns files, not posters or synopses.

3. Run:

   ```bash
   python -m src.main
   ```

## Search flow

Free text never hits the site: the user taps [ 🔍 جستجو ], the bot enters a listening state («نام فیلم یا سریال رو بنویس…»), and the next message becomes the search query. Text sent while not listening just gets a hint with the button attached. The listening mode resets automatically after results or no-results, and `/start` clears it.

## Subtitle search (SubDL)

Next to [ 🔍 جستجو ] there is [ 📝 جستجوی زیرنویس ] (also `/subtitle`). It arms its own listening state, calls the [SubDL API](https://subdl.com/api-doc) for **Persian (`FA`) subtitles only**, and pages the results exactly like the movie search (5 per page, `◀ 1/3 ▶`). Opening a result renders a rich card — a centered metadata table with the title, year, movie/series kind, seasons and file count — and **every subtitle file gets its own blue «دانلود …» button** under the card. There is no season sub-view, so the card never changes: a season with several archives simply gets one button per archive.

Tapping a button **sends the subtitle as a Telegram document** — renamed to something readable (`Interstellar (2014) — Interstellar.2014.1080p.BluRay.zip`) — in a single rich message, with the one instruction every archive needs quoted underneath it in a borderless, centered table:

> زیرنویس را از حالت فشرده خارج کنید و داخل مدیا پلیر اضافه کنید

There is no caption: a caption can't hold a table, and the instruction is the same for every title. On a client old enough to refuse a media block inside a rich message, the file is sent the classic way and the note follows as its own message — the zip is never lost. No download URL appears anywhere on the card, so neither the source host nor the API key is exposed; the key only ever authenticates the bot's own API calls.

Each tap is served in this order:

1. **Cached `file_id`** — if that archive was uploaded before, Telegram re-sends it from its own storage: instant, no bandwidth, and it does not touch SubDL's download limit. The cache is a SQLite table (`DB_PATH`) keyed by the download URL.
2. **Download + upload** — otherwise the bot fetches the public `dl.subdl.com` zip (streamed, capped at 40 MB, HTML "limit reached" interstitials rejected) and uploads it as a document, then remembers the `file_id`.
3. **Link fallback** — if the file is too large, SubDL refuses (404/429), or Telegram rejects the upload, the user gets a «🔗 لینک مستقیم دانلود» button instead of an error, so nobody leaves empty-handed.

> **Quota:** with documents, downloads come from the *server*, which shares SubDL's anonymous limit of 300/day per IP (raising it needs a paid plan). The `file_id` cache is what keeps that comfortable — every archive is downloaded at most once per database, so the limit is spent on new files only. `/status` shows the counters («ارسال N · کش M») if you ever want to watch it.

Series are grouped per season (`فصل 1`, `فصل 2`, …) and each button names the episodes it covers — «همه قسمت‌ها» for a full-season pack, «قسمت 1–8» for a part. A series query sends `full_season=1` so a season shows up as one zip instead of 30 single-episode files (and retries once without it when the title has no season pack at all); movies never send it.

`SUBDL_API_KEY` is the only requirement: set it as a variable on Railway (or in `.env`) and redeploy. Give the service a persistent volume for `DB_PATH` so the `file_id` cache survives redeploys — without it each archive is downloaded once per deploy instead of once, ever. The owner dashboard (`/status`) shows whether the key is picked up — «🟢 فعال — جستجو 3 · عنوان 2 · ارسال 5 · کش 4» — and a missing key logs a warning at startup. Results are cached like every other source — a query for `search_ttl` (1 h), a title's file list for `page_ttl` (6 h) — to stay inside the free quota.

## Docker

```bash
docker build -t movie-bot .
docker run --env-file .env \
  -v movie-bot-data:/app/data \
  -e SESSION_PATH=/app/data/session.json \
  movie-bot
```

The volume keeps the login session across container restarts; without it every redeploy needs a fresh `/login`. It also holds the SQLite database (`DB_PATH`, default `data/bot.db`) with users, content requests and the subtitle `file_id` cache. The container runs as a non-root user.

## Tests

```bash
python -m pytest
```

## Owner: session recovery

The bot has no source-site credentials — its login form is captcha-protected, so sessions come only from a browser cookie.

1. Log in to the site once in a normal browser.
2. In DevTools (Network tab) copy the `Cookie` request header of any request to the site — or just the value of the `wordpress_logged_in_...` row under Application → Cookies.
3. Send `/login` to the bot from the owner account (the `OWNER_ID`, or the first ID in `ALLOWED_USER_IDS`) and paste the cookie header.
   JSON, Netscape, or plain header exports from any browser cookie extension all work.

The bot deletes the cookie message immediately (and warns you to delete it manually if deletion fails), stores the session in `SESSION_PATH` with owner-only file permissions, and resumes working immediately. When the session expires, the owner receives an alert DM (rate-limited to one per 10 minutes) — repeat the same steps, since `/login` is the only way to (re)supply a session. Captchas are never solved and credentials are never stored.
