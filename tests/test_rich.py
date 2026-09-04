from src.models import (
    DownloadLink,
    EpisodeLink,
    MediaKind,
    MovieDetails,
    MovieSummary,
    QualityPack,
    Season,
)
from src.services.rich import rich_card_message, rich_episode_message


def _movie() -> MovieDetails:
    return MovieDetails(
        summary=MovieSummary(
            slug="dune-2024",
            title_en="Dune: Part Two",
            title_fa="تل‌ماسه: بخش دوم",
            year=2024,
            poster_url="https://img.example.com/dune.jpg",
            genres=["علمی تخیلی", "ماجراجویی"],
            kind=MediaKind.MOVIE,
        ),
        imdb="8.3/10",
        plot="پاول آترایدس به آراکیس بازمی‌گردد.",
        countries=["آمریکا"],
        originals=[DownloadLink(quality="1080p", url="https://dl.example.com/f.mkv")],
    )


def _series() -> MovieDetails:
    return MovieDetails(
        summary=MovieSummary(slug="s", title_en="Show", title_fa="سریال", kind=MediaKind.SERIES),
        countries=["آمریکا"],
        imdb="8/10",
        plot="داستان سریال.",
        seasons=[
            Season(
                label="فصل 1",
                qualities=[
                    QualityPack(
                        quality="1080p",
                        episodes=[
                            EpisodeLink(label="S01E01", url="https://dl.example.com/e1.mkv", size="450MB"),
                            EpisodeLink(label="S01E02", url="https://dl.example.com/e2.mkv", size="450MB"),
                        ],
                    )
                ],
            )
        ],
    )


def _blocks(rich):
    return rich.model_dump(exclude_none=True)["blocks"]


def test_rich_card_is_rtl_and_contains_poster_table_pullquote() -> None:
    rich = rich_card_message(_movie())
    assert rich.is_rtl is True
    types = [b["type"] for b in _blocks(rich)]
    assert types[0] == "photo"
    assert "table" in types and "pullquote" in types


def test_rich_card_table_is_borderless_centered_with_metadata() -> None:
    rich = rich_card_message(_movie())
    table = next(b for b in _blocks(rich) if b["type"] == "table")
    assert table["is_bordered"] is False and table["is_compact"] is True
    # every cell is center-aligned
    assert all(cell["align"] == "center" for row in table["cells"] for cell in row)
    flat = [str(cell["text"]) for row in table["cells"] for cell in row]
    assert "Dune: Part Two" in flat and "تل‌ماسه: بخش دوم" in flat
    assert "محصول" in flat and "آمریکا" in flat
    assert "ژانر" in flat and "8.3/10" in flat and "2024" in flat
    # header row marks the two titles
    assert table["cells"][0][0]["is_header"] is True


def test_rich_card_series_has_seasons_row() -> None:
    rich = rich_card_message(_series())
    table = next(b for b in _blocks(rich) if b["type"] == "table")
    flat = [str(cell["text"]) for row in table["cells"] for cell in row]
    assert "فصل‌ها" in flat and "1 فصل" in flat


def test_rich_episode_table_links_episodes() -> None:
    details = _series()
    pack = details.seasons[0].qualities[0]
    rich = rich_episode_message(pack, details.seasons[0])
    table = next(b for b in _blocks(rich) if b["type"] == "table")
    # header + 2 episodes
    assert len(table["cells"]) == 3
    # download cell of the first episode is a URL rich text pointing at the link
    link_cell = table["cells"][1][2]["text"]
    assert isinstance(link_cell, dict) and link_cell["url"] == "https://dl.example.com/e1.mkv"
