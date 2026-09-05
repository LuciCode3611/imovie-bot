from pydantic import BaseModel, Field

from src.models.movie import MediaKind


class SubtitleFile(BaseModel):
    """One downloadable subtitle archive (free Persian zip on dl1.subkade.ir)."""

    label: str  # e.g. "زیرنویس فارسی همه قسمت‌ها" / "زیرنویس فارسی فیلم"
    url: str
    language: str = "فارسی"


class SubtitlePack(BaseModel):
    """A group of subtitle files under one heading — a season for series, or
    the single «فیلم» pack for movies."""

    label: str  # e.g. "فصل 1" / "فیلم"
    files: list[SubtitleFile] = Field(default_factory=list)

    @property
    def file_count(self) -> int:
        return len(self.files)


class SubtitleSummary(BaseModel):
    slug: str
    title_en: str
    year: int | None = None
    poster_url: str | None = None
    kind: MediaKind = MediaKind.MOVIE
    page_url: str | None = None  # canonical post URL (the source site, for the «🌐» button)


class SubtitleDetails(BaseModel):
    summary: SubtitleSummary
    title_fa: str | None = None
    imdb: str | None = None
    plot: str | None = None
    genres: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    cast: list[str] = Field(default_factory=list)
    translators: str | None = None
    sync_note: str | None = None  # e.g. "هماهنگ با نسخه BluRay"
    airing: bool = False  # the «در حال پخش» ribbon on series
    packs: list[SubtitlePack] = Field(default_factory=list)

    @property
    def is_series(self) -> bool:
        return self.summary.kind is MediaKind.SERIES

    @property
    def file_count(self) -> int:
        return sum(pack.file_count for pack in self.packs)
