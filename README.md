# Movie Bot

A private Telegram bot for finding movies and series: search by Persian or English title, then follow inline buttons (audio → quality → episodes) to get direct download links.

## Setup

1. Install:

   ```bash
   pip install -e ".[dev]"
   ```

2. Copy `.env.example` to `.env` and fill in the values:

   | Variable | Purpose |
   | --- | --- |
   | `BOT_TOKEN` | Telegram bot token from [@BotFather](https://t.me/BotFather) |
   | `ALLOWED_USER_IDS` | Comma-separated Telegram user IDs allowed to use the bot; the first one is the owner |
   | `OWNER_ID` | Owner Telegram ID: receives session-expiry alerts and is the /login account (falls back to the first `ALLOWED_USER_IDS` entry) |

   > **Note:** `OWNER_ID` alone does NOT grant bot access — the allowlist middleware only reads `ALLOWED_USER_IDS`, so the owner's Telegram ID must ALSO appear in `ALLOWED_USER_IDS` or every request (including `/login`) is rejected. For example: `ALLOWED_USER_IDS=5441961764` with `OWNER_ID=5441961764`.
   | `EMOJI` | Optional JSON map of role → custom emoji ID for button labels, e.g. `{"dub": "5368385512908012910"}` |
   | `PROXY_URL` | Optional; if Telegram is blocked on the host, set this to your local proxy endpoint, e.g. `socks5://127.0.0.1:10808` or `http://127.0.0.1:10809` |

3. Run:

   ```bash
   python -m src.main
   ```

## Docker

```bash
docker build -t movie-bot .
docker run --env-file .env movie-bot
```

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

The bot stores the session cookies in `session.json` and resumes working immediately. When the session expires, the owner receives an alert DM (rate-limited to one per 10 minutes) — repeat the same steps, since `/login` is the only way to (re)supply a session. Captchas are never solved and credentials are never stored.
