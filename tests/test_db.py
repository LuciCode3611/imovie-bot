"""SQLite repository: users, blocks, requests, the subtitle file cache and overview stats."""

from pathlib import Path

from src.repos.db import Database


def _db(tmp_path: Path) -> Database:
    return Database(tmp_path / "bot.db")


def test_user_upsert_and_counts(tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.upsert_user(1, "رضا", "reza")
    db.upsert_user(2, "Sara", None)
    assert db.count_users() == 2
    # upsert refreshes the name rather than duplicating
    db.upsert_user(1, "رضا احمدی", "reza2")
    user = db.get_user(1)
    assert user is not None and user.full_name == "رضا احمدی" and user.username == "reza2"


def test_search_counter_and_active_window(tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.upsert_user(1, "a", None)
    db.increment_searches(1)
    db.increment_searches(1)
    assert db.total_searches() == 2
    assert db.count_active_since(7) == 1


def test_block_unblock(tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.upsert_user(1, "a", None)
    assert db.is_blocked(1) is False
    db.set_blocked(1, True)
    assert db.is_blocked(1) is True
    assert db.count_blocked() == 1
    db.set_blocked(1, False)
    assert db.is_blocked(1) is False


def test_requests_lifecycle(tmp_path: Path) -> None:
    db = _db(tmp_path)
    rid = db.add_request(1, "رضا", "The Last of Us")
    assert db.count_open_requests() == 1
    assert db.get_request(rid).status == "open"
    db.set_request_status(rid, "done")
    assert db.count_open_requests() == 0
    assert db.count_requests() == 1
    rid2 = db.add_request(2, "sara", "Silo")
    assert db.count_open_requests() == 1
    db.set_request_status(rid2, "rejected")
    assert db.count_requests("rejected") == 1


def test_request_pagination(tmp_path: Path) -> None:
    db = _db(tmp_path)
    for i in range(10):
        db.add_request(1, "u", f"Title {i}")
    page = db.list_requests("open", limit=6)
    assert len(page) == 6
    # newest first
    assert page[0].title == "Title 9"


def test_stats_bundle(tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.upsert_user(1, "a", None)
    db.upsert_user(2, "b", None)
    db.set_blocked(2, True)
    db.increment_searches(1)
    db.add_request(1, "a", "X")
    stats = db.stats()
    assert stats["users"] == 2
    assert stats["blocked"] == 1
    assert stats["searches"] == 1
    assert stats["requests_open"] == 1
    assert stats["requests_total"] == 1
    assert stats["subtitle_files"] == 0


def test_subtitle_file_cache_round_trip(tmp_path: Path) -> None:
    """One upload per archive: a cached file_id keeps the download quota untouched."""
    db = _db(tmp_path)
    url = "https://dl.subdl.com/subtitle/3197651-3213944.zip"
    assert db.subtitle_file_id(url) is None
    db.store_subtitle_file_id(url, "FID-1")
    assert db.subtitle_file_id(url) == "FID-1"
    assert db.count_subtitle_files() == 1
    # re-uploading the same url replaces the id instead of duplicating the row
    db.store_subtitle_file_id(url, "FID-2")
    assert db.subtitle_file_id(url) == "FID-2" and db.count_subtitle_files() == 1
    db.store_subtitle_file_id("https://dl.subdl.com/subtitle/other.zip", "FID-3")
    assert db.count_subtitle_files() == 2 and db.stats()["subtitle_files"] == 2


def test_forgetting_a_stale_subtitle_file_id(tmp_path: Path) -> None:
    db = _db(tmp_path)
    url = "https://dl.subdl.com/subtitle/1.zip"
    db.store_subtitle_file_id(url, "FID")
    db.forget_subtitle_file_id(url)
    assert db.subtitle_file_id(url) is None and db.count_subtitle_files() == 0
    db.forget_subtitle_file_id(url)  # idempotent
