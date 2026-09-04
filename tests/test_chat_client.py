import httpx
import pytest

from app.core.chat_client import ChatApiError, GoogleChatClient


class _FakeHttpx:
    def __init__(self, handler):
        self._handler = handler

    def __call__(self, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, headers=None, params=None):
        request = httpx.Request("GET", url, params=params)
        return self._handler(request)

    def post(self, url, headers=None, json=None):
        request = httpx.Request("POST", url, headers=headers, json=json)
        return self._handler(request)


def test_create_dm_returns_existing_space(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "findDirectMessage" in str(request.url)
        return httpx.Response(200, json={"name": "spaces/AAAAtest"})

    monkeypatch.setattr("app.core.chat_client.httpx.Client", _FakeHttpx(handler))
    client = GoogleChatClient(access_token="tok")
    assert client.create_dm("123456789") == "spaces/AAAAtest"


def test_create_dm_surfaces_http_body(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text='{"error":"permission denied"}')

    monkeypatch.setattr("app.core.chat_client.httpx.Client", _FakeHttpx(handler))
    client = GoogleChatClient(access_token="tok")
    with pytest.raises(ChatApiError) as exc:
        client.create_dm("123456789")
    assert exc.value.status_code == 403
    assert "permission denied" in exc.value.body
