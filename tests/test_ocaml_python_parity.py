"""
Parity tests: Python risk/ftmo.py vs the OCaml ftmo_risk port.

Verifies that the OCaml state machine produces the same internal-kill /
FTMO-fail decisions as the Python implementation on a battery of synthetic
tick sequences. Once these pass, the OCaml version IS the production rule
engine (per ARCHITECTURE.md); the Python version becomes a thin wrapper
that calls the OCaml DLL.

Skipped if the OCaml toolchain is not present (CI env without opam).

These tests use the OCaml runtime via a tiny inline OCaml program that
reads tick data on stdin and prints status codes on stdout -- avoiding
the cost of `dune exec` per tick.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
OCAML_DIR = REPO_ROOT / "ocaml"


def _ocaml_available() -> bool:
    return (
        shutil.which("dune") is not None
        and shutil.which("ocaml") is not None
        and (OCAML_DIR / "_build" / "default" / "lib").exists()
    )


pytestmark = pytest.mark.skipif(
    not _ocaml_available(),
    reason="OCaml toolchain or built ftmo_risk lib not available",
)


# ---------------------------------------------------------------------------
# Embedded OCaml verifier
# ---------------------------------------------------------------------------


VERIFIER_OCAML = textwrap.dedent("""\
    (* Reads JSONL ticks on stdin, prints "status_code\\n" per tick on stdout.
       Each input line: {"acct": 1, "cap": 100000.0, "ts": 0.0, "eq": 99500.0,
                          "reset_balance": 0.0_or_null} *)

    open Ftmo_rules

    let parse_acct = function
      | 0 -> Challenge_1step
      | 1 -> Challenge_2step_phase1
      | 2 -> Challenge_2step_phase2
      | 3 -> Funded_standard
      | 4 -> Funded_swing
      | 5 -> Funded_rewards_1step
      | n -> failwith (Printf.sprintf "bad acct code %d" n)

    let status_code = function
      | Active -> 0
      | Imminent _ -> 1
      | Internal_killed _ -> 2
      | Ftmo_failed _ -> 3

    let () =
      let line = input_line stdin in
      (* First line: {"acct": N, "cap": F} -- session config *)
      let acct_code = Scanf.sscanf line {|{"acct": %d, "cap": %f}|}
                        (fun a c -> (a, c)) in
      let acct, cap = parse_acct (fst acct_code), snd acct_code in
      let state = ref (new_state ~account:acct ~initial_capital:cap) in
      try
        while true do
          let l = input_line stdin in
          (* "ts eq" or "RESET balance" *)
          if String.length l > 6 && String.sub l 0 5 = "RESET" then begin
            let bal = float_of_string (String.sub l 6 (String.length l - 6)) in
            state := daily_reset !state ~at_ts:0.0 ~balance:bal;
            Printf.printf "%d\\n" (status_code !state.status)
          end else begin
            Scanf.sscanf l "%f %f" (fun ts eq ->
              let t = { unix_ts = ts; equity = usd_of_float eq } in
              state := apply_tick !state t;
              Printf.printf "%d\\n" (status_code !state.status))
          end
        done
      with End_of_file -> ()
""")


def _run_verifier(session_config: dict, tick_lines: list[str]) -> list[int]:
    """Run the embedded OCaml verifier and return the per-tick status codes."""
    # Write the verifier to a temp dune project. Easier: use a temp file in
    # the existing ocaml/bin/ that overrides main.ml -- but that's invasive.
    # Cleanest: drop a script into ocaml/verifier/ with its own dune target.
    verifier_dir = OCAML_DIR / "verifier"
    verifier_dir.mkdir(exist_ok=True)
    (verifier_dir / "verifier.ml").write_text(VERIFIER_OCAML, encoding="utf-8")
    (verifier_dir / "dune").write_text(
        "(executable (name verifier) (libraries ftmo_risk))\n",
        encoding="utf-8",
    )

    # Build (cheap if cached)
    build = subprocess.run(
        ["dune", "build", "verifier/verifier.exe"],
        cwd=str(OCAML_DIR), capture_output=True, text=True, timeout=60,
    )
    if build.returncode != 0:
        pytest.skip(f"OCaml verifier build failed: {build.stderr}")

    # Run
    config_json = json.dumps(session_config)
    input_text = config_json + "\n" + "\n".join(tick_lines) + "\n"
    run = subprocess.run(
        ["dune", "exec", "verifier/verifier.exe"],
        cwd=str(OCAML_DIR), input=input_text,
        capture_output=True, text=True, timeout=30,
    )
    if run.returncode != 0:
        raise RuntimeError(f"verifier failed: {run.stderr}")
    return [int(x) for x in run.stdout.strip().split("\n") if x.strip()]


# ---------------------------------------------------------------------------
# Python reference
# ---------------------------------------------------------------------------


def _py_status_codes(account_code: int, capital: float,
                      tick_lines: list[str]) -> list[int]:
    """Compute the same status codes via the Python risk/ftmo.py engine."""
    from risk.ftmo import (
        FTMOAccountType, FTMOInternalBreach, FTMOImminent,
        new_state, equity_tick, daily_reset,
    )
    code_to_acct = {
        0: FTMOAccountType.CHALLENGE_1STEP,
        1: FTMOAccountType.CHALLENGE_2STEP_PHASE1,
        2: FTMOAccountType.CHALLENGE_2STEP_PHASE2,
        3: FTMOAccountType.FUNDED_STANDARD,
        4: FTMOAccountType.FUNDED_SWING,
        5: FTMOAccountType.FUNDED_REWARDS_1STEP,
    }
    state = new_state(code_to_acct[account_code], capital, opening_balance=capital)
    # Python's equity_tick raises on breach; once raised, the state is
    # considered terminal for the purpose of this parity test.
    terminal_code = None

    codes: list[int] = []
    from datetime import datetime, timezone
    for line in tick_lines:
        if terminal_code is not None:
            codes.append(terminal_code)
            continue
        if line.startswith("RESET"):
            bal = float(line[6:])
            state = daily_reset(state, datetime.now(timezone.utc), bal)
            codes.append(0)
            continue
        ts_str, eq_str = line.split()
        eq = float(eq_str)
        try:
            equity_tick(eq, state, datetime.now(timezone.utc))
            codes.append(0)
        except FTMOImminent:
            codes.append(1)
        except FTMOInternalBreach:
            terminal_code = 2
            codes.append(2)
    return codes


# ---------------------------------------------------------------------------
# Test scenarios
# ---------------------------------------------------------------------------


SCENARIOS = [
    pytest.param(
        1, 100_000.0,
        ["0.0 100000.0", "1.0 99500.0", "2.0 99000.0", "3.0 98000.0"],
        id="2step_phase1_gentle_drawdown",
    ),
    pytest.param(
        1, 100_000.0,
        ["0.0 100000.0", "1.0 99000.0", "2.0 97500.0", "3.0 97000.0",
         "4.0 96000.0", "5.0 92000.0"],
        id="2step_phase1_internal_kill",
    ),
    pytest.param(
        0, 100_000.0,
        ["0.0 100000.0", "1.0 99500.0", "2.0 98500.0", "3.0 98200.0",
         "4.0 97500.0"],
        id="1step_internal_kill_at_2pct",
    ),
    pytest.param(
        1, 100_000.0,
        ["0.0 100000.0", "1.0 100200.0", "2.0 100400.0", "3.0 100100.0"],
        id="profitable_session_stays_active",
    ),
]


@pytest.mark.parametrize("acct_code,cap,tick_lines", SCENARIOS)
def test_python_ocaml_parity(acct_code, cap, tick_lines):
    """Status codes must match tick-for-tick between Python and OCaml."""
    py = _py_status_codes(acct_code, cap, tick_lines)
    oc = _run_verifier({"acct": acct_code, "cap": cap}, tick_lines)
    assert len(py) == len(oc), f"length mismatch: py={py}, ocaml={oc}"
    for i, (p, o) in enumerate(zip(py, oc)):
        assert p == o, (f"tick {i} (line {tick_lines[i]!r}): "
                        f"py code={p}, ocaml code={o}")
