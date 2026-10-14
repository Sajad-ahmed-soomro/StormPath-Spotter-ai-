"""Shared HTTP session for third-party APIs (connection pooling + retries)."""

from __future__ import annotations

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class ExternalServiceError(Exception):
    """A third-party API failed; the message is safe to show to users."""


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=32)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers["User-Agent"] = settings.HTTP_USER_AGENT
    return session


_session: requests.Session | None = None


def session() -> requests.Session:
    global _session
    if _session is None:
        _session = _build_session()
    return _session
