import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from src.models.config import Config  # noqa: E402
from src.services.parsers import parse_cookie_header  # noqa: E402
from src.services.zarfilm import ZarfilmClient  # noqa: E402

FIXTURES = Path("tests/fixtures")
TARGETS = {
    "movie_interstellar_authed.html": "/interstellar-2014/",
    "series_dub_authed.html": "<OWNER_SUPPLIES_SERIES_SLUG>",
}


async def main() -> None:
    raw = os.environ.get("ZARFILM_COOKIE", "")
    if not raw:
        sys.exit(
            "Set ZARFILM_COOKIE first: copy the Cookie request header of a logged-in "
            "request to zarfilm.com from browser DevTools (Network tab), or just the "
            "wordpress_logged_in_... row's value from Application > Cookies."
        )
    cookies = parse_cookie_header(raw)
    if not any(name.startswith("wordpress_logged_in") for name in cookies):
        sys.exit("ZARFILM_COOKIE has no wordpress_logged_in_* cookie — copy the header from a logged-in request.")
    FIXTURES.mkdir(parents=True, exist_ok=True)
    client = ZarfilmClient(Config())
    for name, value in cookies.items():
        client._client.cookies.set(name, value)
    client.mark_session_ready()
    for filename, path in TARGETS.items():
        response = await client._client.get(path)
        (FIXTURES / filename).write_bytes(response.content)
        print(f"saved {filename}: HTTP {response.status_code}, {len(response.content)} bytes")
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
