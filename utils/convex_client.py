"""
Minimal Convex HTTP client for the trading bot.

We don't need the full `convex` Python SDK -- this is just two POSTs
(heartbeat, snapshot) and one GET (status), all with shared-secret auth.
Using stdlib urllib keeps the dependency surface zero.

The client is FIRE-AND-FORGET-friendly: post_* methods catch and log
exceptions instead of raising, so a Convex outage cannot crash the
local monitor. JSONL files remain the source of truth on disk; Convex
is a parallel write for cloud visibility / alerting.

Usage:
    from utils.convex_client import ConvexClient
    cc = ConvexClient.from_env()
    cc.post_heartbeat(broker_login=5050327497, ...)
    cc.post_snapshot(broker_login=5050327497, balance=100000, ...)
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Retry-with-backoff for transient failures (5xx / network), added 2026-06-11
# after the 6/03 + 6/10 Convex blips. Three attempts with 1s, 4s sleeps:
# worst case ~20s including timeouts, safely inside the 60s poll loop.
# (The spec's 16s third sleep is intentionally dropped -- it would push the
# worst case to ~45s and crowd the poll budget.) 4xx errors do NOT retry:
# schema/auth failures are not transient.
RETRY_SLEEPS = (1.0, 4.0)

# Cross-channel degradation alert: if this many CONSECUTIVE posts fail
# transiently within the window, fire a DIRECT Pushover message (bypassing
# Convex entirely -- if Convex is down, the normal alert path is down with
# it). Keys come from .env, never from Convex.
TRANSIENT_ALERT_THRESHOLD = 10
TRANSIENT_WINDOW_SEC = 30 * 60
DIRECT_ALERT_COOLDOWN_SEC = 60 * 60
PUSHOVER_URL = "https://api.pushover.net/1/messages.json"

# Durable-payload outbox: snapshots/deals/signals that ultimately fail are
# queued to JSONL and replayed in order after the next successful post.
# Heartbeats are NOT queued (a stale heartbeat is meaningless later).
OUTBOX_PATH = Path(__file__).resolve().parents[1] / "logs" / "convex_outbox.jsonl"
OUTBOX_PATHS_BUFFERED = ("/snapshot", "/deals", "/signals")
OUTBOX_MAX_BYTES = 5 * 1024 * 1024


@dataclass
class ConvexClient:
    site_url: str
    shared_secret: str
    timeout_seconds: float = 5.0
    # degradation-alert state (instance-local, reset on success)
    _consec_transient: int = field(default=0, repr=False)
    _window_start: float = field(default=0.0, repr=False)
    _last_direct_alert: float = field(default=0.0, repr=False)

    @classmethod
    def from_env(cls) -> "ConvexClient | None":
        """Read CONVEX_SITE_URL + FTMO_BOT_SHARED_SECRET from env. Returns
        None (with a warning log) if either is missing -- the monitor can
        continue running without Convex in that case."""
        site = os.environ.get("CONVEX_SITE_URL")
        secret = os.environ.get("FTMO_BOT_SHARED_SECRET")
        if not site or not secret:
            log.warning(
                "ConvexClient.from_env: missing CONVEX_SITE_URL or "
                "FTMO_BOT_SHARED_SECRET; cloud posts disabled"
            )
            return None
        return cls(site_url=site.rstrip("/"), shared_secret=secret)

    def _post(self, path: str, body: dict[str, Any],
              _from_outbox: bool = False) -> dict | None:
        """POST JSON to a Convex HTTP Action. Returns the parsed JSON
        response, or None on any error (logged but not raised).

        Transient failures (HTTP 5xx, network errors, timeouts) are retried
        per RETRY_SLEEPS. Client errors (4xx) and unexpected exceptions fail
        immediately -- they are not transient. Final transient failures feed
        the cross-channel degradation alert; durable payloads (snapshot/
        deals/signals) additionally queue to the outbox for ordered replay."""
        url = f"{self.site_url}{path}"
        data = json.dumps(body).encode("utf-8")
        last_err = "unknown"
        attempts = len(RETRY_SLEEPS) + 1
        for attempt in range(attempts):
            try:
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={
                        "Content-Type": "application/json",
                        "X-Ftmo-Bot-Secret": self.shared_secret,
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                    out = json.loads(resp.read().decode("utf-8"))
                if not _from_outbox:
                    self._note_success()
                return out
            except urllib.error.HTTPError as e:
                body_str = e.read().decode("utf-8", errors="replace")[:200]
                if e.code < 500:
                    # 4xx: our bug (schema/auth), retrying cannot help
                    log.warning(
                        "ConvexClient POST %s failed: HTTP %d body=%s",
                        path, e.code, body_str,
                    )
                    return None
                last_err = f"HTTP {e.code} body={body_str}"
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = f"network error: {e}"
            except Exception as e:
                log.warning("ConvexClient POST %s unexpected error: %s", path, e)
                return None
            if attempt < len(RETRY_SLEEPS):
                time.sleep(RETRY_SLEEPS[attempt])
        log.warning(
            "ConvexClient POST %s failed after %d attempts: %s",
            path, attempts, last_err,
        )
        self._note_transient_failure(path, last_err)
        if not _from_outbox and path in OUTBOX_PATHS_BUFFERED:
            self._outbox_append(path, body)
        return None

    # ------------------------------------------------------------------ #
    # Cross-channel degradation alert (bypasses Convex entirely)
    # ------------------------------------------------------------------ #
    def _note_transient_failure(self, path: str, err: str) -> None:
        now = time.time()
        if now - self._window_start > TRANSIENT_WINDOW_SEC:
            self._window_start = now
            self._consec_transient = 0
        self._consec_transient += 1
        if (self._consec_transient >= TRANSIENT_ALERT_THRESHOLD
                and now - self._last_direct_alert > DIRECT_ALERT_COOLDOWN_SEC):
            self._last_direct_alert = now
            self._direct_pushover(
                "Convex pipeline DEGRADED",
                f"{self._consec_transient} consecutive transient failures in "
                f"{TRANSIENT_WINDOW_SEC // 60}min (last: {path}: {err}). "
                f"Telemetry is dark; the bot itself is unaffected.",
            )

    def _note_success(self) -> None:
        self._consec_transient = 0
        self._flush_outbox()

    def _direct_pushover(self, title: str, message: str) -> None:
        """Direct HTTPS to Pushover -- the ONLY alert that must not depend
        on Convex. Keys from env (.env); silently skipped (with a log) if
        absent so the monitor never crashes over alerting."""
        token = os.environ.get("PUSHOVER_API_TOKEN")
        user = os.environ.get("PUSHOVER_USER_KEY")
        if not token or not user:
            log.warning("direct pushover skipped: PUSHOVER_API_TOKEN/USER_KEY not in env")
            return
        try:
            data = urllib.parse.urlencode({
                "token": token, "user": user,
                "title": title, "message": message, "priority": 1,
            }).encode()
            req = urllib.request.Request(PUSHOVER_URL, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=self.timeout_seconds):
                pass
            log.warning("direct pushover sent: %s", title)
        except Exception as e:  # alerting must never crash the monitor
            log.warning("direct pushover failed: %s", e)

    # ------------------------------------------------------------------ #
    # Durable-payload outbox (replayed in order after recovery)
    # ------------------------------------------------------------------ #
    def _outbox_append(self, path: str, body: dict[str, Any]) -> None:
        try:
            OUTBOX_PATH.parent.mkdir(parents=True, exist_ok=True)
            if OUTBOX_PATH.exists() and OUTBOX_PATH.stat().st_size > OUTBOX_MAX_BYTES:
                log.warning("outbox full (>%d bytes); dropping %s payload",
                            OUTBOX_MAX_BYTES, path)
                return
            with OUTBOX_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": time.time(), "path": path, "body": body}) + "\n")
            log.warning("outbox: queued %s payload for replay", path)
        except Exception as e:
            log.warning("outbox append failed: %s", e)

    def _flush_outbox(self) -> None:
        try:
            if not OUTBOX_PATH.exists() or OUTBOX_PATH.stat().st_size == 0:
                return
            lines = OUTBOX_PATH.read_text(encoding="utf-8").splitlines()
        except Exception as e:
            log.warning("outbox read failed: %s", e)
            return
        remaining: list[str] = []
        replayed = 0
        for i, line in enumerate(lines):
            if remaining:                      # earlier item failed: keep order
                remaining.append(line)
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue                       # drop corrupt line
            out = self._post(item["path"], item["body"], _from_outbox=True)
            if out is None:
                remaining.append(line)         # stop replaying; keep the rest
            else:
                replayed += 1
        try:
            if remaining:
                OUTBOX_PATH.write_text("\n".join(remaining) + "\n", encoding="utf-8")
            else:
                OUTBOX_PATH.write_text("", encoding="utf-8")
        except Exception as e:
            log.warning("outbox rewrite failed: %s", e)
        if replayed:
            log.warning("outbox: replayed %d queued payload(s)", replayed)

    def post_heartbeat(
        self,
        *,
        broker_login: int,
        broker_server: str,
        account_type: str,
        initial_capital: float,
        currency: str,
        monitor_version: str,
        mt_connected: bool,
        ea_states: list[dict] | None = None,
    ) -> dict | None:
        return self._post("/heartbeat", {
            "brokerLogin": broker_login,
            "brokerServer": broker_server,
            "accountType": account_type,
            "initialCapital": initial_capital,
            "currency": currency,
            "monitorVersion": monitor_version,
            "mtConnected": mt_connected,
            "eaStates": ea_states or [],
        })

    def get_latest_deal_ticket(self, broker_login: int) -> int:
        """GET /latest-deal-ticket?brokerLogin=NNN -- returns the highest
        deal ticket the backend has stored, or 0 if no deals seen. Used
        by the monitor to fetch only NEW fills since last sync."""
        url = f"{self.site_url}/latest-deal-ticket?brokerLogin={broker_login}"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return int(data.get("latestTicket", 0))
        except Exception as e:
            log.warning("ConvexClient get_latest_deal_ticket failed: %s", e)
            return 0

    def post_deals(self, *, broker_login: int, deals: list[dict]) -> dict | None:
        """POST /deals — batch insert. Backend dedupes by (accountId, ticket)
        so re-sending the same fill is a no-op."""
        if not deals:
            return {"inserted": 0, "skipped": 0}
        return self._post("/deals", {
            "brokerLogin": broker_login,
            "deals": deals,
        })

    def post_signals(self, *, broker_login: int, events: list[dict]) -> dict | None:
        """POST /signals — batch ingest EA signal events parsed from MT5 logs."""
        if not events:
            return {"inserted": 0, "skipped": 0}
        return self._post("/signals", {
            "brokerLogin": broker_login,
            "events": events,
        })

    def post_snapshot(
        self,
        *,
        broker_login: int,
        broker_server: str,
        account_type: str,
        initial_capital: float,
        currency: str,
        balance: float,
        equity: float,
        profit: float,
        margin_used: float,
        margin_free: float,
        daily_limit_distance: float,
        max_limit_distance: float,
        ftmo_status: int,
        carry_today: float,
        positions: list[dict],
    ) -> dict | None:
        return self._post("/snapshot", {
            "brokerLogin": broker_login,
            "brokerServer": broker_server,
            "accountType": account_type,
            "initialCapital": initial_capital,
            "currency": currency,
            "balance": balance,
            "equity": equity,
            "profit": profit,
            "marginUsed": margin_used,
            "marginFree": margin_free,
            "dailyLimitDistance": daily_limit_distance,
            "maxLimitDistance": max_limit_distance,
            "ftmoStatus": ftmo_status,
            "carryToday": carry_today,
            "positions": positions,
        })
