(** C interface stubs for libftmorisk.dll.

    Phase 5 of the build plan will populate these with `Ctypes.foreign_value`
    bindings so MQL5 can call into the OCaml state machine through a flat C
    ABI (mirrors the libquant pattern in cpp/include/quant/c_abi.h).

    Currently empty -- the .ml + .mli pair is enough to scaffold the type
    shape and qcheck tests; the C interop is layered on later.

    Reference: https://ocaml.org/manual/intfc.html *)
