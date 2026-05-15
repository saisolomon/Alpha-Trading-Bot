# `mql5/` -- the live trading EA

The Expert Advisor that runs inside MT5 to actually execute trades. By design
this layer is THIN -- all math goes through `libquant.dll` (built from
`../cpp/`), all risk decisions go through `libftmorisk.dll` (built from
`../ocaml/`).

## What's here

```
mql5/
├── Experts/
│   └── FTMOBot.mq5            -- main EA (OnInit / OnDeinit / OnTick)
├── Include/
│   ├── QuantLib.mqh           -- DLL imports for libquant
│   └── FTMORisk.mqh           -- DLL imports for libftmorisk
└── Files/
    └── (.onnx models go here at deploy time)
```

The MT5 terminal expects files in specific directories under
`<terminal_data_folder>/MQL5/`. To deploy:

1. Find your terminal data folder:
   ```
   File menu -> Open Data Folder -> MQL5/
   ```

2. Copy this tree there:
   ```
   <terminal_data>/MQL5/Experts/FTMOBot.mq5
   <terminal_data>/MQL5/Include/QuantLib.mqh
   <terminal_data>/MQL5/Include/FTMORisk.mqh
   <terminal_data>/MQL5/Libraries/libquant.dll       (from ../cpp/build/Release/)
   <terminal_data>/MQL5/Libraries/libftmorisk.dll    (from ../ocaml/_build/...)
   <terminal_data>/MQL5/Files/<your_model>.onnx      (from Python training)
   ```

3. In MetaEditor (open via terminal Tools > MetaQuotes Language Editor):
   - Open `Experts/FTMOBot.mq5`
   - F7 to compile
   - In MT5 terminal, drag `FTMOBot` from the Navigator onto a chart
   - Enable "AutoTrading" (the green button in the toolbar)

## Permission requirements

For DLL imports to work you must enable them per-EA:

1. In MT5: Tools > Options > Expert Advisors
2. Check "Allow DLL imports" (with proper warnings about untrusted code)

DLLs you write and compile yourself are safe; the warning exists to prevent
loading hostile broker-distributed DLLs.

## Current status

This is **scaffolding only**. The EA file has the right structure
(OnInit/OnDeinit/OnTick) and the include headers declare the DLL imports,
but no actual trading logic is wired up yet. Phase 6 of the build plan
(see ../ARCHITECTURE.md) implements the live trading behavior.

## Editing without MT5

You can edit `.mq5` and `.mqh` files in any text editor (VS Code has a
syntax-highlighting extension). The MetaEditor compiler (`metaeditor64.exe
/compile:...`) is only needed to produce the `.ex5` binary that MT5 actually
runs.
