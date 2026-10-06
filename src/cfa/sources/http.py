"""Shared HTTP client: timeouts, retries with backoff + jitter, Retry-After, per-host concurrency.

Never raises to callers; every request returns an HttpResult with a Status.
"""

from __future__ import annotations

import asyncio
import email.utils
import logging
import random
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import certifi
import httpx
from tenacity import AsyncRetrying, RetryCallState, retry_if_exception_type, stop_after_attempt

from cfa import config
from cfa.models.field_value import Status

log = logging.getLogger(__name__)


class _Retryable(Exception):
    def __init__(self, status: Status, note: str, retry_after: float | None = None) -> None:
        super().__init__(note)
        self.status = status
        self.note = note
        self.retry_after = retry_after


@dataclass
class HttpResult:
    status: Status
    response: httpx.Response | None = None
    note: str = ""
    elapsed_s: float = 0.0
    body: bytes | None = None

    @property
    def ok(self) -> bool:
        return self.status is Status.OK and self.response is not None

    @property
    def content(self) -> bytes:
        if self.body is not None:
            return self.body
        return self.response.content if self.response is not None else b""

    def json(self) -> Any:
        assert self.response is not None
        return self.response.json()


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, dt.timestamp() - time.time())


def _wait(state: RetryCallState) -> float:
    exc = state.outcome.exception() if state.outcome else None
    if isinstance(exc, _Retryable) and exc.retry_after is not None:
        return min(exc.retry_after, config.BACKOFF_MAX_S * 3)
    base = config.BACKOFF_BASE_S * (2 ** (state.attempt_number - 1))
    return min(config.BACKOFF_MAX_S, base) + random.uniform(0, config.BACKOFF_BASE_S)


def _redact(url: str) -> str:
    """Strip query strings (they can carry API keys) from logged URLs."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


class HttpClient:
    """Async client. Create one per event loop: `async with HttpClient() as http: ...`."""

    def __init__(
        self,
        *,
        max_retries: int = config.MAX_RETRIES,
        transport: httpx.AsyncBaseTransport | None = None,
        wait: Any = None,
    ) -> None:
        self._max_retries = max_retries
        self._transport = transport
        self._wait = wait or _wait
        self._client: httpx.AsyncClient | None = None
        self._host_limits: dict[str, asyncio.Semaphore] = {}

    async def __aenter__(self) -> HttpClient:
        timeout = httpx.Timeout(config.READ_TIMEOUT_S, connect=config.CONNECT_TIMEOUT_S)
        kwargs: dict[str, Any] = {
            "timeout": timeout,
            "headers": {"User-Agent": config.USER_AGENT},
            "follow_redirects": True,
        }
        if self._transport is not None:
            kwargs["transport"] = self._transport
        else:
            kwargs["verify"] = _ssl_verify()
        self._client = httpx.AsyncClient(**kwargs)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _sem(self, url: str) -> asyncio.Semaphore:
        host = urlsplit(url).netloc
        if host not in self._host_limits:
            self._host_limits[host] = asyncio.Semaphore(config.MAX_CONCURRENCY_PER_HOST)
        return self._host_limits[host]

    async def get(
        self, url: str, params: dict[str, Any] | None = None, max_bytes: int | None = None
    ) -> HttpResult:
        if self._client is None:
            raise RuntimeError("HttpClient used outside 'async with'")
        start = time.monotonic()
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._max_retries + 1),
                wait=self._wait,
                retry=retry_if_exception_type(_Retryable),
                reraise=True,
            ):
                with attempt:
                    result = await self._once(url, params, max_bytes)
        except _Retryable as exc:
            result = HttpResult(exc.status, None, exc.note)
        except Exception as exc:  # defensive: never raise to callers
            log.warning("GET %s unexpected error %s", _redact(url), type(exc).__name__)
            result = HttpResult(Status.SOURCE_UNAVAILABLE, None, f"Unexpected error: {type(exc).__name__}")
        result.elapsed_s = time.monotonic() - start
        log.info("GET %s -> %s (%.2fs)", _redact(url), result.status, result.elapsed_s)
        return result

    async def _once(self, url: str, params: dict[str, Any] | None, max_bytes: int | None) -> HttpResult:
        assert self._client is not None
        async with self._sem(url):
            body: bytes | None = None
            try:
                if max_bytes is None:
                    resp = await self._client.get(url, params=params)
                else:
                    capped = await self._get_capped(url, params, max_bytes)
                    if isinstance(capped, HttpResult):
                        return capped
                    resp, body = capped
            except httpx.TimeoutException as exc:
                raise _Retryable(Status.SOURCE_UNAVAILABLE, "Timed out") from exc
            except httpx.TransportError as exc:
                raise _Retryable(
                    Status.SOURCE_UNAVAILABLE, f"Connection error: {type(exc).__name__}"
                ) from exc
        code = resp.status_code
        if code == 429:
            raise _Retryable(
                Status.RATE_LIMITED,
                "Rate limited (HTTP 429)",
                parse_retry_after(resp.headers.get("Retry-After")),
            )
        if code >= 500:
            raise _Retryable(
                Status.SOURCE_UNAVAILABLE,
                f"Server error (HTTP {code})",
                parse_retry_after(resp.headers.get("Retry-After")),
            )
        if code in (401, 403):
            return HttpResult(Status.AUTH_MISSING, resp, f"Not authorized (HTTP {code})")
        if code >= 400:
            return HttpResult(Status.SOURCE_UNAVAILABLE, resp, f"HTTP {code}")
        return HttpResult(Status.OK, resp, body=body)

    async def _get_capped(
        self, url: str, params: dict[str, Any] | None, max_bytes: int
    ) -> tuple[httpx.Response, bytes] | HttpResult:
        assert self._client is not None
        async with self._client.stream("GET", url, params=params) as resp:
            declared = resp.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                return HttpResult(
                    Status.PARSE_FAILED, None, f"File larger than {max_bytes // (1024 * 1024)} MB"
                )
            if resp.status_code >= 400:
                return resp, await resp.aread()
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    return HttpResult(
                        Status.PARSE_FAILED, None, f"File larger than {max_bytes // (1024 * 1024)} MB"
                    )
                chunks.append(chunk)
            return resp, b"".join(chunks)


def _ssl_verify() -> Any:
    """Use certifi's bundle (PyInstaller-safe); honor a corporate CA bundle if the env sets one."""
    import os
    import ssl

    ctx = ssl.create_default_context(cafile=certifi.where())
    extra = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if extra and os.path.exists(extra):
        ctx.load_verify_locations(cafile=extra)
    return ctx
