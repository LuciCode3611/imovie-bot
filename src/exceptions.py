class ZarfilmError(Exception): ...
class AuthError(ZarfilmError): ...
class SessionExpiredError(AuthError): ...
class NotFoundError(ZarfilmError): ...
class ParseError(ZarfilmError): ...


class SubdlError(Exception):
    """SubDL API failure (missing/invalid key, quota, bad answer).

    Deliberately outside the ZarfilmError tree: subtitles have their own source
    and their own credentials, so a SubDL outage must never look like an expired
    zarfilm session. Messages never carry the API key or the request URL.
    """


class ArchiveTooLargeError(SubdlError):
    """A subtitle archive too big to upload through the Bot API (50 MB cap).

    Raised while streaming, before the whole file is in memory; callers answer
    with the public link instead.
    """
