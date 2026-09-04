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
        cast=["Timothée Chalamet", "Zendaya"],
        runtime="166 دقیقه",
        originals=[DownloadLink(quality="1080p", url="https://dl.example.com/f.mkv")],
    )


def _series() -> MovieDetails:
    return MovieDetails(
        summary=MovieSummary(slug="s", title_en="Show", title_fa="سریال", kind=MediaKind.SERIES),
        countries=["آمریکا"],
        cast=["Aaron Pierre"],
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


def _as_text(value) -> str:
    if isinstance(value, str):
        return value
    parts = []
    for item in value:
        parts.append(item if isinstance(item, str) else item.get("alternative_text", ""))
    return "".join(parts)


def test_rich_card_is_rtl_and_contains_poster_table_pullquote() -> None:
    rich = rich_card_message(_movie())
    assert rich.is_rtl is True
    types = [b["type"] for b in _blocks(rich)]
    assert types[0] == "photo"
    assert "table" in types and "pullquote" in types
    # the heading (فیلم/سریال text) was removed
    assert "heading" not in types


def test_rich_card_table_is_borderless_centered_with_metadata() -> None:
    rich = rich_card_message(_movie())
    table = next(b for b in _blocks(rich) if b["type"] == "table")
    assert table["is_bordered"] is False and table["is_compact"] is True
    assert all(cell["align"] == "center" for row in table["cells"] for cell in row)
    # title header row: English left (col0), Persian right (col1)
    assert table["cells"][0][0]["text"] == "Dune: Part Two"
    assert table["cells"][0][1]["text"] == "تل‌ماسه: بخش دوم"
    # metadata rows are [value, label] so the label sits on the right in RTL
    labels = [_as_text(row[1]["text"]) for row in table["cells"][1:]]
    values = [_as_text(row[0]["text"]) for row in table["cells"][1:]]
    joined_labels = " ".join(labels)
    for label in ("امتیاز", "مدت زمان", "محصول", "ژانر", "ستارگان"):
        assert label in joined_labels
    assert "8.3/10" in values and "166 دقیقه" in values
    assert "آمریکا" in values and "Timothée" in " ".join(values)
    # label cells carry the per-role custom emoji ids
    rating_label = table["cells"][1][1]["text"]
    assert isinstance(rating_label, list)
    assert any(
        isinstance(x, dict) and x.get("custom_emoji_id") == "5438496463044752972" for x in rating_label
    )


def test_rich_card_hides_missing_runtime_row() -> None:
    movie = _movie()
    movie.runtime = None
    rich = rich_card_message(movie)
    table = next(b for b in _blocks(rich) if b["type"] == "table")
    labels = " ".join(_as_text(row[1]["text"]) for row in table["cells"][1:])
    assert "مدت زمان" not in labels


def test_rich_episode_table_links_episodes() -> None:
    details = _series()
    pack = details.seasons[0].qualities[0]
    rich = rich_episode_message(pack, details.seasons[0])
    table = next(b for b in _blocks(rich) if b["type"] == "table")
    # header + 2 episodes
    assert len(table["cells"]) == 3
    # RTL: episode label on the right (col2), download link on the left (col0)
    assert table["cells"][1][2]["text"] == "S01E01"
    link_cell = table["cells"][1][0]["text"]
    assert isinstance(link_cell, dict) and link_cell["url"] == "https://dl.example.com/e1.mkv"
