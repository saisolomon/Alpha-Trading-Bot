(** C interface for libftmorisk.dll.

    Exposes the Ftmo_rules state machine through a flat C ABI that mirrors
    cpp/include/quant/c_abi.h's style. MQL5 imports these symbols; Python
    can also call them via ctypes for the FTMO simulator to share the same
    rule logic as the live EA.

    Design:
      * Accounts are represented as opaque integer HANDLES. The OCaml state
        lives in a process-global table; C callers pass the handle in/out.
        This avoids serialising the whole record across the FFI boundary.
      * All functions return an integer status code. 0 = OK, non-zero = error
        (with a human-readable message available via ftmo_last_error).
      * Output values are returned via pointer parameters (caller-allocated). *)

open Ftmo_rules

(* ----- Global state table ----- *)

let next_handle = ref 1
let handles : (int, state ref) Hashtbl.t = Hashtbl.create 16

let alloc_handle (s : state) : int =
  let h = !next_handle in
  incr next_handle;
  Hashtbl.replace handles h (ref s);
  h

let get_handle (h : int) : state ref option =
  Hashtbl.find_opt handles h

let free_handle (h : int) : unit =
  Hashtbl.remove handles h

(* ----- Last error string (caller can fetch it via ftmo_last_error) ----- *)

let last_error : string ref = ref ""

let set_error msg =
  last_error := msg

(* ----- Account type code mapping (must match mql5/Include/FTMORisk.mqh) ----- *)

let account_of_code = function
  | 0 -> Some Challenge_1step
  | 1 -> Some Challenge_2step_phase1
  | 2 -> Some Challenge_2step_phase2
  | 3 -> Some Funded_standard
  | 4 -> Some Funded_swing
  | 5 -> Some Funded_rewards_1step
  | _ -> None

(* ----- Status code mapping (must match the MQL5 .mqh constants) ----- *)

let status_to_code = function
  | Active           -> 0
  | Imminent _       -> 1
  | Internal_killed _ -> 2
  | Ftmo_failed _    -> 3

(* ----- Decision code mapping ----- *)

let decision_to_code = function
  | Allow     -> 0   (* FTMO_DECISION_ALLOW *)
  | Deny _    -> 1   (* FTMO_DECISION_DENY *)
  | Caution _ -> 2   (* FTMO_DECISION_IMMINENT *)

(* ------------------------------------------------------------------------- *)
(* C-callable functions                                                       *)
(*                                                                            *)
(* Registered with the OCaml runtime via Callback.register so they can be    *)
(* invoked from C through the OCaml runtime API (caml_callback). For a true  *)
(* native DLL with extern "C" symbols we'd wrap these in a thin C shim that   *)
(* uses caml_named_value -- that shim is omitted in this scaffolding pass    *)
(* (it goes in a separate Makefile target along with the ocamlmklib step).   *)
(* ------------------------------------------------------------------------- *)

let ftmo_new_account ~account_code ~initial_capital : int =
  match account_of_code account_code with
  | None ->
      set_error (Printf.sprintf "unknown account_code %d" account_code); 0
  | Some account ->
      let s = new_state ~account ~initial_capital in
      alloc_handle s

let ftmo_free_account ~handle : unit =
  free_handle handle

let ftmo_apply_tick ~handle ~unix_ts ~equity : int =
  match get_handle handle with
  | None ->
      set_error (Printf.sprintf "invalid handle %d" handle); -1
  | Some s_ref ->
      let t = { unix_ts; equity = usd_of_float equity } in
      let s' = apply_tick !s_ref t in
      s_ref := s';
      status_to_code s'.status

let ftmo_check_pretrade ~handle ~equity ~worst_case_loss : int =
  match get_handle handle with
  | None ->
      set_error (Printf.sprintf "invalid handle %d" handle); -1
  | Some s_ref ->
      let order = {
        symbol = "";
        worst_case_loss = usd_of_float worst_case_loss;
        expected_pnl = usd_of_float 0.0;
      } in
      let decision = headroom_check !s_ref
                       ~equity:(usd_of_float equity) ~order in
      decision_to_code decision

let ftmo_daily_reset ~handle ~unix_ts ~balance : int =
  match get_handle handle with
  | None ->
      set_error (Printf.sprintf "invalid handle %d" handle); -1
  | Some s_ref ->
      let s' = daily_reset !s_ref ~at_ts:unix_ts ~balance in
      s_ref := s';
      0

let ftmo_status ~handle : int =
  match get_handle handle with
  | None -> -1
  | Some s_ref -> status_to_code !s_ref.status

let ftmo_last_error_text () : string =
  !last_error

(* Register the entry points so a C shim can call them via caml_callback.
   The string keys here are how C looks them up; they must match the names
   the C shim uses in caml_named_value(). *)

let () =
  Callback.register "ftmo_new_account"
    (fun (account_code, initial_capital) ->
       ftmo_new_account ~account_code ~initial_capital);
  Callback.register "ftmo_free_account"
    (fun handle -> ftmo_free_account ~handle);
  Callback.register "ftmo_apply_tick"
    (fun (handle, unix_ts, equity) ->
       ftmo_apply_tick ~handle ~unix_ts ~equity);
  Callback.register "ftmo_check_pretrade"
    (fun (handle, equity, worst_case_loss) ->
       ftmo_check_pretrade ~handle ~equity ~worst_case_loss);
  Callback.register "ftmo_daily_reset"
    (fun (handle, unix_ts, balance) ->
       ftmo_daily_reset ~handle ~unix_ts ~balance);
  Callback.register "ftmo_status"
    (fun handle -> ftmo_status ~handle);
  Callback.register "ftmo_last_error_text"
    (fun () -> ftmo_last_error_text ())
