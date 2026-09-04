# Zarfilm Telegram Bot Implementation Plan

**Goal:** A private, allowlisted Telegram bot that searches zarfilm.com and delivers direct download links via drill-down inline keyboards (language → quality → file, seasons → quality → episode list).

**Architecture:** Single Python process, layered (`src/handlers`, `src/services`, `src/repos`, `src/models`). aiogram 3 long polling; httpx session with persisted login cookies and auto re-login; pure-function parsers from HTML fixtures; in-memory TTL cache + callback state (no database).

**Tech Stack:** Python 3.12, aiogram ≥ 3.31 (ButtonStyle, `icon_custom_emoji_id`), httpx, selectolax, pydantic v2 + pydantic-settings, pytest + pytest-asyncio.

**Spec:** `docs/design.md`. Two steps need live data: the Task 4 fixture capture and the Task 6 selector confirmation.

## Global Constraints

- Python `>=3.12`; aiogram `>=3.31` (button `style` + `icon_custom_emoji_id` need it); pydantic v2 everywhere.
- Explicit type hints on every function; Pydantic models for all data crossing layers; minimal comments (no obvious or conversational comments); no generic boilerplate.
- All user-facing text is Persian, RTL, parse mode `HTML`, and **source-neutral**: the string `zarfilm` (and «زرفیلم») must never appear in texts, buttons, or error messages users see — only in code identifiers, URLs, and logs.
- Direct links only — the bot never uploads media files to Telegram.
- Exactly one zarfilm session (owner's VIP); serialized site requests via `asyncio.Lock`; realistic Chrome User-Agent; TTL caches in front of all site calls.
- `callback_data` uses short keys (`m:<6-hex>` style) — never raw slugs; every value ≤ 64 bytes.
- Secrets only in `.env`; `session.json` never committed (already in `.gitignore`).
- Dev machine is Windows: use `pathlib.Path`, no POSIX-only calls.
- TDD: every task writes its test first, watches it fail, then implements; commit after each task with conventional messages.
- Run tests with `python -m pytest <file> -v` from repo root.

---

### Task 1: Package scaffold, exceptions, and domain models

**Files:**
- Create: `pyproject.toml`
- Create: `src/__init__.py`, `src/exceptions.py`, `src/models/__init__.py`, `src/models/movie.py`
- Test: `tests/test_exceptions.py`, `tests/test_models.py`

**Interfaces:**
- Produces: `MediaKind` (StrEnum: `MOVIE`, `SERIES`); `MovieSummary(slug: str, title_en: str, title_fa: str | None, year: int | None, poster_url: str | None, genres: list[str], kind: MediaKind)`; `DownloadLink(quality: str, url: str, size: str | None, host: str | None)`; `EpisodeLink(label: str, url: str, size: str | None, host: str | None)`; `QualityPack(quality: str, episodes: list[EpisodeLink])`; `Season(label: str, qualities: list[QualityPack])`; `MovieDetails(summary, imdb: str | None, runtime: str | None, plot: str | None, originals: list[DownloadLink], dubs: list[DownloadLink], seasons: list[Season])` with properties `is_series: bool`, `has_dub: bool`; exceptions `ZarfilmError`, `AuthError`, `SessionExpiredError`, `NotFoundError`, `ParseError` (all subclasses of `ZarfilmError`). All re-exported from `src/models/__init__.py`.

- [ ] **Step 1: Write pyproject and package init**

```toml
# pyproject.toml
[project]
name = "movie-bot"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "aiogram>=3.31",
    "httpx>=0.27",
    "selectolax>=0.3.21",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
]

[project.optional-dependencies]
dev = ["pytest>=8.2", "pytest-asyncio>=0.23"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["."]
```

```python
# src/__init__.py
```

```python
# src/models/__init__.py
from src.models.movie import (
    DownloadLink,
    EpisodeLink,
    MediaKind,
    MovieDetails,
    MovieSummary,
    QualityPack,
    Season,
)

__all__ = [
    "DownloadLink",
    "EpisodeLink",
    "MediaKind",
    "MovieDetails",
    "MovieSummary",
    "QualityPack",
    "Season",
]
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_exceptions.py
import pytest

from src.exceptions import AuthError, NotFoundError, ParseError, SessionExpiredError, ZarfilmError


@pytest.mark.parametrize("exc", [AuthError, SessionExpiredError, NotFoundError, ParseError])
def test_domain_exceptions_share_base(exc: type[Exception]) -> None:
    err = exc("boom")
    assert isinstance(err, ZarfilmError)
```

```python
# tests/test_models.py
import pytest
from pydantic import ValidationError

from src.models import DownloadLink, MediaKind, MovieDetails, MovieSummary, Season


def _summary(**overrides) -> MovieSummary:
    fields = {"slug": "interstellar-2014", "title_en": "Interstellar", "kind": MediaKind.MOVIE}
    fields.update(overrides)
    return MovieSummary(**fields)


def test_summary_defaults() -> None:
    s = _summary()
    assert s.title_fa is None and s.year is None and s.genres == []


def test_summary_requires_slug_and_title() -> None:
    with pytest.raises(ValidationError):
        MovieSummary(slug="x")


def _details(**overrides) -> MovieDetails:
    fields = {"summary": _summary()}
    fields.update(overrides)
    return MovieDetails(**fields)


def test_details_defaults_are_empty() -> None:
    d = _details()
    assert d.originals == [] and d.dubs == [] and d.seasons == []
    assert d.is_series is False and d.has_dub is False


def test_series_and_dub_flags() -> None:
    link = DownloadLink(quality="1080p", url="https://dl.example.com/f.mkv", size="2.1GB")
    d = _details(summary=_summary(kind=MediaKind.SERIES), dubs=[link])
    assert d.is_series is True and d.has_dub is True


def test_season_nesting() -> None:
    from src.models import EpisodeLink, QualityPack

    season = Season(
        label="فصل اول",
        qualities=[QualityPack(quality="1080p", episodes=[EpisodeLink(label="S01E01", url="https://dl.example.com/e01.mkv")])],
    )
    d = _details(summary=_summary(kind=MediaKind.SERIES), seasons=[season])
    assert d.seasons[0].qualities[0].episodes[0].label == "S01E01"
```

- [ ] **Step 3: Run tests, expect import errors**

Run: `python -m pytest tests/test_models.py tests/test_exceptions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src'` (or `No module named 'src.exceptions'`).

- [ ] **Step 4: Implement exceptions and models**

```python
# src/exceptions.py
class ZarfilmError(Exception): ...
class AuthError(ZarfilmError): ...
class SessionExpiredError(ZarfilmError): ...
class NotFoundError(ZarfilmError): ...
class ParseError(ZarfilmError): ...
```

```python
# src/models/movie.py
from enum import StrEnum

from pydantic import BaseModel, Field


class MediaKind(StrEnum):
    MOVIE = "movie"
    SERIES = "series"


class DownloadLink(BaseModel):
    quality: str
    url: str
    size: str | None = None
    host: str | None = None


class EpisodeLink(BaseModel):
    label: str
    url: str
    size: str | None = None
    host: str | None = None


class QualityPack(BaseModel):
    quality: str
    episodes: list[EpisodeLink] = Field(default_factory=list)


class Season(BaseModel):
    label: str
    qualities: list[QualityPack] = Field(default_factory=list)


class MovieSummary(BaseModel):
    slug: str
    title_en: str
    title_fa: str | None = None
    year: int | None = None
    poster_url: str | None = None
    genres: list[str] = Field(default_factory=list)
    kind: MediaKind = MediaKind.MOVIE


class MovieDetails(BaseModel):
    summary: MovieSummary
    imdb: str | None = None
    runtime: str | None = None
    plot: str | None = None
    originals: list[DownloadLink] = Field(default_factory=list)
    dubs: list[DownloadLink] = Field(default_factory=list)
    seasons: list[Season] = Field(default_factory=list)

    @property
    def is_series(self) -> bool:
        return self.summary.kind is MediaKind.SERIES

    @property
    def has_dub(self) -> bool:
        return bool(self.dubs)
```

- [ ] **Step 5: Install dependencies and run tests**

Run: `pip install -e ".[dev]"` then `python -m pytest tests/test_models.py tests/test_exceptions.py -v`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src tests
git commit -m "feat: package scaffold, domain exceptions, and movie/series models"
```

---

### Task 2: Config via pydantic-settings

**Files:**
- Create: `src/models/config.py`, `.env.example`
- Modify: `src/models/__init__.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config(BaseSettings)` — fields `bot_token: str`, `zarfilm_username: str`, `zarfilm_password: str`, `allowed_user_ids: list[int]`, `session_path: Path = Path("session.json")`, `search_ttl: int = 3600`, `page_ttl: int = 21600`, `state_ttl: int = 3600`, `emoji: dict[str, str] = {}`. Reads from `.env` / environment; `ALLOWED_USER_IDS` accepts `"111,222,333"`; `EMOJI` accepts a JSON object mapping role → custom emoji id. Re-exported from `src/models/__init__.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import pytest
from pydantic import ValidationError

from src.models.config import Config


def _base_env() -> dict[str, str]:
    return {"BOT_TOKEN": "1:abc", "ZARFILM_USERNAME": "u", "ZARFILM_PASSWORD": "p"}


def test_minimal_config(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = Config(**_base_env())
    assert cfg.allowed_user_ids == []
    assert cfg.search_ttl == 3600 and cfg.page_ttl == 21600 and cfg.state_ttl == 3600


def test_comma_separated_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _base_env() | {"ALLOWED_USER_IDS": " 111, 222 ,333"}
    cfg = Config(**env)
    assert cfg.allowed_user_ids == [111, 222, 333]


def test_emoji_json(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _base_env() | {"EMOJI": '{"dub": "5368385512908012910"}'}
    cfg = Config(**env)
    assert cfg.emoji["dub"] == "5368385512908012910"


def test_missing_token_rejected() -> None:
    with pytest.raises(ValidationError):
        Config(ZARFILM_USERNAME="u", ZARFILM_PASSWORD="p")
```

- [ ] **Step 2: Run, expect failure**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `No module named 'src.models.config'`.

- [ ] **Step 3: Implement**

```python
# src/models/config.py
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    zarfilm_username: str
    zarfilm_password: str
    allowed_user_ids: list[int] = []
    session_path: Path = Path("session.json")
    search_ttl: int = 3600
    page_ttl: int = 21600
    state_ttl: int = 3600
    emoji: dict[str, str] = {}

    @field_validator("allowed_user_ids", mode="before")
    @classmethod
    def _split_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(part) for part in value.replace(" ", "").split(",") if part]
        return value
```

Add to `src/models/__init__.py` imports and `__all__`: `from src.models.config import Config` / `"Config"`.

```python
# .env.example
BOT_TOKEN=
ZARFILM_USERNAME=
ZARFILM_PASSWORD=
ALLOWED_USER_IDS=
# optional JSON: role -> custom emoji id, e.g. {"dub": "5368385512908012910"}
EMOJI=
```

- [ ] **Step 4: Run tests, expect pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/models tests/test_config.py .env.example
git commit -m "feat: pydantic-settings config with allowlist and emoji mapping"
```

---

### Task 3: In-memory stores — TTLCache and CallbackState

**Files:**
- Create: `src/repos/__init__.py`, `src/repos/cache.py`, `src/repos/state.py`
- Test: `tests/test_cache.py`, `tests/test_state.py`

**Interfaces:**
- Produces: `TTLCache` with `async get(key: str) -> Any | None`, `async set(key: str, value: Any, ttl: int) -> None`.
- Produces: `CardEntry` dataclass — `summary: MovieSummary`, `details: MovieDetails | None = None`, `selection: str = ""`.
- Produces: `CallbackState(ttl: int)` with `create(entry: CardEntry) -> str` (returns 6-hex key), `get(key: str) -> CardEntry | None` (expired keys return `None` and are dropped), `drop(key: str) -> None`. Entries are mutable dataclasses: handlers mutate `entry.selection`/`entry.details` in place after `get`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cache.py
import asyncio

from src.repos.cache import TTLCache


async def test_set_get_roundtrip() -> None:
    cache = TTLCache()
    await cache.set("k", [1, 2], ttl=60)
    assert await cache.get("k") == [1, 2]


async def test_expiry_returns_none() -> None:
    cache = TTLCache()
    await cache.set("k", "v", ttl=-1)
    assert await cache.get("k") is None
    assert await cache.get("k") is None  # second read also clean


async def test_missing_key() -> None:
    assert await TTLCache().get("nope") is None
```

```python
# tests/test_state.py
from src.models import MediaKind, MovieSummary
from src.repos.state import CardEntry, CallbackState


def _entry() -> CardEntry:
    summary = MovieSummary(slug="interstellar-2014", title_en="Interstellar", kind=MediaKind.MOVIE)
    return CardEntry(summary=summary)


def test_create_returns_short_key() -> None:
    state = CallbackState(ttl=60)
    key = state.create(_entry())
    assert len(key) == 6
    assert int(key, 16) >= 0


def test_roundtrip_and_mutation() -> None:
    state = CallbackState(ttl=60)
    key = state.create(_entry())
    entry = state.get(key)
    assert entry is not None and entry.selection == ""
    entry.selection = "dub"
    assert state.get(key).selection == "dub"


def test_expiry_drops_entry() -> None:
    state = CallbackState(ttl=-1)
    key = state.create(_entry())
    assert state.get(key) is None


def test_drop() -> None:
    state = CallbackState(ttl=60)
    key = state.create(_entry())
    state.drop(key)
    assert state.get(key) is None
```

- [ ] **Step 2: Run, expect failure**

Run: `python -m pytest tests/test_cache.py tests/test_state.py -v`
Expected: FAIL — `No module named 'src.repos'`.

- [ ] **Step 3: Implement**

```python
# src/repos/__init__.py
```

```python
# src/repos/cache.py
import time
from typing import Any


class TTLCache:
    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float]] = {}

    async def get(self, key: str) -> Any | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        value, expires = entry
        if expires < time.monotonic():
            del self._data[key]
            return None
        return value

    async def set(self, key: str, value: Any, ttl: int) -> None:
        self._data[key] = (value, time.monotonic() + ttl)
```

```python
# src/repos/state.py
import secrets
import time
from dataclasses import dataclass

from src.models import MovieDetails, MovieSummary


@dataclass
class CardEntry:
    summary: MovieSummary
    details: MovieDetails | None = None
    selection: str = ""


class CallbackState:
    def __init__(self, ttl: int) -> None:
        self._ttl = ttl
        self._data: dict[str, tuple[CardEntry, float]] = {}

    def create(self, entry: CardEntry) -> str:
        self._sweep()
        key = secrets.token_hex(3)
        self._data[key] = (entry, time.monotonic() + self._ttl)
        return key

    def get(self, key: str) -> CardEntry | None:
        item = self._data.get(key)
        if item is None:
            return None
        entry, expires = item
        if expires < time.monotonic():
            del self._data[key]
            return None
        return entry

    def drop(self, key: str) -> None:
        self._data.pop(key, None)

    def _sweep(self) -> None:
        now = time.monotonic()
        expired = [key for key, (_, expires) in self._data.items() if expires < now]
        for key in expired:
            del self._data[key]
```

- [ ] **Step 4: Run tests, expect pass**

Run: `python -m pytest tests/test_cache.py tests/test_state.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add src/repos tests
git commit -m "feat: in-memory TTL cache and callback drill-down state store"
```

---

### Task 4: ZarfilmClient auth — login, session persistence, live fixture capture  ⛔ live-data gate

**Files:**
- Create: `src/services/__init__.py`, `src/services/zarfilm.py` (auth core only), `scripts/live_capture.py`
- Test: `tests/test_client_auth.py`

**Interfaces:**
- Produces: `ZarfilmClient(config: Config, transport: httpx.AsyncBaseTransport | None = None)` with methods `async login() -> None`, `async ensure_session() -> None`, `async close() -> None`, attribute `_client: httpx.AsyncClient` (base_url `https://zarfilm.com`, Chrome UA, 20 s timeout, `follow_redirects=True`). Login POSTs to `/sign-in/` with form fields `log`, `pwd`, `wp-submit`, `redirect_to`; success = any cookie named `wordpress_logged_in_*`. Session persists to `config.session_path` (JSON cookie dict) and restores on construction of a new client.
- Consumes: `Config`, `AuthError` from Task 1–2.
- **Later tasks call** `ensure_session()` and `login()`; Task 7 adds `search()`/`movie()` on top of this class.
- Live capture produces `tests/fixtures/movie_interstellar_authed.html` and `tests/fixtures/series_dub_authed.html` used by Task 6.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_client_auth.py
import json

import httpx
import pytest

from src.exceptions import AuthError
from src.models.config import Config
from src.services.zarfilm import ZarfilmClient

LOGIN_FORM = {"log": "u", "pwd": "p"}


def _app(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/sign-in/" and request.method == "POST":
        form = dict(pair.split("=", 1) for pair in request.content.decode().split("&"))
        if form.get("log") == "u" and form.get("pwd") == "p":
            return httpx.Response(
                302,
                headers={"Set-Cookie": "wordpress_logged_in_abc=user%7C1; Path=/", "Location": "/"},
            )
        return httpx.Response(200, text="<html>login page</html>")
    if request.url.path == "/" and request.method == "GET":
        if "wordpress_logged_in_abc" in request.headers.get("Cookie", ""):
            return httpx.Response(200, text="<html>member home</html>")
        return httpx.Response(200, text='<html><a class="btnLoginHeader">ورود / عضویت</a></html>')
    return httpx.Response(404)


def _config(tmp_path) -> Config:
    return Config(
        bot_token="1:abc",
        zarfilm_username="u",
        zarfilm_password="p",
        session_path=tmp_path / "session.json",
    )


async def test_login_success_persists_cookies(tmp_path) -> None:
    client = ZarfilmClient(_config(tmp_path), transport=httpx.MockTransport(_app))
    await client.login()
    saved = json.loads((tmp_path / "session.json").read_text(encoding="utf-8"))
    assert any(key.startswith("wordpress_logged_in") for key in saved)
    await client.close()


async def test_login_bad_credentials_raises(tmp_path) -> None:
    cfg = Config(bot_token="1:abc", zarfilm_username="wrong", zarfilm_password="x", session_path=tmp_path / "s.json")
    client = ZarfilmClient(cfg, transport=httpx.MockTransport(_app))
    with pytest.raises(AuthError):
        await client.login()
    await client.close()


async def test_restored_session_skips_login(tmp_path) -> None:
    cfg = _config(tmp_path)
    first = ZarfilmClient(cfg, transport=httpx.MockTransport(_app))
    await first.login()
    await first.close()

    calls = {"posts": 0}

    def counting_app(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sign-in/":
            calls["posts"] += 1
        return _app(request)

    second = ZarfilmClient(cfg, transport=httpx.MockTransport(counting_app))
    await second.ensure_session()
    assert calls["posts"] == 0
    await second.close()
```

- [ ] **Step 2: Run, expect failure**

Run: `python -m pytest tests/test_client_auth.py -v`
Expected: FAIL — `No module named 'src.services'`.

- [ ] **Step 3: Implement the auth core**

```python
# src/services/__init__.py
```

```python
# src/services/zarfilm.py
import asyncio
import json
from pathlib import Path

import httpx

from src.exceptions import AuthError
from src.models.config import Config

BASE_URL = "https://zarfilm.com"
LOGIN_PATH = "/sign-in/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


class ZarfilmClient:
    def __init__(self, config: Config, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._cfg = config
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"User-Agent": USER_AGENT},
            timeout=20.0,
            follow_redirects=True,
            transport=transport,
        )
        self._lock = asyncio.Lock()
        self._logged_in = False

    async def close(self) -> None:
        await self._client.aclose()

    async def login(self) -> None:
        async with self._lock:
            await self._login_locked()

    async def _login_locked(self) -> None:
        self._client.cookies.clear()
        response = await self._client.post(
            LOGIN_PATH,
            data={
                "log": self._cfg.zarfilm_username,
                "pwd": self._cfg.zarfilm_password,
                "wp-submit": "ورود",
                "redirect_to": BASE_URL,
            },
        )
        response.raise_for_status()
        if not any(name.startswith("wordpress_logged_in") for name in self._client.cookies.keys()):
            raise AuthError("login rejected: no session cookie; check credentials or form fields")
        Path(self._cfg.session_path).write_text(json.dumps(dict(self._client.cookies)), encoding="utf-8")
        self._logged_in = True

    async def ensure_session(self) -> None:
        if self._logged_in:
            return
        if self._restore_session():
            self._logged_in = True
            return
        await self._login_locked()

    def _restore_session(self) -> bool:
        path = Path(self._cfg.session_path)
        if not path.exists():
            return False
        try:
            cookies: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not any(name.startswith("wordpress_logged_in") for name in cookies):
            return False
        for name, value in cookies.items():
            self._client.cookies.set(name, value)
        return True
```

- [ ] **Step 4: Run tests, expect pass**

Run: `python -m pytest tests/test_client_auth.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Live capture — user gate**

1. Create `.env` from `.env.example`, fill in real `BOT_TOKEN`, `ZARFILM_USERNAME`, `ZARFILM_PASSWORD`, `ALLOWED_USER_IDS`.
2. Write and run `scripts/live_capture.py` (owner runs it locally; it uses the same `ZarfilmClient`):

```python
# scripts/live_capture.py
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from src.models.config import Config  # noqa: E402
from src.services.zarfilm import ZarfilmClient  # noqa: E402

FIXTURES = Path("tests/fixtures")
TARGETS = {
    "movie_interstellar_authed.html": "/interstellar-2014/",
    "series_dub_authed.html": "<OWNER_SUPPLIES_SERIES_SLUG>",
}


async def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    client = ZarfilmClient(Config())
    await client.login()
    for filename, path in TARGETS.items():
        response = await client._client.get(path)
        (FIXTURES / filename).write_bytes(response.content)
        print(f"saved {filename}: HTTP {response.status_code}, {len(response.content)} bytes")
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
```

3. Owner edits `TARGETS` with a series slug that has a Persian dub (e.g. from zarfilm's سریال section), then runs `python scripts/live_capture.py`.
4. Expected output: `HTTP 200` for both files; the movie fixture contains real download rows (verify: `grep -c "1080" tests/fixtures/movie_interstellar_authed.html` returns > 0).
5. If login fails with `AuthError`, owner re-runs step 3 after confirming credentials; if the form fields differ, inspect `tests/fixtures/sign-in form` (save via one-off `httpx.get(BASE_URL + "/sign-in/")`) and adjust the `data=` dict in `_login_locked` — that is the only place form fields live.
6. Commit the fixtures and script:

```bash
git add scripts/live_capture.py tests/fixtures/movie_interstellar_authed.html tests/fixtures/series_dub_authed.html
git commit -m "test: capture authed zarfilm fixtures via live login"
```

- [ ] **Step 6: Commit the auth implementation (if not already committed with fixtures)**

```bash
git add src/services tests/test_client_auth.py
git commit -m "feat: zarfilm login with persistent session and re-login core"
```

---

### Task 5: Parsers — search cards and movie metadata

**Files:**
- Create: `src/services/parsers.py`
- Create: `tests/fixtures/search_interstellar.html`, `tests/fixtures/movie_interstellar_public.html` (copies of the probed pages)
- Test: `tests/test_parsers.py`

**Interfaces:**
- Consumes: models from Task 1, `ParseError`.
- Produces: `parse_search(html: HTMLParser) -> list[MovieSummary]`; `parse_movie(html: HTMLParser, slug: str) -> MovieDetails` (metadata only in this task: summary fields + imdb + plot + kind; download fields empty; Task 6 fills them). Both raise `ParseError` on malformed input.
- Verified selector facts (from probed fixtures):
  - Search cards: `.posts_hoder_archive .item_body_widget[data-type="post"]`; slug URL `a.bgbackitem[href]`; English title `.item-foot-title h3.movie-title`; year `.score .year`; IMDb `.score .rate` (text like `8.6/10`); genres `.genres_links h3 span`; poster `a.bgbackitem img[src]`.
  - Movie page: JSON-LD `<script type="application/ld+json" class="yoast-schema-graph">` → `@graph` → `WebPage.name` (e.g. `دانلود فیلم Interstellar 2014 - میان‌ستاره‌ای`), `ImageObject.url` (poster), `Article.headline`; plot `div.plot`; IMDb `.item.imdb strong`.

- [ ] **Step 1: Create fixtures**

```bash
mkdir -p tests/fixtures
cp _probe_search.html tests/fixtures/search_interstellar.html
cp _probe_movie.html tests/fixtures/movie_interstellar_public.html
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_parsers.py
from pathlib import Path

import pytest
from selectolax.parser import HTMLParser

from src.exceptions import ParseError
from src.models import MediaKind
from src.services.parsers import parse_movie, parse_search

FIXTURES = Path(__file__).parent / "fixtures"


def test_search_parses_results() -> None:
    html = HTMLParser((FIXTURES / "search_interstellar.html").read_text(encoding="utf-8"))
    results = parse_search(html)
    assert results, "search page should yield at least one result"
    first = next(r for r in results if r.slug == "interstellar-2014")
    assert first.title_en == "Interstellar"
    assert first.year == 2014
    assert "درام" in first.genres
    assert first.poster_url and first.poster_url.startswith("https")


def test_movie_metadata_from_public_page() -> None:
    html = HTMLParser((FIXTURES / "movie_interstellar_public.html").read_text(encoding="utf-8"))
    details = parse_movie(html, "interstellar-2014")
    assert details.summary.title_en == "Interstellar"
    assert details.summary.title_fa == "میان‌ستاره‌ای"
    assert details.summary.year == 2014
    assert details.summary.kind is MediaKind.MOVIE
    assert details.imdb == "8.6"
    assert details.plot and details.plot.startswith("در حالی که")
    assert details.summary.poster_url and "wp-content" in details.summary.poster_url


def test_parse_error_on_garbage() -> None:
    with pytest.raises(ParseError):
        parse_movie(HTMLParser("<html><body></body></html>"), "nothing-2000")
```

- [ ] **Step 3: Run, expect failure**

Run: `python -m pytest tests/test_parsers.py -v`
Expected: FAIL — `No module named 'src.services.parsers'`.

- [ ] **Step 4: Implement parsers (metadata part)**

```python
# src/services/parsers.py
import json
import re

from selectolax.parser import HTMLParser

from src.exceptions import ParseError
from src.models import MediaKind, MovieDetails, MovieSummary

TITLE_PREFIXES = ("دانلود رایگان سریال ", "دانلود رایگان فیلم ", "دانلود سریال ", "دانلود انیمیشن ", "دانلود فیلم ")


def parse_search(html: HTMLParser) -> list[MovieSummary]:
    results: list[MovieSummary] = []
    for card in html.css('.posts_hoder_archive .item_body_widget[data-type="post"]'):
        link = card.css_first("a.bgbackitem")
        if link is None or not link.attributes.get("href"):
            continue
        slug = link.attributes["href"].rstrip("/").rsplit("/", 1)[-1]
        poster_node = card.css_first("a.bgbackitem img")
        rate = _text(card, ".score .rate")
        results.append(
            MovieSummary(
                slug=slug,
                title_en=_text(card, ".item-foot-title h3.movie-title") or slug,
                title_fa=None,
                year=_int_or_none(_text(card, ".score .year")),
                poster_url=poster_node.attributes.get("src") if poster_node else None,
                genres=[node.text(strip=True) for node in card.css(".genres_links h3 span") if node.text(strip=True)],
            )
        )
    return results


def parse_movie(html: HTMLParser, slug: str) -> MovieDetails:
    graph = _jsonld_graph(html)
    webpage = _node(graph, "WebPage")
    if not webpage.get("name"):
        raise ParseError("movie page without JSON-LD WebPage name")
    title_en, title_fa = _split_title(webpage["name"])
    poster = _node(graph, "ImageObject").get("url")
    summary = MovieSummary(
        slug=slug,
        title_en=title_en,
        title_fa=title_fa,
        year=_year_from_slug(slug),
        poster_url=poster,
        kind=_detect_kind(webpage["name"]),
    )
    details = MovieDetails(
        summary=summary,
        imdb=_text(html, ".item.imdb strong"),
        plot=_text(html, "div.plot"),
    )
    return _parse_download_box(html, details)


def _parse_download_box(html: HTMLParser, details: MovieDetails) -> MovieDetails:
    return details  # Task 6 replaces this stub with real parsing


def _jsonld_graph(html: HTMLParser) -> dict:
    for node in html.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text())
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and isinstance(data.get("@graph"), list):
            return data
    return {}


def _node(graph: dict, node_type: str) -> dict:
    for node in graph.get("@graph", []):
        if node.get("@type") == node_type:
            return node
    return {}


def _split_title(name: str) -> tuple[str, str | None]:
    title = name
    for prefix in TITLE_PREFIXES:
        if title.startswith(prefix):
            title = title[len(prefix):]
            break
    if " - " in title:
        en, fa = title.rsplit(" - ", 1)
        return en.strip(), fa.strip()
    return title.strip(), None


def _detect_kind(title: str) -> MediaKind:
    return MediaKind.SERIES if "سریال" in title or "مجموعه" in title else MediaKind.MOVIE


def _year_from_slug(slug: str) -> int | None:
    match = re.search(r"-(\d{4})$", slug)
    return int(match.group(1)) if match else None


def _text(scope, selector: str) -> str | None:
    node = scope.css_first(selector)
    return node.text(strip=True) if node else None


def _int_or_none(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None
```

- [ ] **Step 5: Run tests, fix, repeat**

Run: `python -m pytest tests/test_parsers.py -v`
Expected: PASS. If a selector yields nothing on the real fixtures, re-inspect the fixture with `python -c "..."` grep snippets from the spec's selector facts and adjust only the selector strings — model shapes stay fixed.

- [ ] **Step 6: Commit**

```bash
git add src/services/parsers.py tests/test_parsers.py tests/fixtures/search_interstellar.html tests/fixtures/movie_interstellar_public.html
git commit -m "feat: search card and movie metadata parsers with real fixtures"
```

---

### Task 6: Download-box parser — dubs, seasons, qualities, episodes  ⛔ live-data gate

**Files:**
- Modify: `src/services/parsers.py` (`_parse_download_box`)
- Test: `tests/test_parsers_download.py`

**Interfaces:**
- Consumes: fixtures `tests/fixtures/movie_interstellar_authed.html`, `tests/fixtures/series_dub_authed.html` (Task 4 Step 5).
- Produces: completed `parse_movie` behavior — fills `originals: list[DownloadLink]`, `dubs: list[DownloadLink]` (empty when the movie has no dub), `seasons: list[Season]` (series only; implies `kind = SERIES`), `summary.kind` corrected to SERIES when season structure found. Selector constants live in one module-level dict `DL_SELECTORS` so site changes are one-place fixes.

- [ ] **Step 1: Discover the download-box markup in the authed fixtures**

Run these inspections and note the class names of: quality row containers, language/dub grouping, season boxes, per-episode rows, size text nodes:

```bash
python - <<'PY'
from selectolax.parser import HTMLParser
from pathlib import Path
for name in ("movie_interstellar_authed.html", "series_dub_authed.html"):
    html = HTMLParser((Path("tests/fixtures") / name).read_text(encoding="utf-8"))
    for sel in ("[data-tab_id]", ".single-tab-dlbox", ".download-links", "[class*=quality]", "[class*=season]", "[class*=dub]", "[class*=episode]"):
        nodes = html.css(sel)
        if nodes:
            print(name, sel, len(nodes), "first class:", nodes[0].attributes.get("class"))
PY
```

Confirm the identified selectors against the visible structure (owner eyeballs one page in a browser if ambiguous), then set the constants in Step 3 accordingly. If dub/season grouping turns out to be flat rows with text markers (e.g. rows whose text contains «دوبله»), the classifier in Step 3 handles both shapes: rows are grouped by their container, language by marker text, seasons by their heading text.

- [ ] **Step 2: Write the failing tests (shape-based, capture-independent)**

```python
# tests/test_parsers_download.py
import re
from pathlib import Path

from selectolax.parser import HTMLParser

from src.models import MediaKind
from src.services.parsers import parse_movie

FIXTURES = Path(__file__).parent / "fixtures"


def _details(name: str):
    return parse_movie(HTMLParser((FIXTURES / name).read_text(encoding="utf-8")), "probe-slug-2000")


def test_authed_movie_has_original_links() -> None:
    details = _details("movie_interstellar_authed.html")
    assert details.originals, "authed movie page must expose original-audio links"
    assert all(re.fullmatch(r"\d{3,4}p", link.quality) for link in details.originals)
    assert all(link.url.startswith("http") for link in details.originals)


def test_size_and_host_extracted_when_present() -> None:
    details = _details("movie_interstellar_authed.html")
    with_size = [link for link in details.originals + details.dubs if link.size]
    assert with_size, "expected at least one link with a parsed size"
    assert all(re.search(r"\d+(\.\d+)?\s?(GB|MB)", link.size, re.I) for link in with_size)


def test_series_structure() -> None:
    details = _details("series_dub_authed.html")
    assert details.is_series
    assert details.seasons, "series page must expose seasons"
    for season in details.seasons:
        assert season.label
        for pack in season.qualities:
            assert re.fullmatch(r"\d{3,4}p", pack.quality)
            assert pack.episodes
            assert all(e.label and e.url.startswith("http") for e in pack.episodes)
```

- [ ] **Step 3: Run, expect failure, then implement**

Run: `python -m pytest tests/test_parsers_download.py -v`
Expected: FAIL — `originals` empty (stub returns details untouched).

Replace `_parse_download_box` with real parsing built on the constants from Step 1. Shape of the implementation (selector values come from Step 1; the grouping logic below is final):

```python
DL_SELECTORS = {
    "box": ".single-tab-dlbox",          # confirm/adjust in Step 1
    "quality_row": "[class*=quality]",   # confirm/adjust in Step 1
    "link": "a",                          # confirm/adjust in Step 1
    "season_heading": "[class*=season]",  # confirm/adjust in Step 1
}
DUB_MARKER = "دوبله"
SIZE_RE = re.compile(r"\d+(?:\.\d+)?\s?(?:GB|MB)", re.I)
QUALITY_RE = re.compile(r"\d{3,4}p", re.I)


def _parse_download_box(html: HTMLParser, details: MovieDetails) -> MovieDetails:
    rows = html.css(DL_SELECTORS["quality_row"])
    originals: list[DownloadLink] = []
    dubs: list[DownloadLink] = []
    seasons: list[Season] = []
    current_season: Season | None = None
    for row in rows:
        anchor = row.css_first(DL_SELECTORS["link"]) or row
        href = anchor.attributes.get("href")
        if not href or not href.startswith("http"):
            continue
        text = row.text(strip=True)
        quality_match = QUALITY_RE.search(text)
        if not quality_match:
            continue
        quality = quality_match.group(0).lower()
        size_match = SIZE_RE.search(text)
        host = re.sub(r"^www\.", "", urlparse(href).netloc)
        if _is_season_heading(text, html, row):
            current_season = Season(label=text[:40])
            seasons.append(current_season)
            continue
        link = DownloadLink(quality=quality, url=href, size=size_match.group(0) if size_match else None, host=host)
        if current_season is not None:
            _append_episode(current_season, link)
        elif DUB_MARKER in text:
            dubs.append(link)
        else:
            originals.append(link)
    details.originals = originals
    details.dubs = dubs
    details.seasons = seasons
    if seasons:
        details.summary.kind = MediaKind.SERIES
    return details


def _append_episode(season: Season, link: DownloadLink) -> None:
    episode_label = _episode_label(link.url) or f"{len(season.qualities) + 1}"
    for pack in season.qualities:
        if pack.quality == link.quality:
            pack.episodes.append(EpisodeLink(label=episode_label, url=link.url, size=link.size, host=link.host))
            return
    season.qualities.append(
        QualityPack(quality=link.quality, episodes=[EpisodeLink(label=episode_label, url=link.url, size=link.size, host=link.host)])
    )


def _episode_label(url: str) -> str | None:
    match = re.search(r"[Ss](\d{1,2})[Ee](\d{1,3})", url)
    return f"S{match.group(1).zfill(2)}E{match.group(2).zfill(2)}" if match else None
```

Add imports at top of module: `from urllib.parse import urlparse`, and extend the model imports with `DownloadLink, EpisodeLink, QualityPack, Season`. Implement `_is_season_heading(text, html, row)` per the shape found in Step 1 — a row is a season heading when its element matches `DL_SELECTORS["season_heading"]` and its text contains «فصل»; minimal version:

```python
def _is_season_heading(text: str, html: HTMLParser, row) -> bool:
    return "فصل" in text and QUALITY_RE.search(text) is None
```

- [ ] **Step 4: Run the full parser suite, expect pass**

Run: `python -m pytest tests/test_parsers.py tests/test_parsers_download.py -v`
Expected: PASS. If a fixture proves the guessed selector wrong, adjust only `DL_SELECTORS` values (Step 1 data), not the grouping logic; rerun.

- [ ] **Step 5: Commit**

```bash
git add src/services/parsers.py tests/test_parsers_download.py
git commit -m "feat: download box parser for dubs, seasons, qualities, and episodes"
```

---

### Task 7: ZarfilmClient fetch methods — search, movie, expiry re-login

**Files:**
- Modify: `src/services/zarfilm.py`
- Test: `tests/test_client_fetch.py`

**Interfaces:**
- Consumes: `parse_search`, `parse_movie` (Tasks 5–6); `NotFoundError`, `ParseError`.
- Produces: `async search(query: str) -> list[MovieSummary]` (GET `/?s=<query>`); `async movie(slug: str) -> MovieDetails` (GET `/<slug>/`, logged-in wrapper); internal `async _get(path: str, **params) -> httpx.Response` — serializes through `self._lock`, retries once on `httpx.TransportError` after 1 s; logged-in wrapper re-logins once when the page shows the logged-out header (`btnLoginHeader` marker) and raises `AuthError` if it still fails; 404 → `NotFoundError`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_client_fetch.py
import json
from pathlib import Path

import httpx
import pytest

from src.exceptions import AuthError, NotFoundError
from src.models.config import Config
from src.services.zarfilm import ZarfilmClient

FIXTURES = Path(__file__).parent / "fixtures"
PUBLIC_SEARCH = (FIXTURES / "search_interstellar.html").read_text(encoding="utf-8")
PUBLIC_MOVIE = (FIXTURES / "movie_interstellar_public.html").read_text(encoding="utf-8")

LOGGED_OUT_MARK = 'class="btnLoginHeader"'
COOKIE = "wordpress_logged_in_abc=user%7C1; Path=/"


def _app(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    cookie_ok = "wordpress_logged_in_abc" in request.headers.get("Cookie", "")
    if path == "/sign-in/" and request.method == "POST":
        return httpx.Response(302, headers={"Set-Cookie": COOKIE, "Location": "/"})
    if path == "/" and request.method == "GET":
        return httpx.Response(200, text=PUBLIC_SEARCH)
    if path == "/interstellar-2014/":
        if cookie_ok:
            return httpx.Response(200, text=PUBLIC_MOVIE)
        return httpx.Response(200, text=f"<html><div {LOGGED_OUT_MARK}></div></html>")
    if path == "/missing-2000/":
        return httpx.Response(404, text="not found")
    return httpx.Response(404)


def _client(tmp_path) -> ZarfilmClient:
    cfg = Config(bot_token="1:abc", zarfilm_username="u", zarfilm_password="p", session_path=tmp_path / "s.json")
    return ZarfilmClient(cfg, transport=httpx.MockTransport(_app))


async def test_search_returns_summaries(tmp_path) -> None:
    client = _client(tmp_path)
    results = await client.search("interstellar")
    assert any(r.slug == "interstellar-2014" for r in results)
    await client.close()


async def test_movie_404_raises_not_found(tmp_path) -> None:
    client = _client(tmp_path)
    with pytest.raises(NotFoundError):
        await client.movie("missing-2000")
    await client.close()


async def test_movie_logs_in_when_logged_out(tmp_path) -> None:
    client = _client(tmp_path)
    details = await client.movie("interstellar-2014")
    assert details.summary.slug == "interstellar-2014"
    await client.close()


async def test_search_transport_retry(tmp_path) -> None:
    state = {"failed_once": False}

    def flaky(request: httpx.Request) -> httpx.Response:
        if not state["failed_once"]:
            state["failed_once"] = True
            raise httpx.ConnectError("boom", request=request)
        return _app(request)

    cfg = Config(bot_token="1:abc", zarfilm_username="u", zarfilm_password="p", session_path=tmp_path / "s.json")
    client = ZarfilmClient(cfg, transport=httpx.MockTransport(flaky))
    results = await client.search("interstellar")
    assert isinstance(results, list)
    await client.close()
```

- [ ] **Step 2: Run, expect failure**

Run: `python -m pytest tests/test_client_fetch.py -v`
Expected: FAIL — `ZarfilmClient` has no attribute `search`.

- [ ] **Step 3: Implement fetch methods**

Append to `src/services/zarfilm.py` (imports: `from src.exceptions import AuthError, NotFoundError`, `from src.services.parsers import parse_movie, parse_search`, `from src.models import MovieDetails, MovieSummary`):

```python
    LOGGED_OUT_MARK = "btnLoginHeader"

    async def search(self, query: str) -> list[MovieSummary]:
        response = await self._get("/", params={"s": query})
        response.raise_for_status()
        return parse_search(HTMLParser(response.text))

    async def movie(self, slug: str) -> MovieDetails:
        response = await self._get_logged_in(f"/{slug}/")
        if response.status_code == 404:
            raise NotFoundError(slug)
        response.raise_for_status()
        return parse_movie(HTMLParser(response.text), slug)

    async def _get_logged_in(self, path: str) -> httpx.Response:
        await self.ensure_session()
        response = await self._get(path)
        if self.LOGGED_OUT_MARK in response.text:
            self._logged_in = False
            async with self._lock:
                await self._login_locked()
            response = await self._get(path)
            if self.LOGGED_OUT_MARK in response.text:
                raise AuthError("session expired and re-login did not restore access")
        return response

    async def _get(self, path: str, **kwargs) -> httpx.Response:
        async with self._lock:
            try:
                return await self._client.get(path, **kwargs)
            except httpx.TransportError:
                await asyncio.sleep(1.0)
                return await self._client.get(path, **kwargs)
```

Add `from selectolax.parser import HTMLParser` to the module imports.

- [ ] **Step 4: Run the whole suite, expect pass**

Run: `python -m pytest -v`
Expected: PASS (all prior tests green too).

- [ ] **Step 5: Commit**

```bash
git add src/services/zarfilm.py tests/test_client_fetch.py
git commit -m "feat: zarfilm search and movie fetch with re-login and retry"
```

---

### Task 8: Formatting — card text and drill-down keyboards

**Files:**
- Create: `src/services/formatting.py`
- Test: `tests/test_formatting.py`

**Interfaces:**
- Consumes: models (Task 1); `ButtonStyle` from aiogram.
- Produces:
  - `card_text(details: MovieDetails) -> str` — HTML-escaped RTL Persian card per `CONTRIBUTING.md` template (title/year line, ⭐ IMDb · 🎭 genres · ⏱ runtime line, truncated plot ≤ ~300 chars).
  - `search_keyboard(results: list[tuple[str, CardEntry]]) -> InlineKeyboardMarkup` — one button per result, `callback_data=f"m:{key}"`, style PRIMARY.
  - `root_keyboard(details: MovieDetails, key: str) -> InlineKeyboardMarkup` — dub movie: `[دانلود با زبان اصلی]` PRIMARY + `[دانلود با دوبله فارسی]` SUCCESS → callbacks `l:{key}:orig` / `l:{key}:dub`; no-dub movie: quality buttons (from `details.originals`) → `q:{key}:orig:{idx}`; series: season buttons → `s:{key}:{idx}`.
  - `quality_keyboard(links: list[DownloadLink], key: str, audio: str) -> InlineKeyboardMarkup` — all PRIMARY, labels `{quality} - {size}` when size known → `q:{key}:{audio}:{idx}`, plus `[انصراف]` DANGER → `x:{key}`.
  - `season_quality_keyboard(packs: list[QualityPack], key: str) -> InlineKeyboardMarkup` — one PRIMARY button per pack labeled by quality → `q:{key}:s:{idx}`, plus `[انصراف]` DANGER.
  - `file_keyboard(links: list[DownloadLink], key: str) -> InlineKeyboardMarkup` — URL buttons `⬇ {size} — {host}` + `[انصراف]` DANGER.
  - `episode_list_text(pack: QualityPack) -> str` — HTML list of `<a href="{url}">{label}</a>` with sizes.
  - Emoji handling: module-level `FALLBACK_ICONS: dict[str, str]`; `apply_icon(button_text: str, role: str, emoji_map: dict[str, str]) -> InlineKeyboardButton` — sets `icon_custom_emoji_id=emoji_map[role]` when present, else prefixes the text with `FALLBACK_ICONS[role]`.
  - All callbacks ≤ 64 bytes; `parse_mode="HTML"` assumed on the bot side.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_formatting.py
from src.models import (
    DownloadLink,
    EpisodeLink,
    MediaKind,
    MovieDetails,
    MovieSummary,
    QualityPack,
    Season,
)
from src.repos.state import CardEntry
from src.services.formatting import (
    apply_icon,
    card_text,
    episode_list_text,
    file_keyboard,
    quality_keyboard,
    root_keyboard,
    search_keyboard,
)


def _details(dub: bool = False, series: bool = False) -> MovieDetails:
    summary = MovieSummary(
        slug="interstellar-2014",
        title_en="Interstellar",
        title_fa="میان‌ستاره‌ای",
        year=2014,
        genres=["درام", "علمی تخیلی"],
        kind=MediaKind.SERIES if series else MediaKind.MOVIE,
    )
    link = DownloadLink(quality="1080p", url="https://dl.example.com/f.mkv", size="2.1GB", host="dl.example.com")
    return MovieDetails(
        summary=summary,
        imdb="8.6",
        plot="در حالی که قحطی و گرسنگی به کره ی زمین چیره شده، گروهی از ستاره شناسان تصمیم میگیرند...",
        dubs=[link] if dub else [],
        originals=[] if series else [link],
        seasons=[Season(label="فصل اول", qualities=[QualityPack(quality="1080p", episodes=[EpisodeLink(label="S01E01", url="https://dl.example.com/e01.mkv", size="300MB", host="dl.example.com")])])] if series else [],
    )


def test_card_text_contains_metadata_and_no_source() -> None:
    text = card_text(_details())
    assert "Interstellar" in text and "میان‌ستاره‌ای" in text and "2014" in text
    assert "8.6" in text and "درام" in text
    assert "zarfilm" not in text.lower() and "زرفیلم" not in text


def test_root_keyboard_dub_movie() -> None:
    kb = root_keyboard(_details(dub=True), "abc123")
    texts = [btn.text for row in kb.inline for btn in row]
    styles = [btn.style for row in kb.inline for btn in row]
    assert "دانلود با زبان اصلی" in texts and "دانلود با دوبله فارسی" in texts
    assert styles.__contains__("primary") and styles.__contains__("success")


def test_root_keyboard_no_dub_goes_straight_to_qualities() -> None:
    kb = root_keyboard(_details(dub=False), "abc123")
    flat = [btn for row in kb.inline for btn in row]
    assert flat[0].text == "1080p - 2.1GB"
    assert flat[0].callback_data == "q:abc123:orig:0"


def test_root_keyboard_series_shows_seasons() -> None:
    kb = root_keyboard(_details(series=True), "abc123")
    flat = [btn for row in kb.inline for btn in row]
    assert flat[0].text == "فصل اول" and flat[0].callback_data == "s:abc123:0"


def test_quality_keyboard_has_cancel() -> None:
    kb = quality_keyboard(_details().originals, "abc123", "orig")
    flat = [btn for row in kb.inline for btn in row]
    assert flat[0].text == "1080p - 2.1GB" and flat[0].style == "primary"
    cancel = flat[-1]
    assert cancel.text == "انصراف" and cancel.style == "danger" and cancel.callback_data == "x:abc123"


def test_file_keyboard_url_buttons() -> None:
    kb = file_keyboard(_details().originals, "abc123")
    flat = [btn for row in kb.inline for btn in row]
    assert flat[0].url == "https://dl.example.com/f.mkv"
    assert "2.1GB" in flat[0].text and "dl.example.com" in flat[0].text
    assert flat[-1].text == "انصراف"


def test_all_callback_data_within_telegram_limit() -> None:
    for kb in (root_keyboard(_details(dub=True), "abc123"), root_keyboard(_details(series=True), "abc123"),
               quality_keyboard(_details().originals, "abc123", "orig"), file_keyboard(_details().originals, "abc123")):
        for row in kb.inline:
            for btn in row:
                if btn.callback_data:
                    assert len(btn.callback_data.encode()) <= 64


def test_episode_list_text() -> None:
    pack = _details(series=True).seasons[0].qualities[0]
    text = episode_list_text(pack)
    assert '<a href="https://dl.example.com/e01.mkv">S01E01</a>' in text and "300MB" in text


def test_search_keyboard() -> None:
    entry = CardEntry(summary=_details().summary)
    kb = search_keyboard([("aaaaaa", entry)])
    btn = kb.inline[0][0]
    assert btn.callback_data == "m:aaaaaa" and btn.style == "primary"


def test_apply_icon_fallback_and_custom() -> None:
    from aiogram.types import InlineKeyboardButton

    custom = apply_icon("دانلود", "dub", {"dub": "5368385512908012910"})
    assert isinstance(custom, InlineKeyboardButton) and custom.icon_custom_emoji_id == "5368385512908012910"
    fallback = apply_icon("دانلود", "dub", {})
    assert fallback.icon_custom_emoji_id is None and fallback.text.startswith("🟢")
```

- [ ] **Step 2: Run, expect failure**

Run: `python -m pytest tests/test_formatting.py -v`
Expected: FAIL — `No module named 'src.services.formatting'`.

- [ ] **Step 3: Implement**

```python
# src/services/formatting.py
from html import escape
from typing import Any

from aiogram.enums.button_style import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.models import DownloadLink, MovieDetails, QualityPack
from src.repos.state import CardEntry

PLOT_LIMIT = 300

FALLBACK_ICONS: dict[str, str] = {
    "original": "🔵",
    "dub": "🟢",
    "season": "📂",
    "quality": "⬇️",
    "result": "🎬",
}


def card_text(details: MovieDetails) -> str:
    summary = details.summary
    title = escape(summary.title_en)
    if summary.title_fa:
        title += f" — {escape(summary.title_fa)}"
    head = f"🎬 {title} ({summary.year})" if summary.year else f"🎬 {title}"
    meta_parts: list[str] = []
    if details.imdb:
        meta_parts.append(f"⭐ {escape(details.imdb)}")
    if summary.genres:
        meta_parts.append("🎭 " + escape("، ".join(summary.genres[:3])))
    if details.runtime:
        meta_parts.append(f"⏱ {escape(details.runtime)}")
    lines = [head]
    if meta_parts:
        lines.append(" · ".join(meta_parts))
    if details.plot:
        plot = escape(details.plot[:PLOT_LIMIT].rsplit(" ", 1)[0]) + "…"
        lines.append(f"📄 {plot}")
    return "\n".join(lines)


def search_keyboard(results: list[tuple[str, CardEntry]]) -> InlineKeyboardMarkup:
    rows = [[_result_button(key, entry)] for key, entry in results]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _result_button(key: str, entry: CardEntry) -> InlineKeyboardButton:
    s = entry.summary
    text = s.title_en + (f" ({s.year})" if s.year else "")
    return apply_icon(text, "result", {}, callback_data=f"m:{key}", style=ButtonStyle.PRIMARY)


def root_keyboard(details: MovieDetails, key: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if details.is_series:
        for idx, season in enumerate(details.seasons):
            rows.append([apply_icon(season.label, "season", {}, callback_data=f"s:{key}:{idx}", style=ButtonStyle.PRIMARY)])
    elif details.has_dub:
        rows.append([
            apply_icon("دانلود با زبان اصلی", "original", {}, callback_data=f"l:{key}:orig", style=ButtonStyle.PRIMARY),
            apply_icon("دانلود با دوبله فارسی", "dub", {}, callback_data=f"l:{key}:dub", style=ButtonStyle.SUCCESS),
        ])
    else:
        rows = _quality_rows(details.originals, key, "orig")
    return InlineKeyboardMarkup(inline_keyboard=rows)


def quality_keyboard(links: list[DownloadLink], key: str, audio: str) -> InlineKeyboardMarkup:
    rows = _quality_rows(links, key, audio)
    rows.append([_cancel_button(key)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def season_quality_keyboard(packs: list[QualityPack], key: str) -> InlineKeyboardMarkup:
    rows = [[apply_icon(pack.quality, "quality", {}, callback_data=f"q:{key}:s:{idx}", style=ButtonStyle.PRIMARY)] for idx, pack in enumerate(packs)]
    rows.append([_cancel_button(key)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def file_keyboard(links: list[DownloadLink], key: str) -> InlineKeyboardMarkup:
    rows = [[_file_button(link)] for link in links]
    rows.append([_cancel_button(key)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _quality_rows(links: list[DownloadLink], key: str, audio: str) -> list[list[InlineKeyboardButton]]:
    row = [
        apply_icon(_quality_label(link), "quality", {}, callback_data=f"q:{key}:{audio}:{idx}", style=ButtonStyle.PRIMARY)
        for idx, link in enumerate(links)
    ]
    return [row] if row else []


def _quality_label(link: DownloadLink) -> str:
    return f"{link.quality} - {link.size}" if link.size else link.quality


def _file_button(link: DownloadLink) -> InlineKeyboardButton:
    text = "⬇ " + (link.size or "دانلود")
    if link.host:
        text += f" — {link.host}"
    return InlineKeyboardButton(text=text, url=link.url)


def _cancel_button(key: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text="انصراف", callback_data=f"x:{key}", style=ButtonStyle.DANGER)


def episode_list_text(pack: QualityPack) -> str:
    lines = [f'<a href="{escape(episode.url)}">{escape(episode.label)}</a>' + (f" — {escape(episode.size)}" if episode.size else "") for episode in pack.episodes]
    return "\n".join(lines)


def apply_icon(text: str, role: str, emoji_map: dict[str, str], **button_kwargs: Any) -> InlineKeyboardButton:
    icon = emoji_map.get(role)
    if icon:
        return InlineKeyboardButton(text=text, icon_custom_emoji_id=icon, **button_kwargs)
    return InlineKeyboardButton(text=f"{FALLBACK_ICONS.get(role, '')} {text}".strip(), **button_kwargs)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `python -m pytest tests/test_formatting.py -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add src/services/formatting.py tests/test_formatting.py
git commit -m "feat: card text and drill-down keyboards with styles, sizes, emoji fallback"
```

---

### Task 9: Middleware — allowlist and per-user search lock

**Files:**
- Create: `src/handlers/__init__.py`, `src/handlers/middleware.py`
- Test: `tests/test_middleware.py`

**Interfaces:**
- Produces: `AllowlistMiddleware(allowed: set[int])` (aiogram `BaseMiddleware` — outside the allowlist: answers «این ربات خصوصی است.» and stops the chain); `SearchLockMiddleware()` — per-user `asyncio.Lock` keyed by user id; if the user's lock is held, answers «یه جستجو در حال اجراست؛ کمی صبر کن.» and stops; both registered as outer message middlewares in Task 12.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_middleware.py
import asyncio
from unittest.mock import AsyncMock

import pytest
from aiogram.types import Message, User

from src.handlers.middleware import AllowlistMiddleware, SearchLockMiddleware


def _message(user_id: int) -> Message:
    message = AsyncMock(spec=Message)
    message.from_user = User(id=user_id, is_bot=False, first_name="t")
    message.answer = AsyncMock()
    return message


def _data(user_id: int) -> dict:
    return {"event_from_user": User(id=user_id, is_bot=False, first_name="t")}


async def test_allowlisted_user_passes() -> None:
    handler = AsyncMock(return_value="ok")
    mw = AllowlistMiddleware(allowed={42})
    result = await mw(handler, _message(42), _data(42))
    assert result == "ok"
    handler.assert_awaited_once()


async def test_stranger_blocked() -> None:
    handler = AsyncMock()
    mw = AllowlistMiddleware(allowed={42})
    result = await mw(handler, _message(7), _data(7))
    assert result is None
    handler.assert_not_awaited()


async def test_second_concurrent_search_blocked() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_handler(event, data):
        started.set()
        await release.wait()
        return "done"

    mw = SearchLockMiddleware()
    first = asyncio.create_task(mw(slow_handler, _message(42), _data(42)))
    await started.wait()
    handler2 = AsyncMock()
    result = await mw(handler2, _message(42), _data(42))
    assert result is None
    handler2.assert_not_awaited()
    release.set()
    assert await first == "done"


async def test_different_users_do_not_block_each_other() -> None:
    mw = SearchLockMiddleware()
    handler = AsyncMock(return_value="ok")
    held = mw._locks.setdefault(1, asyncio.Lock())
    await held.acquire()
    assert await mw(handler, _message(2), _data(2)) == "ok"
```

- [ ] **Step 2: Run, expect failure**

Run: `python -m pytest tests/test_middleware.py -v`
Expected: FAIL — `No module named 'src.handlers'`.

- [ ] **Step 3: Implement**

```python
# src/handlers/__init__.py
```

```python
# src/handlers/middleware.py
import asyncio
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

PRIVATE_ONLY_TEXT = "این ربات خصوصی است."
BUSY_TEXT = "یه جستجو در حال اجراست؛ کمی صبر کن."


class AllowlistMiddleware(BaseMiddleware):
    def __init__(self, allowed: set[int]) -> None:
        self._allowed = allowed

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or user.id not in self._allowed:
            if isinstance(event, Message):
                await event.answer(PRIVATE_ONLY_TEXT)
            return None
        return await handler(event, data)


class SearchLockMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)
        lock = self._locks.setdefault(user.id, asyncio.Lock())
        if lock.locked():
            if isinstance(event, Message):
                await event.answer(BUSY_TEXT)
            return None
        async with lock:
            return await handler(event, data)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `python -m pytest tests/test_middleware.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/handlers tests/test_middleware.py
git commit -m "feat: allowlist and per-user search lock middleware"
```

---

### Task 10: Handlers — start/help, errors, search, card open

**Files:**
- Create: `src/handlers/common.py`, `src/handlers/search.py`, `src/handlers/card.py`
- Test: `tests/test_handlers_search.py`

**Interfaces:**
- Consumes: `ZarfilmClient.search/movie`, `TTLCache`, `CallbackState`/`CardEntry`, formatting functions.
- Produces: routers `common.router`, `search.router`, `card.router` (registered in Task 12).
  - `common.py`: `/start` → «نام فیلم یا سریال رو بفرست…»; `/help` → same guidance; errors observer on the router: `ZarfilmError` → «دسترسی به منبع در دسترس نیست؛ بعداً تلاش کن.» logged at warning; unexpected → logged with traceback, user sees the same text. All texts source-neutral.
  - `search.py`: non-command text → cache get (`search:{query}`) → miss: `zarfilm.search()` → `cache.set(search_ttl)` → create one `CardEntry` per result (max 5) in `CallbackState` → `search_keyboard` reply. No results → «چیزی پیدا نشد؛ با املای دیگری امتحان کن.»
  - `card.py`: callback `m:{key}` → entry lookup (expired → «جستجو منقضی شده؛ دوباره جستجو کن.» + `cb.answer()`) → details from slug cache (`page:{slug}`) or `zarfilm.movie(slug)` → cached `page_ttl` → `entry.details = details` → `cb.message.edit_text(card_text, reply_markup=root_keyboard, parse_mode="HTML")` → `cb.answer()`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_handlers_search.py
from unittest.mock import AsyncMock

import pytest
from aiogram.types import Message, User

from src.models import MovieSummary
from src.repos.cache import TTLCache
from src.repos.state import CallbackState
from src.handlers import search


def _results() -> list[MovieSummary]:
    return [MovieSummary(slug="interstellar-2014", title_en="Interstellar", year=2014)]


def _message(text: str, user_id: int = 42) -> Message:
    message = AsyncMock(spec=Message)
    message.text = text
    message.from_user = User(id=user_id, is_bot=False, first_name="t")
    message.answer = AsyncMock()
    return message


@pytest.fixture
def deps():
    from src.models.config import Config

    return {
        "cache": TTLCache(),
        "card_state": CallbackState(ttl=60),
        "zarfilm": AsyncMock(),
        "cfg": Config(bot_token="1:abc", zarfilm_username="u", zarfilm_password="p"),
    }


async def test_search_replies_with_result_buttons(deps) -> None:
    deps["zarfilm"].search = AsyncMock(return_value=_results())
    message = _message("interstellar")
    await search.handle_search(message, **deps)
    message.answer.assert_awaited_once()
    kwargs = message.answer.await_args.kwargs
    kb = kwargs["reply_markup"]
    assert kb.inline[0][0].callback_data.startswith("m:")


async def test_search_no_results_message(deps) -> None:
    deps["zarfilm"].search = AsyncMock(return_value=[])
    message = _message("qqqqqq")
    await search.handle_search(message, **deps)
    text = message.answer.await_args.args[0]
    assert "پیدا نشد" in text


async def test_search_uses_cache_before_site(deps) -> None:
    await deps["cache"].set("search:interstellar", _results(), ttl=60)
    deps["zarfilm"].search = AsyncMock()
    message = _message("interstellar")
    await search.handle_search(message, **deps)
    deps["zarfilm"].search.assert_not_awaited()
```

> **Note on dependency naming:** aiogram's `Dispatcher.workflow_data` injects extra kwargs into handlers by key. The key `state` is reserved (aiogram injects `FSMContext` there), so the callback-state store is wired as `card_state` in handlers and in `build_dispatcher` (Task 12).

- [ ] **Step 2: Run, expect failure**

Run: `python -m pytest tests/test_handlers_search.py -v`
Expected: FAIL — `cannot import name 'search'`.

- [ ] **Step 3: Implement**

```python
# src/handlers/common.py
import logging

from aiogram import Router
from aiogram.types import CallbackQuery, Message

from src.exceptions import ZarfilmError

router = Router(name="common")

START_TEXT = "نام فیلم یا سریال رو بفرست تا لینک‌های دانلودش رو پیدا کنم."
UNAVAILABLE_TEXT = "دسترسی به منبع در دسترس نیست؛ بعداً تلاش کن."


@router.message(F.text.startswith("/start"))
async def start(message: Message) -> None:
    await message.answer(START_TEXT)


@router.message(F.text.startswith("/help"))
async def help_(message: Message) -> None:
    await message.answer(START_TEXT)


@router.errors()
async def on_error(event, exception: Exception | None = None) -> bool:
    failure = exception or getattr(event, "exception", None)
    if isinstance(failure, ZarfilmError):
        logging.warning("source failure: %s", failure)
    else:
        logging.exception("unhandled bot error: %s", failure)
    update = getattr(event, "update", event)
    target = update.message or update.callback_query
    if isinstance(target, Message):
        await target.answer(UNAVAILABLE_TEXT)
    elif isinstance(target, CallbackQuery):
        await target.answer(UNAVAILABLE_TEXT, show_alert=True)
    return True
```

(Add `F` back to the aiogram import in this module — `from aiogram import F, Router` — the `/start` and `/help` filters use it. The errors observer is registered unfiltered so it catches every exception shape, and reads `exception` either from the kwarg or from aiogram's `ErrorEvent` wrapper, whichever the installed version provides.)

```python
# src/handlers/search.py
from aiogram import F, Router
from aiogram.types import Message

from src.models.config import Config
from src.repos.cache import TTLCache
from src.repos.state import CallbackState, CardEntry
from src.services.formatting import search_keyboard
from src.services.zarfilm import ZarfilmClient

router = Router(name="search")

NO_RESULTS_TEXT = "چیزی پیدا نشد؛ با املای دیگری امتحان کن."
MAX_RESULTS = 5


@router.message(F.text & ~F.text.startswith("/"))
async def handle_search(
    message: Message,
    zarfilm: ZarfilmClient,
    cache: TTLCache,
    card_state: CallbackState,
    cfg: Config,
) -> None:
    query = (message.text or "").strip()
    cache_key = f"search:{query.lower()}"
    results = await cache.get(cache_key)
    if results is None:
        results = await zarfilm.search(query)
        await cache.set(cache_key, results, cfg.search_ttl)
    if not results:
        await message.answer(NO_RESULTS_TEXT)
        return
    pairs: list[tuple[str, CardEntry]] = []
    for summary in results[:MAX_RESULTS]:
        entry = CardEntry(summary=summary)
        key = card_state.create(entry)
        pairs.append((key, entry))
    await message.answer("نتایج جستجو:", reply_markup=search_keyboard(pairs))
```

```python
# src/handlers/card.py
from aiogram import F, Router
from aiogram.types import CallbackQuery

from src.repos.cache import TTLCache
from src.repos.state import CallbackState
from src.services.formatting import card_text, root_keyboard
from src.services.zarfilm import ZarfilmClient

router = Router(name="card")

EXPIRED_TEXT = "جستجو منقضی شده؛ دوباره جستجو کن."


@router.callback_query(F.data.startswith("m:"))
async def open_card(
    callback: CallbackQuery,
    zarfilm: ZarfilmClient,
    cache: TTLCache,
    card_state: CallbackState,
    cfg,
) -> None:
    key = callback.data.split(":", 1)[1]
    entry = card_state.get(key)
    if entry is None:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    details = await cache.get(f"page:{entry.summary.slug}")
    if details is None:
        details = await zarfilm.movie(entry.summary.slug)
        await cache.set(f"page:{entry.summary.slug}", details, cfg.page_ttl)
    entry.details = details
    await callback.message.edit_text(
        card_text(details),
        reply_markup=root_keyboard(details, key),
        parse_mode="HTML",
    )
    await callback.answer()
```

- [ ] **Step 4: Run tests, expect pass**

Run: `python -m pytest tests/test_handlers_search.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/handlers tests/test_handlers_search.py
git commit -m "feat: start/help, error observer, search handler, and card open callback"
```

---

### Task 11: Handlers — drill-down callbacks, cancel, episode list, admin /login

**Files:**
- Modify: `src/handlers/card.py` (append callbacks), `src/handlers/card_text.py` no — keep `src/handlers/card.py`
- Create: `src/handlers/admin.py`
- Test: `tests/test_handlers_drilldown.py`

**Interfaces:**
- Consumes: formatting keyboards, `CardEntry.selection`, models.
- Produces (all in `card.router` unless noted):
  - `l:{key}:{audio}` → `quality_keyboard(links_for(entry, audio), key, audio)`; stores `entry.selection = audio`.
  - `s:{key}:{idx}` → quality buttons over the season's `QualityPack`s, labeled by quality and size of the pack's first episode when known; stores `entry.selection = f"s:{idx}"`.
  - `q:{key}:{audio}:{idx}` — movie audio (`orig`/`dub`): edit to `file_keyboard([link], key)`; series season (`audio == "s"`): send `episode_list_text(pack)` as a new HTML message and revert the card keyboard to `root_keyboard(details, key)`; clear `entry.selection`.
  - `x:{key}` → revert to `root_keyboard(details, key)`, clear `entry.selection`.
  - Helpers in `src/services/parsers.py` (pure, testable): `parse_cookie_header(raw: str) -> dict[str, str]` and `filter_session_cookies(cookies: dict[str, str]) -> dict[str, str]` (keeps `wordpress_logged_in*` keys).
  - `admin.py`: `/login` — owner only (`cfg.allowed_user_ids[0]`); FSM state `waiting_cookie`; next message text parsed via the helpers above → written into `cfg.session_path` JSON + loaded into `zarfilm._client.cookies` → confirm «نشست به‌روزرسانی شد.»; the cookie message is deleted immediately after reading.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_handlers_drilldown.py
from unittest.mock import AsyncMock

import pytest
from aiogram.types import CallbackQuery, Message, User

from src.handlers import admin  # noqa: F401  (import exercised via card tests' shared deps)
from src.models import (
    DownloadLink,
    EpisodeLink,
    MediaKind,
    MovieDetails,
    MovieSummary,
    QualityPack,
    Season,
)
from src.repos.state import CallbackState, CardEntry
from src.handlers import card


def _movie_details(dub: bool = True) -> MovieDetails:
    link = DownloadLink(quality="1080p", url="https://dl.example.com/f.mkv", size="2.1GB", host="dl.example.com")
    return MovieDetails(
        summary=MovieSummary(slug="f-2014", title_en="F", kind=MediaKind.MOVIE),
        dubs=[link] if dub else [],
        originals=[link],
    )


def _series_details() -> MovieDetails:
    return MovieDetails(
        summary=MovieSummary(slug="s-2020", title_en="S", kind=MediaKind.SERIES),
        seasons=[Season(label="فصل اول", qualities=[QualityPack(quality="1080p", episodes=[EpisodeLink(label="S01E01", url="https://dl.example.com/e01.mkv", size="300MB")])])],
    )


def _cb(data: str, message: AsyncMock) -> CallbackQuery:
    cb = AsyncMock(spec=CallbackQuery)
    cb.data = data
    cb.message = message
    cb.answer = AsyncMock()
    cb.from_user = User(id=42, is_bot=False, first_name="t")
    return cb


def _message(text: str, user_id: int = 42) -> Message:
    message = AsyncMock(spec=Message)
    message.text = text
    message.from_user = User(id=user_id, is_bot=False, first_name="t")
    message.answer = AsyncMock()
    message.delete = AsyncMock()
    return message


@pytest.fixture
def deps():
    from src.models.config import Config

    return {
        "cache": AsyncMock(),
        "card_state": CallbackState(ttl=60),
        "zarfilm": AsyncMock(),
        "cfg": Config(bot_token="1:abc", zarfilm_username="u", zarfilm_password="p"),
    }


async def test_language_choice_shows_qualities(deps) -> None:
    entry = CardEntry(summary=_movie_details().summary, details=_movie_details())
    key = deps["card_state"].create(entry)
    message = AsyncMock()
    message.edit_reply_markup = AsyncMock()
    await card.choose_language(_cb(f"l:{key}:dub", message), **deps)
    message.edit_reply_markup.assert_awaited_once()
    kb = message.edit_reply_markup.await_args.kwargs["reply_markup"]
    assert kb.inline[0][0].text == "1080p - 2.1GB"
    assert kb.inline[0][0].callback_data == f"q:{key}:dub:0"
    assert entry.selection == "dub"


async def test_quality_choice_movie_edits_to_file_buttons(deps) -> None:
    entry = CardEntry(summary=_movie_details().summary, details=_movie_details(), selection="dub")
    key = deps["card_state"].create(entry)
    message = AsyncMock()
    message.edit_reply_markup = AsyncMock()
    await card.choose_quality(_cb(f"q:{key}:dub:0", message), **deps)
    kb = message.edit_reply_markup.await_args.kwargs["reply_markup"]
    assert kb.inline[0][0].url == "https://dl.example.com/f.mkv"


async def test_quality_choice_series_sends_episode_list_and_reverts(deps) -> None:
    entry = CardEntry(summary=_series_details().summary, details=_series_details(), selection="s:0")
    key = deps["card_state"].create(entry)
    message = AsyncMock()
    message.edit_reply_markup = AsyncMock()
    await card.choose_quality(_cb(f"q:{key}:s:0", message), **deps)
    message.answer.assert_awaited_once()
    assert "S01E01" in message.answer.await_args.args[0]
    message.edit_reply_markup.assert_awaited_once()
    assert entry.selection == ""


async def test_cancel_returns_to_root(deps) -> None:
    entry = CardEntry(summary=_movie_details().summary, details=_movie_details(), selection="dub")
    key = deps["card_state"].create(entry)
    message = AsyncMock()
    message.edit_reply_markup = AsyncMock()
    await card.cancel(_cb(f"x:{key}", message), **deps)
    message.edit_reply_markup.assert_awaited_once()
    assert entry.selection == ""


async def test_expired_key_alerts(deps) -> None:
    message = AsyncMock()
    cb = _cb("x:ffff00", message)
    await card.cancel(cb, **deps)
    cb.answer.assert_awaited_once()
    assert "منقضی" in cb.answer.await_args.args[0]


async def test_season_quality_button_labels_use_pack_quality(deps) -> None:
    entry = CardEntry(summary=_series_details().summary, details=_series_details())
    key = deps["card_state"].create(entry)
    message = AsyncMock()
    message.edit_reply_markup = AsyncMock()
    await card.choose_season(_cb(f"s:{key}:0", message), **deps)
    kb = message.edit_reply_markup.await_args.kwargs["reply_markup"]
    assert kb.inline[0][0].text == "1080p"
    assert kb.inline[0][0].callback_data == f"q:{key}:s:0"


def test_parse_cookie_header_extracts_pairs() -> None:
    from src.services.parsers import parse_cookie_header

    cookies = parse_cookie_header("wordpress_logged_in_abc=user%7C1; theme=dark")
    assert cookies == {"wordpress_logged_in_abc": "user%7C1", "theme": "dark"}


def test_filter_session_cookies() -> None:
    from src.services.parsers import filter_session_cookies

    kept = filter_session_cookies({"wordpress_logged_in_abc": "u", "theme": "dark"})
    assert kept == {"wordpress_logged_in_abc": "u"}


async def test_start_login_owner_only(deps) -> None:
    from src.handlers import admin

    cfg = deps["cfg"]
    cfg.allowed_user_ids = [42]
    owner = _message("/login", user_id=42)
    fsm = AsyncMock()
    await admin.start_login(owner, fsm, cfg)
    owner.answer.assert_awaited_once()
    fsm.set_state.assert_awaited_once()

    stranger = _message("/login", user_id=7)
    await admin.start_login(stranger, AsyncMock(), cfg)
    stranger.answer.assert_not_awaited()


async def test_receive_cookie_updates_session_and_deletes_message(deps, tmp_path) -> None:
    from src.handlers import admin

    cfg = deps["cfg"]
    cfg.allowed_user_ids = [42]
    cfg.session_path = tmp_path / "session.json"

    message = _message("wordpress_logged_in_abc=user%7C1; theme=dark", user_id=42)
    fsm = AsyncMock()
    await admin.receive_cookie(message, fsm, cfg, deps["zarfilm"])
    message.delete.assert_awaited_once()
    assert "wordpress_logged_in_abc" in cfg.session_path.read_text(encoding="utf-8")
    message.answer.assert_awaited_once()
    fsm.clear.assert_awaited_once()
```

- [ ] **Step 2: Run, expect failure**

Run: `python -m pytest tests/test_handlers_drilldown.py -v`
Expected: FAIL — `card` has no attribute `choose_language`.

- [ ] **Step 3: Implement drill-down and admin**

Append to `src/handlers/card.py`:

```python
from aiogram import F
from aiogram.types import CallbackQuery, Message

from src.models import QualityPack
from src.repos.state import CallbackState
from src.services.formatting import episode_list_text, file_keyboard, quality_keyboard, root_keyboard, season_quality_keyboard

AUDIO_LINKS = {"orig": "originals", "dub": "dubs"}


@router.callback_query(F.data.startswith("l:"))
async def choose_language(callback: CallbackQuery, card_state: CallbackState, **_: object) -> None:
    _, key, audio = callback.data.split(":")
    entry = card_state.get(key)
    if entry is None or entry.details is None:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    entry.selection = audio
    links = getattr(entry.details, AUDIO_LINKS[audio])
    await callback.message.edit_reply_markup(reply_markup=quality_keyboard(links, key, audio))
    await callback.answer()


@router.callback_query(F.data.startswith("s:"))
async def choose_season(callback: CallbackQuery, card_state: CallbackState, **_: object) -> None:
    _, key, idx_text = callback.data.split(":")
    entry = card_state.get(key)
    if entry is None or entry.details is None:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    entry.selection = f"s:{idx_text}"
    season = entry.details.seasons[int(idx_text)]
    await callback.message.edit_reply_markup(reply_markup=season_quality_keyboard(season.qualities, key))
    await callback.answer()


@router.callback_query(F.data.startswith("q:"))
async def choose_quality(callback: CallbackQuery, card_state: CallbackState, **_: object) -> None:
    _, key, audio, idx_text = callback.data.split(":")
    entry = card_state.get(key)
    if entry is None or entry.details is None:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    idx = int(idx_text)
    if audio == "s":
        season_index = int(entry.selection.split(":")[1]) if entry.selection.startswith("s:") else 0
        pack = entry.details.seasons[season_index].qualities[idx]
        await callback.message.answer(episode_list_text(pack), parse_mode="HTML")
        await callback.message.edit_reply_markup(reply_markup=root_keyboard(entry.details, key))
        entry.selection = ""
        await callback.answer()
        return
    links = getattr(entry.details, AUDIO_LINKS[audio])
    await callback.message.edit_reply_markup(reply_markup=file_keyboard([links[idx]], key))
    await callback.answer()


@router.callback_query(F.data.startswith("x:"))
async def cancel(callback: CallbackQuery, card_state: CallbackState, **_: object) -> None:
    key = callback.data.split(":", 1)[1]
    entry = card_state.get(key)
    if entry is None or entry.details is None:
        await callback.answer(EXPIRED_TEXT, show_alert=True)
        return
    entry.selection = ""
    await callback.message.edit_reply_markup(reply_markup=root_keyboard(entry.details, key))
    await callback.answer()
```

> Handlers pull only the dependencies they declare; aiogram injects by parameter name from `workflow_data` (hence `card_state`, since `state` is reserved for FSM), and `**_: object` absorbs the rest.

```python
# src/handlers/admin.py
import json
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from src.services.parsers import filter_session_cookies, parse_cookie_header
from src.services.zarfilm import ZarfilmClient

router = Router(name="admin")


class LoginStates(StatesGroup):
    waiting_cookie = State()


@router.message(F.text.startswith("/login"))
async def start_login(message: Message, state: FSMContext, cfg) -> None:
    if not cfg.allowed_user_ids or message.from_user.id != cfg.allowed_user_ids[0]:
        return
    await state.set_state(LoginStates.waiting_cookie)
    await message.answer("مقدار کوکی مرورگر رو بفرست (name=value; ...).")


@router.message(LoginStates.waiting_cookie, F.text)
async def receive_cookie(message: Message, state: FSMContext, cfg, zarfilm: ZarfilmClient) -> None:
    raw = message.text
    await message.delete()
    cookies = parse_cookie_header(raw)
    session_cookies = filter_session_cookies(cookies)
    if not session_cookies:
        await message.answer("کوکی نشست توش نبود؛ دوباره تلاش کن.")
        return
    for name, value in cookies.items():
        zarfilm._client.cookies.set(name, value)
    cfg.session_path.write_text(json.dumps(dict(zarfilm._client.cookies)), encoding="utf-8")
    await state.clear()
    logging.info("session cookie refreshed via /login")
    await message.answer("نشست به‌روزرسانی شد.")
```

Add to `src/services/parsers.py` (pure helpers, no I/O):

```python
def parse_cookie_header(raw: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for part in raw.split(";"):
        if "=" in part:
            name, value = part.strip().split("=", 1)
            cookies[name] = value
    return cookies


def filter_session_cookies(cookies: dict[str, str]) -> dict[str, str]:
    return {name: value for name, value in cookies.items() if name.startswith("wordpress_logged_in")}
```

- [ ] **Step 4: Run the full suite, expect pass**

Run: `python -m pytest -v`
Expected: PASS (all prior tests green too).
    await admin.receive_cookie(message, fsm, cfg, deps["zarfilm"])
    message.delete.assert_awaited_once()
    assert "wordpress_logged_in_abc" in cfg.session_path.read_text(encoding="utf-8")
    message.answer.assert_awaited_once()
    fsm.clear.assert_awaited_once()
```

- [ ] **Step 5: Commit**

```bash
git add src/handlers tests/test_handlers_drilldown.py
git commit -m "feat: drill-down callbacks, cancel, episode list, and admin /login"
```

---

### Task 12: Wiring — main.py, logging, Dockerfile, README

**Files:**
- Create: `src/main.py`, `Dockerfile`, `README.md`
- Modify: none

**Interfaces:**
- Consumes: everything above.
- Produces: runnable bot via `python -m src.main`; container image.

- [ ] **Step 1: Implement main.py**

```python
# src/main.py
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from src.handlers import admin, card, common, search
from src.handlers.middleware import AllowlistMiddleware, SearchLockMiddleware
from src.models.config import Config
from src.repos.cache import TTLCache
from src.repos.state import CallbackState
from src.services.zarfilm import ZarfilmClient


def build_dispatcher(config: Config) -> tuple[Dispatcher, ZarfilmClient]:
    dp = Dispatcher(storage=MemoryStorage())
    zarfilm = ZarfilmClient(config)
    cache = TTLCache()
    state = CallbackState(ttl=config.state_ttl)

    allowed = set(config.allowed_user_ids)
    dp.message.middleware(AllowlistMiddleware(allowed))
    dp.message.middleware(SearchLockMiddleware())
    dp.callback_query.middleware(AllowlistMiddleware(allowed))

    deps = {"cfg": config, "zarfilm": zarfilm, "cache": cache, "card_state": state}
    dp.include_router(common.router)
    dp.include_router(search.router)
    dp.include_router(card.router)
    dp.include_router(admin.router)
    dp.workflow_data.update(deps)
    return dp, zarfilm


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = Config()
    dp, zarfilm = build_dispatcher(config)
    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await zarfilm.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Smoke-test wiring without a real token**

Run: `python -c "from src.main import build_dispatcher; from src.models.config import Config; import os; os.environ.update(BOT_TOKEN='1:x', ZARFILM_USERNAME='u', ZARFILM_PASSWORD='p'); dp, _ = build_dispatcher(Config()); print('routers:', len(dp.sub_routers))"`
Expected: prints `routers: 4` (no import/wiring errors).

- [ ] **Step 3: Dockerfile and README**

```dockerfile
# Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
CMD ["python", "-m", "src.main"]
```

```markdown
# README.md (summary content)
- Movie download bot: search by Persian/English title, get direct download links via inline buttons.
- Setup: `pip install -e ".[dev]"`; copy `.env.example` to `.env` and fill values; run `python -m src.main`.
- Tests: `python -m pytest`.
- If the site session expires: send `/login` from the owner account and paste the browser cookie header.
```

- [ ] **Step 4: Run the entire suite one last time**

Run: `python -m pytest -v`
Expected: PASS (all tasks).

- [ ] **Step 5: Commit**

```bash
git add src/main.py Dockerfile README.md
git commit -m "feat: wire dispatcher, polling entrypoint, Dockerfile, and README"
```

---

## Final verification (after Task 12)

1. `python -m pytest -v` — full suite green.
2. Live acceptance with the owner: fill `.env` with real values, run `python -m src.main`, then in Telegram: `/start` → send a movie name → open card → language → quality → file URL button; repeat for a no-dub movie and a series (season → quality → episode list); confirm `انصراف` behaves; confirm no user-visible text mentions the source site.
3. Owner supplies emoji IDs → add them to `EMOJI` in `.env` → restart → verify custom icons render on buttons (fallback still works with `EMOJI` unset).
