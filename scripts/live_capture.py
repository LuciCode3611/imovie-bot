import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from src.models.config import Config  # noqa: E402
from src.services.parsers import parse_cookies  # noqa: E402
from src.services.zarfilm import ZarfilmClient  # noqa: E402

FIXTURES = Path("tests/fixtures")
TARGETS = {
    "movie_interstellar_authed.html": "/interstellar-2014/",
    "series_dub_authed.html": "/batman-knightfall-part-1-knightfall-2026/",
}


async def main() -> None:
    raw = os.environ.get("ZARFILM_COOKIE", "")
    if not raw:
        sys.exit(
            "Set ZARFILM_COOKIE first: paste a JSON, Netscape, or header cookie export "
            "(any browser cookie extension works), or the Cookie request header of a "
            "logged-in request to zarfilm.com from DevTools."
        )
    cookies = parse_cookies(raw)
    if not any(name.startswith("wordpress_logged_in") for name in cookies):
        sys.exit("ZARFILM_COOKIE has no wordpress_logged_in_* cookie — copy the header from a logged-in request.")
    FIXTURES.mkdir(parents=True, exist_ok=True)
    client = ZarfilmClient(Config())
    client.set_cookies(cookies)
    client.mark_session_ready()
    for filename, path in TARGETS.items():
        response = await client._client.get(path)
        if response.status_code != 200:
            print(f"skipped {filename}: HTTP {response.status_code}")
            continue
        (FIXTURES / filename).write_bytes(response.content)
        print(f"saved {filename}: HTTP {response.status_code}, {len(response.content)} bytes")
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
