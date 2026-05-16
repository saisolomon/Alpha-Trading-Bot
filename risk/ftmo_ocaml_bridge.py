"""
Bridge between Python risk/ftmo.py and the OCaml ftmo_risk library.

This module provides a way to verify the Python implementation against
the OCaml port BIT-FOR-BIT. The OCaml engine is the single source of
truth (per ARCHITECTURE.md); Python is what the backtest currently uses.

The bridge runs the OCaml CLI (`dune exec bin/main.exe`) on the SAME
tick sequence as the Python engine and asserts the status codes match.

Once we have an actual libftmorisk.dll built with ocamlmklib + C stubs
(Phase 5 follow-on), this module will be replaced with a ctypes wrapper
that calls the DLL directly per tick -- no subprocess overhead.

For now this is a CORRECTNESS GATE in the test suite, not a runtime
component. The Python implementation in risk/ftmo.py remains the actual
runtime; the bridge proves the OCaml port matches.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
OCAML_DIR = REPO_ROOT / "ocaml"


def ocaml_available() -> bool:
    """True if dune + an opam switch with ftmo_risk built are reachable."""
    if shutil.which("dune") is None:
        return False
    # Heuristic: must have built the lib at least once.
    build_marker = OCAML_DIR / "_build"
    return build_marker.exists()


@dataclass
class OcamlVerifyTickResult:
    """Result of one apply_tick run via the OCaml CLI verifier."""
    py_status_code: int     # 0=Active, 1=Imminent, 2=InternalKilled, 3=FtmoFailed
    ocaml_status_code: int
    match: bool


def _run_ocaml_cli(args: list[str]) -> str:
    """Run `dune exec bin/main.exe -- <args>` and return stdout."""
    if not ocaml_available():
        raise RuntimeError("OCaml toolchain not available -- see ocaml/README.md")
    # We invoke dune with --root so the working directory doesn't matter.
    result = subprocess.run(
        ["dune", "exec", "bin/main.exe", "--root", str(OCAML_DIR), "--"] + args,
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"OCaml CLI failed (rc={result.returncode}): {result.stderr}"
        )
    return result.stdout


def python_status_to_code(state, equity: float, exc: Optional[BaseException]) -> int:
    """Map the Python equity_tick outcome to the same code scheme the OCaml
    state machine uses. equity_tick is exception-driven, so the caller
    passes in the exception that was raised (or None for Active)."""
    from risk.ftmo import FTMOInternalBreach, FTMOImminent
    if exc is None:
        return 0  # Active
    if isinstance(exc, FTMOImminent):
        return 1  # Imminent
    if isinstance(exc, FTMOInternalBreach):
        return 2  # Internal_killed
    # NOTE: the Python impl doesn't have an Ftmo_failed status -- it relies
    # on the simulator (backtest/ftmo_sim.py) to detect FTMO-line crossings
    # against the limits. So we never get code 3 from the live Python engine.
    return -1  # unknown
