"""
Order slicer — breaks large orders into TWAP time-slices.

Policy (from Planning.md):
  Threshold: orders > 1% of average bar volume on the strategy timeframe
  → sliced into N equal parts executed at equal time intervals.
  Participation cap: 10% of average bar volume per slice.

Only TWAP is implemented in v1. VWAP is in the backlog.

Usage:
    slicer = TwapSlicer(avg_bar_volume=1500, participation_cap=0.10)
    slices = slicer.plan(total_volume=5.0)
    for s in slices:
        send_slice(s)
        time.sleep(s.interval_seconds)
"""
from __future__ import annotations

import math
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Slice plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OrderSlice:
    """One slice of a larger order."""
    slice_index: int
    total_slices: int
    volume: float          # lots for this slice
    interval_seconds: float  # wait BEFORE sending (0 for first slice)

    @property
    def is_last(self) -> bool:
        return self.slice_index == self.total_slices - 1


@dataclass(frozen=True)
class SlicePlan:
    """Complete TWAP slice plan for one parent order."""
    total_volume: float
    slices: list[OrderSlice]
    total_duration_seconds: float
    reason: str  # "sliced" or "single" (order small enough to go direct)

    @property
    def is_single(self) -> bool:
        return len(self.slices) == 1


# ---------------------------------------------------------------------------
# TwapSlicer
# ---------------------------------------------------------------------------


class TwapSlicer:
    """Plans TWAP execution for an order.

    Parameters
    ----------
    avg_bar_volume:
        Average tick_volume on the strategy's primary timeframe.
        Used to determine whether slicing is needed.
    volume_threshold_pct:
        Orders above this fraction of avg_bar_volume are sliced. Default 0.01 (1%).
    participation_cap_pct:
        Maximum fraction of avg_bar_volume per slice. Default 0.10 (10%).
    interval_seconds:
        Time between slices in seconds. Default 60.
    min_slice_volume:
        Minimum lots per slice (broker-specific, typically 0.01). Default 0.01.
    """

    def __init__(
        self,
        avg_bar_volume: float,
        volume_threshold_pct: float = 0.01,
        participation_cap_pct: float = 0.10,
        interval_seconds: float = 60.0,
        min_slice_volume: float = 0.01,
    ) -> None:
        self._avg_vol = avg_bar_volume
        self._threshold_pct = volume_threshold_pct
        self._cap_pct = participation_cap_pct
        self._interval = interval_seconds
        self._min_slice = min_slice_volume

    def plan(self, total_volume: float) -> SlicePlan:
        """Create a TWAP slice plan for the given volume.

        If the order is small enough (below threshold), a single-slice plan
        is returned with interval_seconds=0 (send immediately).

        Parameters
        ----------
        total_volume:
            Total order volume in lots.
        """
        threshold = self._avg_vol * self._threshold_pct

        if total_volume <= threshold or self._avg_vol <= 0:
            return SlicePlan(
                total_volume=total_volume,
                slices=[OrderSlice(0, 1, total_volume, 0.0)],
                total_duration_seconds=0.0,
                reason="single",
            )

        # Max volume per slice based on participation cap
        max_per_slice = max(self._min_slice, self._avg_vol * self._cap_pct)
        n_slices = math.ceil(total_volume / max_per_slice)
        n_slices = max(2, n_slices)  # always at least 2 slices if slicing is triggered

        base_vol = round(total_volume / n_slices, 2)
        # Distribute remainder to last slice to avoid rounding errors
        last_vol = round(total_volume - base_vol * (n_slices - 1), 2)

        slices = []
        for i in range(n_slices):
            vol = last_vol if i == n_slices - 1 else base_vol
            vol = max(self._min_slice, vol)
            slices.append(OrderSlice(
                slice_index=i,
                total_slices=n_slices,
                volume=vol,
                interval_seconds=0.0 if i == 0 else self._interval,
            ))

        return SlicePlan(
            total_volume=total_volume,
            slices=slices,
            total_duration_seconds=(n_slices - 1) * self._interval,
            reason="sliced",
        )

    def needs_slicing(self, volume: float) -> bool:
        """Return True if this volume requires TWAP slicing."""
        return volume > self._avg_vol * self._threshold_pct and self._avg_vol > 0
