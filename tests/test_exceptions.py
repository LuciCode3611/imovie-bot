import pytest

from src.exceptions import AuthError, NotFoundError, ParseError, SessionExpiredError, SubdlError, ZarfilmError


@pytest.mark.parametrize("exc", [AuthError, SessionExpiredError, NotFoundError, ParseError])
def test_domain_exceptions_share_base(exc: type[Exception]) -> None:
    err = exc("boom")
    assert isinstance(err, ZarfilmError)


def test_session_expired_is_an_auth_error() -> None:
    assert issubclass(SessionExpiredError, AuthError)

def test_subtitle_failures_stay_out_of_the_zarfilm_tree() -> None:
    """A dead subtitle API must never read like an expired zarfilm session."""
    assert not issubclass(SubdlError, ZarfilmError)
    assert not isinstance(SubdlError("boom"), AuthError)
