# Multi-Language Architecture

This repository is organized into four language layers, each chosen for what it
is best at. Strategy logic must NEVER be implemented twice -- a function lives
in exactly one place and the other layers import or call it.

```
ftmo-bot/
├── (Python tree)         RESEARCH layer        backtest, training, analysis
├── cpp/                  HOT-PATH math          C++ DLL, called by Python+MQL5
├── ocaml/                RISK state machine     OCaml DLL, called by MQL5 (and Python)
└── mql5/                 LIVE TRADING           MT5 Expert Advisor
```

## Why each language

### Python -- research and training (CURRENT)

Owns: backtest engine, walk-forward, parameter sweep, plotting, ML training
(PyTorch / scikit-learn / hmmlearn), ONNX export, data caching.

Why Python: the iteration-loop language. Notebooks, pandas, matplotlib, the
whole scientific-Python stack. There is no faster way to research a strategy.

What Python should NOT do: ship to live. The research code is for finding
edge, not for executing it. See "research vs live drift" below.

### C++ -- hot-path math (`cpp/libquant.dll`)

Owns: feature math (ATR, EMA, rolling z-score, log returns), Markov chain
forward step, ONNX runtime calls for model inference, anything that has to be
identical between research and live.

Why C++: it's the only sane way to have ONE implementation that both Python
(via pybind11) and MQL5 (via DLL import) call. Without this, the live MQL5 EA
has to reimplement the math, and any bug in the duplicate implementation is a
silent edge killer.

Performance is a secondary benefit. The primary benefit is **eliminating
research/live drift** -- the same byte-identical code computes a feature in
the backtest and in the live tick handler.

### OCaml -- risk state machine (`ocaml/libftmorisk.dll`)

Owns: FTMO rule engine, kill-switch state machine, headroom check, the things
where a bug means a blown account.

Why OCaml: variant types and pattern matching make whole categories of bugs
*unrepresentable* (cf. CLAUDE.md sec.3 -- FTMO rules are bright-line invariants).
Combined with `qcheck` property-based tests we can mechanically prove
properties like "for any sequence of ticks, equity never crosses an FTMO line
without an internal kill firing first" -- not just test it on examples.

For a single-account bot this is overkill. For a system whose failure mode is
"lose all the prop capital in one tick" it's the right tradeoff.

### MQL5 -- live trading (`mql5/Experts/US500_MeanRev.mq5`)

Owns: the actual EA running inside the MT5 terminal. Order send/modify/cancel,
position management, tick subscription, account info polling.

Why MQL5: it's the only thing FTMO supports. Until we leave FTMO for IBKR +
NautilusTrader (post-Phase-2 milestone), MQL5 is locked in.

What MQL5 should NOT do: anything other than glue. All math goes through
libquant. All risk decisions go through libftmorisk. The MQL5 file is short
on purpose.

## The "research vs live drift" failure mode

This is the failure mode the architecture exists to prevent.

A common pattern in retail quant code:
1. Backtest in Python with a custom `compute_atr()`.
2. Port to MQL5 by hand: write a different `compute_atr()` in MQL5.
3. Live results don't match backtest. Spend weeks finding the off-by-one.
4. Fix it. Six months later tweak the Python version. Forget to port.
5. Live silently diverges from backtest forever.

Our defense: there is only ONE `compute_atr()`, written in C++ in
`cpp/src/features.cpp`. Python calls it via pybind11. MQL5 calls it via
DLL import. They cannot drift because they're the same function.

The corresponding rule for risk: there is only ONE `headroom_check()`, written
in OCaml. The Python backtest calls it via the C interface for the FTMO
simulator. The MQL5 EA calls the same compiled DLL. Same defense.

## Build prerequisites (Windows)

Each subdirectory has its own README with detailed install steps. Summary:

| Layer | Toolchain | Approx install size |
|-------|-----------|---------------------|
| Python | already installed (uv + .venv) | -- |
| C++ | Visual Studio Build Tools 2022 (MSVC), CMake 3.20+ | ~6 GB |
| OCaml | opam (Windows native) + dune | ~1 GB |
| MQL5 | MT5 terminal (already installed) -- has built-in MetaEditor | -- |

You can scaffold and read the code without any of the new toolchains.
You only need them when you want to actually build the DLLs.

## Build flow

```
# 1. Build the C++ library (DLL + Python wheel)
cd cpp
cmake -S . -B build -A x64
cmake --build build --config Release

# 2. Build the OCaml library (DLL)
cd ../ocaml
opam install . --deps-only
dune build

# 3. Compile the MQL5 EA
# Open mql5/Experts/US500_MeanRev.mq5 in MetaEditor, F7 to compile
# Or via command line: metaeditor64.exe /compile:mql5/Experts/US500_MeanRev.mq5

# 4. Deploy
# Copy libquant.dll and libftmorisk.dll to MT5 terminal/MQL5/Libraries/
# Copy any ONNX models to MT5 terminal/MQL5/Files/
# Attach US500_MeanRev to a chart in MT5 -> live
```

Detailed instructions in each subdirectory's README.

## Runtime data flow

Live trading, per tick:

```
MT5 broker tick arrives
       |
       v
MQL5 EA::OnTick()
       |
       |---> libquant.compute_features(prices)   # feature vector
       |     (C++, single source of truth)
       |
       |---> libquant.markov_forecast(state)     # regime probability
       |
       |---> libquant.onnx_infer(model, features)  # LSTM signal (Phase 3+)
       |
       |---> libftmorisk.check_pretrade(account, order)  # OCaml gate
       |     (returns Allow | Deny | Imminent)
       |
       v
   if Allow:
       MQL5 EA::OrderSend(...)
   else:
       MQL5 EA::Log(...)
```

Research, per backtest run:

```
Python pytest
       |
       v
backtest engine
       |
       |---> import quantlib (pybind11 wrapper of cpp/libquant)
       |     # SAME C++ functions as live, byte-identical results
       |
       |---> import ftmo_risk (ctypes wrapper of ocaml/libftmorisk)
       |     # SAME OCaml state machine as live
       |
       v
   metrics, equity curve, walk-forward report
```

## Build phases (per the architecture proposal)

Phase 1 -- Markov regime gate (Python only). 1-2 days.
Phase 2 -- HMM upgrade. 2-3 days.
Phase 3 -- LSTM directional ensemble. 1 week.
Phase 4 -- Port hot-path math to C++ libquant. 2 weeks.
Phase 5 -- Port FTMO rule engine to OCaml libftmorisk. 1-2 weeks.
Phase 6 -- MQL5 EA + 4-week paper trade. 2-3 weeks.

This file documents the **target** architecture. Phases 1-3 stay in pure
Python; Phase 4-6 build out the multi-language stack.

## References

- `Memory.md` -- decisions, learnings, gotchas across the project history.
- `CLAUDE.md` -- core principles, hard rules, FTMO compliance.
- `Planning.md` -- roadmap and milestones.
- `cpp/README.md`, `ocaml/README.md`, `mql5/README.md` -- per-layer details.
