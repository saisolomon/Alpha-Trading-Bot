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
import urllib.request
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

# Retry-with-backoff for transient failures (5xx / network), added 2026-06-11
# after the 6/03 + 6/10 Convex blips. Three attempts with 1s, 4s sleeps:
# worst case ~20s including timeouts, safely inside the 60s poll loop.
# (The spec's 16s third sleep is intentionally dropped -- it would push the
# worst case to ~45s and crowd the poll budget.) 4xx errors do NOT retry:
# schema/auth failures are not transient.
RETRY_SLEEPS = (1.0, 4.0)


@dataclass
class ConvexClient:
    site_url: str
    shared_secret: str
    timeout_seconds: float = 5.0

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

    def _post(self, path: str, body: dict[str, Any]) -> dict | None:
        """POST JSON to a Convex HTTP Action. Returns the parsed JSON
        response, or None on any error (logged but not raised).

        Transient failures (HTTP 5xx, network errors, timeouts) are retried
        per RETRY_SLEEPS. Client errors (4xx) and unexpected exceptions fail
        immediately -- they are not transient."""
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
                    return json.loads(resp.read().decode("utf-8"))
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
        return None

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
