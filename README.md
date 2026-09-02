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
   | `ZARFILM_USERNAME` / `ZARFILM_PASSWORD` | Source-site account used to fetch download links |
   | `ALLOWED_USER_IDS` | Comma-separated Telegram user IDs allowed to use the bot; the first one is the owner |
   | `EMOJI` | Optional JSON map of role → custom emoji ID for button labels, e.g. `{"dub": "5368385512908012910"}` |

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

If the site session expires, log in to the site in a normal browser, copy the full `Cookie` header from a request to the site, then send `/login` to the bot from the owner account (the first ID in `ALLOWED_USER_IDS`) and paste the header. The bot stores the session cookies in `session.json` and resumes working.
