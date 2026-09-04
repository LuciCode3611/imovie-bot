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
    dubbed: bool = False

    @property
    def episode_count(self) -> int:
        return len(self.episodes)


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
