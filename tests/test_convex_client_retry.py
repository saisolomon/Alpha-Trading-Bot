"""Regression tests for ConvexClient retry-with-backoff (M10, 2026-06-11).

Acceptance (Tasks.md, Convex pipeline resilience):
  - mock a 5xx then a 200 -> first call returns the 200 after one retry
  - mock a triple 5xx     -> call logs a warning and returns None (no raise)
  - mock a 4xx            -> NO retry (fails fast; not transient)

Runnable standalone (no pytest needed):  python tests/test_convex_client_retry.py
"""
from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils import convex_client as cc_mod
from utils.convex_client import ConvexClient


def _ok_response(payload: dict):
    class _Resp:
        def read(self):
            return json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return _Resp()


def _http_error(code: int):
    return urllib.error.HTTPError(
        url="http://x", code=code, msg="err", hdrs=None, fp=io.BytesIO(b"boom"),
    )


def make_client() -> ConvexClient:
    return ConvexClient(site_url="https://example.convex.site", shared_secret="s")


def test_5xx_then_200_returns_after_one_retry():
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise _http_error(500)
        return _ok_response({"ok": True})

    with mock.patch.object(cc_mod.urllib.request, "urlopen", fake_urlopen), \
         mock.patch.object(cc_mod.time, "sleep") as slept:
        out = make_client()._post("/snapshot", {"a": 1})
    assert out == {"ok": True}, out
    assert len(calls) == 2, calls
    assert slept.call_count == 1, slept.call_args_list
    print("PASS test_5xx_then_200_returns_after_one_retry")


def test_triple_5xx_returns_none_without_raising():
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        raise _http_error(503)

    with mock.patch.object(cc_mod.urllib.request, "urlopen", fake_urlopen), \
         mock.patch.object(cc_mod.time, "sleep") as slept:
        out = make_client()._post("/heartbeat", {"a": 1})
    assert out is None
    assert len(calls) == 3, f"expected 3 attempts, got {len(calls)}"  # 1 + 2 retries
    assert slept.call_count == 2
    print("PASS test_triple_5xx_returns_none_without_raising")


def test_4xx_fails_fast_no_retry():
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        raise _http_error(400)

    with mock.patch.object(cc_mod.urllib.request, "urlopen", fake_urlopen), \
         mock.patch.object(cc_mod.time, "sleep") as slept:
        out = make_client()._post("/snapshot", {"a": 1})
    assert out is None
    assert len(calls) == 1, f"4xx must not retry; attempts={len(calls)}"
    assert slept.call_count == 0
    print("PASS test_4xx_fails_fast_no_retry")


def test_network_error_retries_then_succeeds():
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        if len(calls) <= 2:
            raise urllib.error.URLError("handshake timed out")
        return _ok_response({"ok": 2})

    with mock.patch.object(cc_mod.urllib.request, "urlopen", fake_urlopen), \
         mock.patch.object(cc_mod.time, "sleep") as slept:
        out = make_client()._post("/snapshot", {"a": 1})
    assert out == {"ok": 2}
    assert len(calls) == 3
    assert slept.call_count == 2
    print("PASS test_network_error_retries_then_succeeds")


if __name__ == "__main__":
    test_5xx_then_200_returns_after_one_retry()
    test_triple_5xx_returns_none_without_raising()
    test_4xx_fails_fast_no_retry()
    test_network_error_retries_then_succeeds()
    print("ALL RETRY TESTS PASS")
