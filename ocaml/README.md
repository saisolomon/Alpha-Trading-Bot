# `ocaml/libftmorisk` -- type-safe FTMO risk state machine

The bright-line FTMO rules (CLAUDE.md sec.3) live here. Variant types make
invalid account states unrepresentable. Property tests via `qcheck` mechanically
prove invariants like "for any sequence of equity ticks, equity never crosses
the daily-loss line without an internal kill firing first."

## Why OCaml for this

Every other layer in the system can fail loudly (Python throws, MQL5 logs).
A bug in the FTMO rule engine fails silently and ends the prop account. The
right defense is to make the bug impossible to write in the first place:

- **Variant types**: An account state is one of `{ Active | InternalKilled |
  FtmoFailed }`. There is no representation in which all three are true.
  Pattern-matching on the type forces every case to be handled.
- **Records with private constructors**: Equity, balance, P&L are wrapped in
  abstract types. You cannot accidentally pass a daily-loss number where an
  account-balance number is expected.
- **Property tests via qcheck**: Generators produce arbitrary sequences of
  ticks; the invariant "no FTMO line is crossed without internal kill firing"
  is checked across thousands of generated histories per CI run.

For a single-account demo bot this is overkill. For a system whose failure
mode is "lose all the prop capital in one tick" it's the right tradeoff.

## What's here

```
ocaml/
├── dune-project              -- top-level dune config
├── lib/                      -- the rule engine library
│   ├── dune
│   ├── ftmo_rules.ml         -- state machine + transitions
│   ├── ftmo_rules.mli        -- public interface
│   └── c_stubs.ml            -- thin C-interface wrappers (later phase)
├── tests/                    -- qcheck property tests
│   ├── dune
│   └── test_properties.ml
└── bin/                      -- CLI for ad-hoc testing
    ├── dune
    └── main.ml
```

## Build prerequisites (Windows)

Install once:

1. **Install opam (OCaml package manager) for Windows.**
   The native Windows installer is at <https://opam.ocaml.org/doc/Install.html>
   (look for the "Windows" section -- there is now a native MSYS2-based installer
   that doesn't require WSL).

2. **Initialize opam and install the toolchain:**
   ```powershell
   opam init -a
   opam switch create 5.1.0
   opam install dune qcheck qcheck-alcotest alcotest
   ```

3. **(For C interface DLL, later phase):**
   ```powershell
   opam install ctypes ctypes-foreign
   ```

## Build commands

From this directory:

```powershell
opam install . --deps-only
dune build
dune test                 # runs qcheck property tests
dune exec bin/main.exe    # runs the CLI demo
```

The DLL build (later phase) will produce `_build/default/lib/libftmorisk.dll`
which MQL5 imports.

## Current status

This is **scaffolding only**. The state machine has the right shape but the
transitions are placeholder `Active`-returning stubs. Phase 5 of the build
plan (see ARCHITECTURE.md) ports the existing Python `risk/ftmo.py` rule
machine into the OCaml types.

The Python side will keep using `risk/ftmo.py` for now. After the OCaml port
lands, the FTMO simulator (`backtest/ftmo_sim.py`) will switch to calling the
OCaml DLL via `ctypes`, providing the same byte-identical-rule guarantee that
libquant provides for math.
