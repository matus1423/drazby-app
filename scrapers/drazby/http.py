"""Slušný HTTP klient: identifikovateľný User-Agent, pauzy, retry s backoffom, robots.txt."""

from __future__ import annotations

import logging
import random
import time
import urllib.robotparser
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

USER_AGENT = (
    "drazby-app/0.1 (+https://github.com/matus1423/drazby-app; "
    "nekomercny agregator verejnych oznameni o drazbach)"
)

RETRY_STATUS = {429, 500, 502, 503, 504}


class Blocked(Exception):
    """Zdroj zakazuje prístup (robots.txt) — nesťahujeme."""


class RateLimited(Exception):
    """Zdroj žiada dlhú prestávku (Retry-After nad limit) — beh ukončíme a pokračujeme nabudúce."""


class PoliteClient:
    def __init__(self, min_delay: float = 1.5, timeout: float = 60.0, retries: int = 5,
                 respect_robots: bool = True, max_wait: float = 120.0):
        self.max_wait = max_wait
        self.min_delay = min_delay
        self.retries = retries
        self.respect_robots = respect_robots
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "sk,en;q=0.5"},
            timeout=timeout,
            follow_redirects=True,
        )

    # --- robots.txt -------------------------------------------------------
    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.client.get(base + "/robots.txt")
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except httpx.HTTPError:
                rp = None  # robots.txt nedostupný → správame sa opatrne, ale povolíme
            self._robots[base] = rp
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(USER_AGENT, url)

    # --- pauza na hostiteľa ----------------------------------------------
    def _wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            wait = self.min_delay - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last[host] = time.monotonic()

    def get(self, url: str, **kw) -> httpx.Response:
        if not self.allowed(url):
            raise Blocked(f"robots.txt zakazuje {url}")
        host = urlsplit(url).netloc
        err: Exception | None = None
        for attempt in range(self.retries):
            self._wait(host)
            try:
                r = self.client.get(url, **kw)
                if r.status_code in RETRY_STATUS:
                    err = httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
                    ra = _retry_after(r)
                    if ra and ra > self.max_wait:
                        raise RateLimited(f"{host} žiada počkať {ra:.0f} s (HTTP {r.status_code})")
                    delay = ra or _backoff(attempt)
                    log.warning("%s → %s, opakujem o %.0f s", url, r.status_code, delay)
                    time.sleep(delay)
                    continue
                r.raise_for_status()
                return r
            except (httpx.TransportError, httpx.RemoteProtocolError) as e:
                err = e
                delay = _backoff(attempt)
                log.warning("%s → %s, opakujem o %.0f s", url, type(e).__name__, delay)
                time.sleep(delay)
        assert err is not None
        raise err

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _backoff(attempt: int) -> float:
    return min(60.0, 2.0 * (2 ** attempt)) + random.uniform(0, 1)


def _retry_after(r: httpx.Response) -> float | None:
    v = r.headers.get("retry-after")
    try:
        return float(v) if v else None
    except ValueError:
        return None
