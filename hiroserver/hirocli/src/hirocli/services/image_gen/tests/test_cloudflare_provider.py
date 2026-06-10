"""Unit tests for the Cloudflare Workers AI image-gen provider (httpx stubbed)."""

from __future__ import annotations

import base64
from typing import Any

import pytest

import hirocli.services.image_gen.cloudflare_provider as cf
from hirocli.services.image_gen.cloudflare_provider import (
    CloudflareImageGenError,
    CloudflareImageGenProvider,
    _clamp_steps,
    _extract_image_b64,
)

_FAKE_JPEG = b"\xff\xd8\xff\xe0fakejpegbytes"
_FAKE_B64 = base64.b64encode(_FAKE_JPEG).decode("ascii")


class _StubResponse:
    def __init__(self, status_code: int = 200, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self) -> dict[str, Any]:
        return self._payload


class _StubClient:
    """Replaces httpx.AsyncClient; pops responses from a shared queue and records calls."""

    responses: list[_StubResponse] = []
    calls: list[dict[str, Any]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_StubClient":
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False

    async def post(self, url: str, headers: Any = None, json: Any = None) -> _StubResponse:
        _StubClient.calls.append({"url": url, "headers": headers, "json": json})
        return _StubClient.responses.pop(0)


@pytest.fixture()
def stub_client(monkeypatch: pytest.MonkeyPatch) -> type[_StubClient]:
    _StubClient.responses = []
    _StubClient.calls = []
    monkeypatch.setattr(cf.httpx, "AsyncClient", _StubClient)
    # No real sleeping between retry attempts.
    monkeypatch.setattr(cf, "_RETRY_BACKOFF_S", (0.0, 0.0))
    return _StubClient


def _provider() -> CloudflareImageGenProvider:
    return CloudflareImageGenProvider(api_token="tok", account_id="acct")


def test_availability_requires_both_credentials() -> None:
    assert _provider().is_available()
    assert not CloudflareImageGenProvider(api_token="tok", account_id=None).is_available()
    assert not CloudflareImageGenProvider(api_token=None, account_id="acct").is_available()


def test_clamp_steps_bounds() -> None:
    assert _clamp_steps(0) == 1
    assert _clamp_steps(4) == 4
    assert _clamp_steps(20) == 8


def test_extract_image_handles_rest_wrapper_and_raw_shape() -> None:
    assert _extract_image_b64({"result": {"image": "abc"}, "success": True}) == "abc"
    assert _extract_image_b64({"image": "abc"}) == "abc"
    assert _extract_image_b64({"result": {}, "success": True}) is None


@pytest.mark.asyncio
async def test_generate_success(stub_client: type[_StubClient]) -> None:
    stub_client.responses = [
        _StubResponse(200, {"result": {"image": _FAKE_B64}, "success": True})
    ]
    result = await _provider().generate("a red fox", steps=20, seed=7)

    assert result.image_bytes == _FAKE_JPEG
    assert result.mime_type == "image/jpeg"
    assert result.width == 1024 and result.height == 1024
    assert result.steps == 8  # clamped to the flux maximum

    call = stub_client.calls[0]
    assert "accounts/acct/ai/run/@cf/black-forest-labs/flux-1-schnell" in call["url"]
    assert call["headers"]["Authorization"] == "Bearer tok"
    assert call["json"] == {"prompt": "a red fox", "steps": 8, "seed": 7}


@pytest.mark.asyncio
async def test_generate_rejects_empty_and_oversized_prompts(stub_client: type[_StubClient]) -> None:
    with pytest.raises(ValueError):
        await _provider().generate("   ")
    with pytest.raises(ValueError):
        await _provider().generate("x" * 2049)


@pytest.mark.asyncio
async def test_generate_raises_on_api_error_payload(stub_client: type[_StubClient]) -> None:
    stub_client.responses = [
        _StubResponse(400, {"success": False, "errors": [{"message": "bad prompt"}]})
    ]
    with pytest.raises(CloudflareImageGenError, match="bad prompt"):
        await _provider().generate("a red fox")


@pytest.mark.asyncio
async def test_generate_retries_transient_then_succeeds(stub_client: type[_StubClient]) -> None:
    stub_client.responses = [
        _StubResponse(429, {}),
        _StubResponse(200, {"result": {"image": _FAKE_B64}, "success": True}),
    ]
    result = await _provider().generate("a red fox")
    assert result.image_bytes == _FAKE_JPEG
    assert len(stub_client.calls) == 2
