"""
Cross-language parity: OCaml ftmo_rules.ml vs C++ ftmo_rules.cpp.

The MQL5 EA calls the C++ implementation (via libquant.dll). The OCaml
implementation remains the formal spec with qcheck-proven invariants.
This test guarantees the two stay in sync: identical tick sequences
must produce identical status codes.

Mechanism:
  1. Build a list of test tick sequences (a mix of normal trades, deep
     drawdowns, FTMO-line crossings).
  2. For each: run via OCaml CLI (tests/test_ocaml_python_parity.py
     verifier infrastructure) and via the C++ DLL.
  3. Assert the status codes match tick-for-tick.

If the C++ port drifts from the OCaml spec, this test catches it.

Skipped if:
  - OCaml toolchain isn't installed
  - libquant.dll isn't built
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
OCAML_DIR = REPO_ROOT / "ocaml"
DLL_PATH = REPO_ROOT / "cpp" / "build" / "libquant.dll"


def _ocaml_available() -> bool:
    return (
        shutil.which("dune") is not None
        and shutil.which("ocaml") is not None
        and (OCAML_DIR / "_build" / "default" / "lib").exists()
    )


pytestmark = pytest.mark.skipif(
    not _ocaml_available() or not DLL_PATH.exists(),
    reason="Either OCaml toolchain or libquant.dll not available",
)


# ---------------------------------------------------------------------------
# OCaml verifier (reuses the script from test_ocaml_python_parity)
# ---------------------------------------------------------------------------


VERIFIER_OCAML = textwrap.dedent("""\
    open Ftmo_rules

    let parse_acct = function
      | 0 -> Challenge_1step
      | 1 -> Challenge_2step_phase1
      | 2 -> Challenge_2step_phase2
      | 3 -> Funded_standard
      | 4 -> Funded_swing
      | 5 -> Funded_rewards_1step
      | n -> failwith (Printf.sprintf "bad acct %d" n)

    let status_code = function
      | Active -> 0
      | Imminent _ -> 1
      | Internal_killed _ -> 2
      | Ftmo_failed _ -> 3

    let () =
      let line = input_line stdin in
      let acct_code, cap = Scanf.sscanf line {|{"acct": %d, "cap": %f}|}
        (fun a c -> (a, c)) in
      let state = ref (new_state ~account:(parse_acct acct_code)
                         ~initial_capital:cap) in
      try
        while true do
          let l = input_line stdin in
          Scanf.sscanf l "%f %f" (fun ts eq ->
            let t = { unix_ts = ts; equity = usd_of_float eq } in
            state := apply_tick !state t;
            Printf.printf "%d\\n" (status_code !state.status))
        done
      with End_of_file -> ()
""")


def _ocaml_status_codes(acct_code: int, cap: float,
                         ticks: list[tuple[float, float]]) -> list[int]:
    verifier_dir = OCAML_DIR / "verifier"
    verifier_dir.mkdir(exist_ok=True)
    (verifier_dir / "verifier.ml").write_text(VERIFIER_OCAML, encoding="utf-8")
    (verifier_dir / "dune").write_text(
        "(executable (name verifier) (libraries ftmo_risk))\n", encoding="utf-8"
    )
    build = subprocess.run(
        ["dune", "build", "verifier/verifier.exe"],
        cwd=str(OCAML_DIR), capture_output=True, text=True, timeout=60,
    )
    if build.returncode != 0:
        pytest.skip(f"OCaml verifier build failed: {build.stderr}")

    config = json.dumps({"acct": acct_code, "cap": cap})
    tick_lines = "\n".join(f"{ts} {eq}" for ts, eq in ticks)
    input_text = config + "\n" + tick_lines + "\n"
    run = subprocess.run(
        ["dune", "exec", "verifier/verifier.exe"],
        cwd=str(OCAML_DIR), input=input_text,
        capture_output=True, text=True, timeout=30,
    )
    if run.returncode != 0:
        raise RuntimeError(f"verifier failed: {run.stderr}")
    return [int(x) for x in run.stdout.strip().split("\n") if x.strip()]


# ---------------------------------------------------------------------------
# C++ DLL caller
# ---------------------------------------------------------------------------


def _cpp_status_codes(acct_code: int, cap: float,
                       ticks: list[tuple[float, float]]) -> list[int]:
    if sys.platform == "win32":
        gcc = shutil.which("gcc")
        if gcc:
            os.add_dll_directory(str(Path(gcc).parent))
    lib = ctypes.WinDLL(str(DLL_PATH))
    lib.ftmo_new_account.argtypes = [ctypes.c_int, ctypes.c_double]
    lib.ftmo_new_account.restype = ctypes.c_long
    lib.ftmo_free_account.argtypes = [ctypes.c_long]
    lib.ftmo_apply_tick.argtypes = [ctypes.c_long, ctypes.c_double, ctypes.c_double]
    lib.ftmo_apply_tick.restype = ctypes.c_int

    handle = lib.ftmo_new_account(acct_code, cap)
    try:
        return [int(lib.ftmo_apply_tick(handle, ts, eq)) for ts, eq in ticks]
    finally:
        lib.ftmo_free_account(handle)


# ---------------------------------------------------------------------------
# Test scenarios
# ---------------------------------------------------------------------------


SCENARIOS = [
    pytest.param(
        1, 100_000.0,
        [(0.0, 100_000.0), (1.0, 99_500.0), (2.0, 99_000.0), (3.0, 98_000.0)],
        id="phase1_gentle_drawdown",
    ),
    pytest.param(
        1, 100_000.0,
        [(0.0, 100_000.0), (1.0, 99_000.0), (2.0, 97_500.0),
         (3.0, 97_000.0), (4.0, 96_000.0), (5.0, 92_000.0)],
        id="phase1_internal_kill_then_ftmo_fail",
    ),
    pytest.param(
        0, 100_000.0,
        [(0.0, 100_000.0), (1.0, 99_500.0), (2.0, 98_500.0),
         (3.0, 98_200.0), (4.0, 97_500.0)],
        id="1step_tighter_internal_kill",
    ),
    pytest.param(
        1, 100_000.0,
        [(0.0, 100_000.0), (1.0, 100_200.0), (2.0, 100_400.0), (3.0, 100_100.0)],
        id="profitable_session",
    ),
    pytest.param(
        2, 50_000.0,
        [(0.0, 50_000.0), (1.0, 49_000.0), (2.0, 47_500.0), (3.0, 45_000.0)],
        id="phase2_different_capital_scale",
    ),
    pytest.param(
        3, 200_000.0,
        [(0.0, 200_000.0), (1.0, 199_500.0), (2.0, 198_000.0),
         (3.0, 195_000.0), (4.0, 190_000.0)],
        id="funded_standard_drawdown",
    ),
]


@pytest.mark.parametrize("acct_code,cap,ticks", SCENARIOS)
def test_ocaml_cpp_status_codes_match(acct_code, cap, ticks):
    """OCaml and C++ must return identical status codes for every tick."""
    oc = _ocaml_status_codes(acct_code, cap, ticks)
    cp = _cpp_status_codes(acct_code, cap, ticks)
    assert len(oc) == len(cp), f"length mismatch: ocaml={oc}, cpp={cp}"
    for i, (o, c) in enumerate(zip(oc, cp)):
        assert o == c, (f"tick {i} (ts={ticks[i][0]}, eq={ticks[i][1]}): "
                        f"ocaml={o}, cpp={c}")
