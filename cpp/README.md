# `cpp/libquant` -- hot-path math library

Single source of truth for feature math used by both the Python research stack
and the MQL5 live EA. Eliminates research-vs-live drift by construction
(see ../ARCHITECTURE.md).

## What's here

- `include/quant/` -- public headers
- `src/` -- implementations
- `bindings/python_module.cpp` -- pybind11 wrapper (built into a `.pyd` /
  `quantlib` Python module)
- `tests/` -- C++ unit tests + Python parity tests against the existing
  pure-Python implementation

Currently implemented:
- `compute_atr(high, low, close, period)` -- ATR(period) via EWM of true range
- `compute_ema(series, span)` -- exponential moving average
- `compute_rolling_zscore(series, lookback)` -- rolling z-score
- `markov_forecast(transition_matrix, current_state, n_steps)` -- stub

Stubbed for later phases:
- `onnx_infer(model_path, features)` -- ONNX runtime inference (Phase 3)

## Build prerequisites (Windows)

Install once:

1. **Visual Studio Build Tools 2022** (free) -- the "Desktop development with
   C++" workload. About 6 GB.
   <https://visualstudio.microsoft.com/visual-cpp-build-tools/>

2. **CMake 3.20 or newer** -- standalone installer, add to PATH.
   <https://cmake.org/download/>

3. **pybind11** -- pip install in the project venv:
   ```powershell
   uv pip install pybind11
   ```

(ONNX runtime will be added in Phase 3.)

## Build commands

From the repo root:

```powershell
cd cpp
cmake -S . -B build -A x64
cmake --build build --config Release
```

Outputs:
- `build/Release/libquant.dll` -- the C-ABI DLL for MQL5 to import
- `build/Release/quantlib.cp311-win_amd64.pyd` -- the Python module (or
  similar versioned name)

Install the Python module into the venv:

```powershell
copy build\Release\quantlib.cp311-win_amd64.pyd ..\.venv\Lib\site-packages\
```

(Or use `pip install .` in this directory once `setup.py` is added in a
later phase.)

## Parity testing (the whole point)

After building, from the repo root:

```powershell
uv run pytest tests/test_cpp_parity.py -v
```

This compares C++ outputs to the existing pure-Python implementations bar by
bar on cached real data. ANY mismatch beyond a tiny floating-point tolerance
(1e-9 relative) is a build failure -- it means we have research-vs-live drift.

## Where to put new functions

1. Declaration in `include/quant/<topic>.hpp`
2. Implementation in `src/<topic>.cpp`
3. Pybind11 binding in `bindings/python_module.cpp`
4. Parity test in `../tests/test_cpp_parity.py`

The Python wrapper is *only* a wrapper -- no logic in pybind11 layer.
