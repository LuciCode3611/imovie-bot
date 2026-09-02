import pytest

from src.exceptions import AuthError, NotFoundError, ParseError, SessionExpiredError, ZarfilmError


@pytest.mark.parametrize("exc", [AuthError, SessionExpiredError, NotFoundError, ParseError])
def test_domain_exceptions_share_base(exc: type[Exception]) -> None:
    err = exc("boom")
    assert isinstance(err, ZarfilmError)
