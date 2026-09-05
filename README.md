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
   | `SUBKADE_BASE_URL` | Optional; subtitle source origin (default `https://subkade.ir`) |

   > **Note:** When `ALLOWED_USER_IDS` is set, `OWNER_ID` alone does NOT grant access — the allowlist middleware only reads `ALLOWED_USER_IDS`, so the owner's Telegram ID must ALSO appear in it or every request (including `/login`) is rejected. For example: `ALLOWED_USER_IDS=5441961764` with `OWNER_ID=5441961764`. **If `ALLOWED_USER_IDS` is empty the bot is OPEN TO EVERY user** (and logs an info line at startup); in that open mode set `OWNER_ID` explicitly if you want `/login` and session alerts.

   Cards use Bot API 10.1 **rich messages** (poster + centered borderless metadata table + centered story pull-quote). On Telegram clients older than that the bot automatically falls back to the classic photo card.

3. Run:

   ```bash
   python -m src.main
   ```

## Search flow

Free text never hits the site: the user taps [ 🔍 جستجو ], the bot enters a listening state («نام فیلم یا سریال رو بنویس…»), and the next message becomes the search query. Text sent while not listening just gets a hint with the button attached. The listening mode resets automatically after results or no-results, and `/start` clears it.

## Subtitle search (subkade.ir)

Next to [ 🔍 جستجو ] there is [ 📝 جستجوی زیرنویس ] (also `/subtitle`). It arms its own listening state, searches [subkade.ir](https://subkade.ir/) and pages the results exactly like the movie search (5 per page, `◀ 1/3 ▶`). Opening a result renders a rich card — poster, metadata table (IMDb, genres, cast, translators, sync note), synopsis and a table with a «🔗 دریافت» link per Persian subtitle zip; series are grouped by season, and each season button lists its files as direct-download buttons. Only the free Persian archives on `dl1.subkade.ir` are scraped — the VIP-only English/Arabic lists are ignored. No login is required; the source domain can be overridden with `SUBKADE_BASE_URL`.

## Docker

```bash
docker build -t movie-bot .
docker run --env-file .env \
  -v movie-bot-data:/app/data \
  -e SESSION_PATH=/app/data/session.json \
  movie-bot
```

The volume keeps the login session across container restarts; without it every redeploy needs a fresh `/login`. The container runs as a non-root user.

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
