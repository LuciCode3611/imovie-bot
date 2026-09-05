from pydantic import BaseModel, Field

from src.models.movie import MediaKind


class SubtitleFile(BaseModel):
    """One downloadable Persian subtitle archive.

    ``url`` is a public ``dl.subdl.com`` zip link: it is handed to users as an
    inline button, so it never carries credentials (see subdl_parsers).
    """

    label: str  # episode span and/or release name, e.g. «همه قسمت‌ها · Dune.2024.1080p.WEB»
    url: str
    language: str = "فارسی"
    season: int | None = None
    episode: int | None = None
    episode_from: int | None = None
    episode_end: int | None = None
    full_season: bool = False
    author: str | None = None


class SubtitlePack(BaseModel):
    """A group of subtitle files under one heading — a season for series, or
    the single «فیلم» pack for movies."""

    label: str  # e.g. "فصل 1" / "فیلم"
    files: list[SubtitleFile] = Field(default_factory=list)

    @property
    def file_count(self) -> int:
        return len(self.files)


class SubtitleSummary(BaseModel):
    """One title matched by a SubDL search (an entry of the ``results`` array)."""

    title_en: str
    kind: MediaKind = MediaKind.MOVIE
    year: int | None = None
    sd_id: str | None = None
    imdb_id: str | None = None
    tmdb_id: int | None = None

    @property
    def key(self) -> str:
        """Stable id for caching this title's subtitle list (ids beat the name)."""
        return str(self.sd_id or self.imdb_id or self.tmdb_id or self.title_en).casefold()


class SubtitleDetails(BaseModel):
    """The Persian subtitle files SubDL holds for one title."""

    summary: SubtitleSummary
    packs: list[SubtitlePack] = Field(default_factory=list)

    @property
    def is_series(self) -> bool:
        return self.summary.kind is MediaKind.SERIES

    @property
    def file_count(self) -> int:
        return sum(pack.file_count for pack in self.packs)

    @property
    def files(self) -> list[SubtitleFile]:
        """Every file in keyboard order — a button's callback data is an index
        into this list, so both sides must agree on the order."""
        return [file for pack in self.packs for file in pack.files]

    @property
    def season_labels(self) -> list[str]:
        """Season headings for a series card (empty for a movie)."""
        return [pack.label for pack in self.packs] if self.is_series else []

    @property
    def seasons(self) -> list[int]:
        """Distinct season numbers the files cover, ascending."""
        return sorted({file.season for pack in self.packs for file in pack.files if file.season is not None})
