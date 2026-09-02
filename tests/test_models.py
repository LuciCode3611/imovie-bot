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
