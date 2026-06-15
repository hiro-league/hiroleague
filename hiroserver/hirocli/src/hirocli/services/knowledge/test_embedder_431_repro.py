"""Repro harness for the eval-run 431 (``request_headers_too_large``) — observed evidence only.

A real memory-eval run died mid-run with OpenAI's ``431 Request headers are too large`` raised
from the **recall leg's embedding call**: ``GraphitiEmbedderClient.create`` → ``asyncio.to_thread``
→ ``CatalogEmbeddingsBackend.embed_texts`` → ``langchain_openai`` → ONE shared sync OpenAI client,
hit concurrently by up to ``MAX_QUESTION_CONCURRENCY`` worker threads.

These tests reproduce that EXACT client stack and concurrency pattern against a local fake
OpenAI-compatible embeddings server that records every request's raw header block, so we can
measure — not guess — whether client-side state (cookie jar, retries, thread-shared connections)
makes request headers grow or corrupts requests on the wire:

* ``test_eval_concurrency_headers_stay_bounded`` — the faithful repro (Cloudflare-style cookies:
  fixed names, rotating values). If headers grow or any request corrupts, this FAILS and the 431
  is a client-side bug we can fix here.
* ``test_rotating_cookie_names_grow_headers`` — positive control: a server that mints a NEW cookie
  name per response. Proves the harness detects unbounded ``Cookie`` growth (the shape a real
  client-side 431 would take), so a pass on the faithful repro is meaningful, not blind.
"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from hirocli.services.knowledge.embedder import CatalogEmbeddingsBackend
from hirocli.services.knowledge.graph.graphiti_adapters import GraphitiEmbedderClient

# Mirrors the production fan-out: MAX_QUESTION_CONCURRENCY parallel questions, each recall
# embedding its query through the one shared backend.
_LANES = 8
_ROUNDS = 25
_DIM = 8


class _FakeOpenAIServer(ThreadingHTTPServer):
    """Local OpenAI-compatible /v1/embeddings endpoint that records request headers.

    ``cookie_mode``:
      * ``"cloudflare"`` — two fixed-name cookies (``__cf_bm``/``_cfuvid``) with a fresh value on
        every response, exactly what api.openai.com's edge does (sans ``Secure``, so the jar
        replays them over plain http in the test).
      * ``"rotate_names"`` — a NEW cookie name each response (positive control: forces unbounded
        jar growth).
    """

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, cookie_mode: str, *, always_431: bool = False) -> None:
        super().__init__(("127.0.0.1", 0), _EmbeddingsHandler)
        self.cookie_mode = cookie_mode
        self.always_431 = always_431
        self.lock = threading.Lock()
        self.records: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.counter = 0


class _EmbeddingsHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive, like the real edge — exercises pooled connections
    server: _FakeOpenAIServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 — stdlib signature
        pass  # keep pytest output readable

    def do_POST(self) -> None:  # noqa: N802 — stdlib handler naming
        try:
            self._handle_embeddings()
        except Exception as exc:  # record, don't hide — a corrupt request must fail the test
            with self.server.lock:
                self.server.errors.append(f"{type(exc).__name__}: {exc}")
            raise

    def _handle_embeddings(self) -> None:
        # Raw header block size = what a gateway's 431 limit actually meters.
        raw_header_block = "".join(f"{k}: {v}\r\n" for k, v in self.headers.items())
        header_bytes = len(self.requestline.encode()) + 2 + len(raw_header_block.encode()) + 2
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        payload = json.loads(body)  # a thread-corrupted/interleaved request explodes right here
        inputs = payload.get("input")
        n = len(inputs) if isinstance(inputs, list) else 1

        with self.server.lock:
            self.server.counter += 1
            seq = self.server.counter
            self.server.records.append(
                {
                    "seq": seq,
                    "header_bytes": header_bytes,
                    "cookie_len": len(self.headers.get("Cookie") or ""),
                    "n_headers": len(self.headers),
                }
            )

        if self.server.always_431:
            # The production failure, verbatim (OpenAI's envelope for this code).
            err = json.dumps(
                {
                    "error": {
                        "message": "Request headers are too large.",
                        "type": "invalid_request_error",
                        "param": None,
                        "code": "request_headers_too_large",
                    }
                }
            ).encode()
            self.send_response(431)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)
            return

        data = [
            {"object": "embedding", "embedding": [0.1] * _DIM, "index": i} for i in range(n)
        ]
        resp = json.dumps(
            {
                "object": "list",
                "data": data,
                "model": "text-embedding-3-small",
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        if self.server.cookie_mode == "cloudflare":
            # Fixed names, fresh values — http.cookiejar REPLACES by (domain, path, name).
            self.send_header(
                "Set-Cookie", f"__cf_bm={uuid.uuid4().hex}{uuid.uuid4().hex}; path=/; HttpOnly"
            )
            self.send_header("Set-Cookie", f"_cfuvid={uuid.uuid4().hex}; path=/; HttpOnly")
        else:  # rotate_names — every response adds a brand-new cookie to the jar
            self.send_header("Set-Cookie", f"probe_{seq}={uuid.uuid4().hex}; path=/; HttpOnly")
        self.end_headers()
        self.wfile.write(resp)


def _build_embedder_stack(port: int) -> GraphitiEmbedderClient:
    """The production wiring, byte-for-byte: OpenAIEmbeddings → CatalogEmbeddingsBackend →
    GraphitiEmbedderClient — one shared sync client, exactly like ``resolve_knowledge_embedder``."""
    from langchain_openai import OpenAIEmbeddings

    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small",
        api_key="sk-test-431-repro",
        base_url=f"http://127.0.0.1:{port}/v1",
        check_embedding_ctx_length=_tiktoken_available(),
    )
    backend = CatalogEmbeddingsBackend(
        embeddings, model_id="openai:text-embedding-3-small", dimension=_DIM
    )
    return GraphitiEmbedderClient(backend, embedding_dim=_DIM)


def _tiktoken_available() -> bool:
    """Use the real tokenized request path (the failing traceback's line) when the tiktoken
    encoding is cached locally; fall back to plain-string inputs offline (identical headers —
    the thing under test — only the JSON body shape differs)."""
    try:
        import tiktoken

        tiktoken.encoding_for_model("text-embedding-3-small")
        return True
    except Exception:
        return False


async def _question_lane(embedder: GraphitiEmbedderClient, lane: int, rounds: int) -> None:
    """One 'question' worth of recall embeds, looped — same call shape as _traced_search."""
    for r in range(rounds):
        vec = await embedder.create([f"recall query lane={lane} round={r} " + "memory " * 8])
        assert len(vec) == _DIM


async def _hammer(embedder: GraphitiEmbedderClient, *, lanes: int, rounds: int) -> None:
    """The eval's parallel question phase in miniature: a TaskGroup of lanes, each lane embedding
    serially — so ``lanes`` worker threads hit the ONE shared sync client at any moment."""
    async with asyncio.TaskGroup() as tg:
        for lane in range(lanes):
            tg.create_task(_question_lane(embedder, lane, rounds))


def _growth(records: list[dict[str, Any]]) -> tuple[int, int, int]:
    """(first-request header bytes, max header bytes, growth) across the run, in arrival order."""
    sizes = [r["header_bytes"] for r in records]
    return sizes[0], max(sizes), max(sizes) - sizes[0]


@pytest.mark.asyncio
async def test_eval_concurrency_headers_stay_bounded() -> None:
    """Faithful repro of the failing run: 8 parallel lanes × shared sync client × Cloudflare-style
    rotating cookie VALUES. Headers must stay flat and every request must parse cleanly — if this
    fails, the 431 is reproducible client-side and the failure mode is in the report string."""
    server = _FakeOpenAIServer(cookie_mode="cloudflare")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        embedder = _build_embedder_stack(server.server_address[1])
        await _hammer(embedder, lanes=_LANES, rounds=_ROUNDS)
    finally:
        server.shutdown()
        server.server_close()

    assert not server.errors, f"corrupted/unparseable requests reached the server: {server.errors}"
    assert len(server.records) == _LANES * _ROUNDS, (
        f"request count mismatch: {len(server.records)} != {_LANES * _ROUNDS} "
        "(lost or duplicated requests under thread-shared client)"
    )
    first, peak, growth = _growth(server.records)
    cookies = [r["cookie_len"] for r in server.records]
    report = (
        f"headers: first={first}B peak={peak}B growth={growth}B · "
        f"cookie: first={cookies[0]}B last={cookies[-1]}B max={max(cookies)}B · "
        f"requests={len(server.records)}"
    )
    print(f"\n[431-repro · cloudflare-mode] {report}")
    # Replay sanity: the jar is live (later requests DO carry a Cookie header), so a flat size
    # is evidence of replacement-not-accumulation — not of cookies being ignored.
    assert max(cookies) > 0, "client never replayed cookies — harness not faithful to production"
    assert growth < 512, f"request headers grew under eval concurrency — 431 mechanism FOUND: {report}"


@pytest.mark.asyncio
async def test_rotating_cookie_names_grow_headers() -> None:
    """Positive control: rotating cookie NAMES must grow the shared jar without bound and the
    harness must SEE it. Proves the bounded result above is a real negative, not a blind one."""
    server = _FakeOpenAIServer(cookie_mode="rotate_names")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        embedder = _build_embedder_stack(server.server_address[1])
        # Serial lane is enough — growth is per-response, concurrency irrelevant here.
        await _hammer(embedder, lanes=1, rounds=40)
    finally:
        server.shutdown()
        server.server_close()

    first, peak, growth = _growth(server.records)
    print(f"\n[431-repro · rotate-names control] first={first}B peak={peak}B growth={growth}B")
    assert growth > 1024, (
        "harness failed to detect unbounded Cookie growth — its bounded-headers verdict "
        "in the faithful repro would be meaningless"
    )


@pytest.mark.asyncio
async def test_431_failure_logs_request_header_postmortem() -> None:
    """When the endpoint answers the production 431, the backend must (a) re-raise the
    APIStatusError unchanged — eval failure semantics stay intact — and (b) emit the header
    post-mortem (names + sizes of the EXACT failed request) so the next real occurrence is
    self-diagnosing. The probe is best-effort: this also guards it against masking the error."""
    import openai

    server = _FakeOpenAIServer(cookie_mode="cloudflare", always_431=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        embedder = _build_embedder_stack(server.server_address[1])
        with pytest.raises(openai.APIStatusError) as excinfo:
            await embedder.create(["the recall query that hits the 431"])
    finally:
        server.shutdown()
        server.server_close()

    assert excinfo.value.status_code == 431
    # The probe's evidence source: the failed httpx request (with its on-the-wire headers)
    # must be reachable from the raised error — that's what _log_embed_http_failure reads.
    request = excinfo.value.response.request
    assert "authorization" in request.headers
    header_total = sum(len(k) + len(v) + 4 for k, v in request.headers.items())
    print(f"\n[431-repro · postmortem] failed-request header_total={header_total}B")
    assert header_total < 2048  # sanity: a genuinely small request still 431'd (server-decided)
