import httpx
import pytest
import respx

from cfa.models.field_value import Status
from cfa.sources.http import HttpClient, parse_retry_after
from tests.conftest import no_wait

URL = "https://example.test/api"


@respx.mock
async def test_ok(http):
    respx.get(URL).respond(200, json={"a": 1})
    res = await http.get(URL)
    assert res.ok and res.json() == {"a": 1}


@respx.mock
async def test_429_then_200_retries(http):
    route = respx.get(URL).mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(200, json={})]
    )
    res = await http.get(URL)
    assert res.ok and route.call_count == 2


@respx.mock
async def test_500_three_times_gives_unavailable():
    route = respx.get(URL).respond(500)
    async with HttpClient(max_retries=2, wait=no_wait) as http:
        res = await http.get(URL)
    assert res.status is Status.SOURCE_UNAVAILABLE and route.call_count == 3


@respx.mock
async def test_persistent_429_is_rate_limited(http):
    respx.get(URL).respond(429)
    res = await http.get(URL)
    assert res.status is Status.RATE_LIMITED


@respx.mock
async def test_timeout(http):
    route = respx.get(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    res = await http.get(URL)
    assert res.status is Status.SOURCE_UNAVAILABLE and "Timed out" in res.note
    assert route.call_count == 4


@respx.mock
async def test_connect_error(http):
    respx.get(URL).mock(side_effect=httpx.ConnectError("offline"))
    res = await http.get(URL)
    assert res.status is Status.SOURCE_UNAVAILABLE


@respx.mock
async def test_404_not_retried(http):
    route = respx.get(URL).respond(404)
    res = await http.get(URL)
    assert res.status is Status.SOURCE_UNAVAILABLE and route.call_count == 1


@respx.mock
async def test_403_is_auth(http):
    respx.get(URL).respond(403)
    assert (await http.get(URL)).status is Status.AUTH_MISSING


@respx.mock
async def test_size_cap(http):
    respx.get(URL).respond(200, content=b"x" * 5000)
    res = await http.get(URL, max_bytes=1000)
    assert res.status is Status.PARSE_FAILED and res.response is None
    ok = await http.get(URL, max_bytes=10_000)
    assert ok.ok and ok.content == b"x" * 5000


@respx.mock
async def test_user_agent(http):
    route = respx.get(URL).respond(200)
    await http.get(URL)
    assert route.calls.last.request.headers["User-Agent"].startswith("CollegeFitAdvisor/")


def test_retry_after_parsing():
    assert parse_retry_after("3") == 3.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("garbage") is None
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0


async def test_used_outside_context():
    with pytest.raises(RuntimeError):
        await HttpClient().get(URL)
