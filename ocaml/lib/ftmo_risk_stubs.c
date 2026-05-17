/* ftmo_risk_stubs.c
 *
 * C shim that bridges the OCaml ftmo_rules state machine to the C ABI
 * MQL5 imports. Each exported function:
 *   1. Looks up the registered OCaml callback by name (set in c_stubs.ml
 *      via Callback.register)
 *   2. Marshals C args to OCaml values
 *   3. Invokes via caml_callback*
 *   4. Unmarshals the OCaml result back to a C return value
 *
 * On first call we initialise the OCaml runtime with caml_startup.
 *
 * Built as a native OCaml shared library via ocamlmklib. See ../build_dll.ps1.
 *
 * The export macro picks the right calling convention for MT5 imports:
 *   - On Windows we declare __stdcall (MQL5's default for #import)
 *   - On non-Windows we leave it bare cdecl (irrelevant for MQL5 but useful
 *     if anyone wants to load this lib from Linux Python via ctypes)
 */

#include <caml/mlvalues.h>
#include <caml/callback.h>
#include <caml/alloc.h>
#include <caml/memory.h>
#include <caml/threads.h>
#include <caml/fail.h>
#include <caml/misc.h>     /* char_os typedef on Windows */

#include <stdio.h>
#include <stdlib.h>

#ifdef _WIN32
  #include <wchar.h>
  #define FTMO_API __declspec(dllexport)
  /* MQL5 #import expects stdcall by default for ints/doubles. */
  #define FTMO_CALL __stdcall
#else
  #define FTMO_API __attribute__((visibility("default")))
  #define FTMO_CALL
#endif

/* ---------------------------------------------------------------------- */
/* One-time OCaml runtime initialisation                                  */
/* ---------------------------------------------------------------------- */

static int g_ocaml_initialised = 0;

static void ensure_ocaml_init(void) {
    if (g_ocaml_initialised) return;
    /* caml_startup needs a NULL-terminated argv. On Windows the OCaml
       runtime uses wide-char (char_os = wchar_t) strings; on POSIX it's
       plain char. Provide a dummy program name -- it's only used for
       error reporting. */
#ifdef _WIN32
    static char_os *argv[] = { (char_os *)L"libftmorisk", NULL };
#else
    static char_os *argv[] = { (char_os *)"libftmorisk", NULL };
#endif
    caml_startup(argv);
    g_ocaml_initialised = 1;
}

/* Helper: fetch a named callback or fail loudly. */
static value get_callback(const char *name) {
    const value *cb = caml_named_value(name);
    if (cb == NULL) {
        fprintf(stderr, "[libftmorisk] FATAL: callback '%s' not registered\n", name);
        abort();
    }
    return *cb;
}

/* ---------------------------------------------------------------------- */
/* Exported C functions (one per OCaml callback in c_stubs.ml)            */
/* ---------------------------------------------------------------------- */

/* ftmo_new_account(account_code, initial_capital) -> handle (int)        */
FTMO_API long FTMO_CALL ftmo_new_account(int account_code, double initial_capital) {
    ensure_ocaml_init();
    CAMLparam0();
    CAMLlocal2(arg, result);
    arg = caml_alloc_tuple(2);
    Store_field(arg, 0, Val_int(account_code));
    Store_field(arg, 1, caml_copy_double(initial_capital));
    result = caml_callback(get_callback("ftmo_new_account"), arg);
    CAMLreturnT(long, (long)Long_val(result));
}

/* ftmo_free_account(handle)                                              */
FTMO_API void FTMO_CALL ftmo_free_account(long handle) {
    ensure_ocaml_init();
    caml_callback(get_callback("ftmo_free_account"), Val_long(handle));
}

/* ftmo_apply_tick(handle, unix_ts, equity) -> status_code (int)          */
FTMO_API int FTMO_CALL ftmo_apply_tick(long handle, double unix_ts, double equity) {
    ensure_ocaml_init();
    CAMLparam0();
    CAMLlocal2(arg, result);
    arg = caml_alloc_tuple(3);
    Store_field(arg, 0, Val_long(handle));
    Store_field(arg, 1, caml_copy_double(unix_ts));
    Store_field(arg, 2, caml_copy_double(equity));
    result = caml_callback(get_callback("ftmo_apply_tick"), arg);
    CAMLreturnT(int, Int_val(result));
}

/* ftmo_check_pretrade(handle, equity, worst_case_loss) -> decision (int) */
FTMO_API int FTMO_CALL ftmo_check_pretrade(long handle, double equity, double worst_case_loss) {
    ensure_ocaml_init();
    CAMLparam0();
    CAMLlocal2(arg, result);
    arg = caml_alloc_tuple(3);
    Store_field(arg, 0, Val_long(handle));
    Store_field(arg, 1, caml_copy_double(equity));
    Store_field(arg, 2, caml_copy_double(worst_case_loss));
    result = caml_callback(get_callback("ftmo_check_pretrade"), arg);
    CAMLreturnT(int, Int_val(result));
}

/* ftmo_daily_reset(handle, unix_ts, balance) -> 0                        */
FTMO_API int FTMO_CALL ftmo_daily_reset(long handle, double unix_ts, double balance) {
    ensure_ocaml_init();
    CAMLparam0();
    CAMLlocal2(arg, result);
    arg = caml_alloc_tuple(3);
    Store_field(arg, 0, Val_long(handle));
    Store_field(arg, 1, caml_copy_double(unix_ts));
    Store_field(arg, 2, caml_copy_double(balance));
    result = caml_callback(get_callback("ftmo_daily_reset"), arg);
    CAMLreturnT(int, Int_val(result));
}

/* ftmo_status(handle) -> status_code (int)                                */
FTMO_API int FTMO_CALL ftmo_status(long handle) {
    ensure_ocaml_init();
    value result = caml_callback(get_callback("ftmo_status"), Val_long(handle));
    return Int_val(result);
}
