import urllib.request


def slow() -> None:
    urllib.request.urlopen("https://example.invalid")


def bounded() -> None:
    urllib.request.urlopen("https://example.invalid", timeout=3)


def suppressed() -> None:
    # The short rule id is enough: the suppression holds across rule updates.
    # nosemgrep: urlopen-without-timeout
    urllib.request.urlopen("https://example.invalid")


def wrong_id() -> None:
    # nosemgrep: no-such-rule
    urllib.request.urlopen("https://example.invalid")
