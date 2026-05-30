"""Cliente HTTP con reintentos, backoff y rate-limiting cortés."""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Optional

import requests
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from .config import Config

logger = logging.getLogger(__name__)


class TransientHTTPError(Exception):
    """Error recuperable (429 / 5xx) que justifica reintento."""


class JumboClient:
    """Envoltura sobre requests.Session con backoff y pausas entre llamadas."""

    def __init__(self, config: Config):
        self.config = config
        self.session = self._build_session()
        self._last_request_ts = 0.0

    def _build_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update(
            {
                "User-Agent": self.config.user_agent,
                "Accept": "application/json",
                "Accept-Language": "es-CL,es;q=0.9",
                "Referer": "https://www.jumbo.cl/",
            }
        )
        return s

    def _throttle(self) -> None:
        """Mantiene una pausa aleatoria entre requests para no saturar el sitio."""
        elapsed = time.monotonic() - self._last_request_ts
        delay = random.uniform(self.config.min_delay, self.config.max_delay)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_request_ts = time.monotonic()

    def _request(self, url: str, params: Optional[dict] = None) -> requests.Response:
        for attempt in Retrying(
            retry=retry_if_exception_type((TransientHTTPError, requests.ConnectionError, requests.Timeout)),
            wait=wait_exponential_jitter(initial=1, max=30),
            stop=stop_after_attempt(self.config.max_retries),
            reraise=True,
        ):
            with attempt:
                self._throttle()
                resp = self.session.get(url, params=params, timeout=self.config.request_timeout)
                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                    logger.warning("HTTP %s en %s — reintentando", resp.status_code, resp.url)
                    raise TransientHTTPError(f"status={resp.status_code}")
                resp.raise_for_status()
        return resp

    def get_json(self, url: str, params: Optional[dict] = None) -> Any:
        """GET que devuelve JSON parseado."""
        resp = self._request(url, params=params)
        if not resp.content:
            return None
        return resp.json()

    def get_with_range(self, url: str, params: Optional[dict] = None):
        """GET que además devuelve el total reportado por el header
        'resources' / 'Rest-Content-Range' (formato 'items 0-49/1234')."""
        resp = self._request(url, params=params)
        total = None
        header = resp.headers.get("resources") or resp.headers.get("Rest-Content-Range")
        if header and "/" in header:
            try:
                total = int(header.rsplit("/", 1)[1])
            except (ValueError, IndexError):
                total = None
        data = resp.json() if resp.content else []
        return data, total

    def close(self) -> None:
        self.session.close()
