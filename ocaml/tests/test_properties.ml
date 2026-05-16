(** Property tests for the production-faithful FTMO rule state machine.

    The invariants checked here are the bright-line guarantees we want
    *mechanically true* for any sequence of equity ticks, not just
    example-based unit tests. Each `Test.make ... ~count:N` runs N
    independent random scenarios per CI run. *)

open Ftmo_rules

(* ------------------------------------------------------------------------- *)
(* Generators                                                                 *)
(* ------------------------------------------------------------------------- *)

let gen_account : account_type QCheck.arbitrary =
  QCheck.oneof_list [
    Challenge_1step;
    Challenge_2step_phase1;
    Challenge_2step_phase2;
    Funded_standard;
    Funded_swing;
    Funded_rewards_1step;
  ]

let gen_tick ~initial_capital : tick QCheck.arbitrary =
  let open QCheck in
  map
    (fun (ts, frac) ->
      { unix_ts = float_of_int ts;
        equity = usd_of_float (initial_capital *. (1.0 +. frac)) })
    (pair nat_small (float_range (-0.30) 0.30))

let gen_tick_sequence ~initial_capital : tick list QCheck.arbitrary =
  QCheck.list_size (QCheck.Gen.int_range 1 200)
    (gen_tick ~initial_capital)

(* ------------------------------------------------------------------------- *)
(* Helpers                                                                    *)
(* ------------------------------------------------------------------------- *)

let initial = new_state ~account:Challenge_2step_phase1 ~initial_capital:100_000.0

let severity = function
  | Active -> 0
  | Imminent _ -> 1
  | Internal_killed _ -> 2
  | Ftmo_failed _ -> 3

(* ------------------------------------------------------------------------- *)
(* Properties                                                                 *)
(* ------------------------------------------------------------------------- *)

(** P1: Once Ftmo_failed, the state stays Ftmo_failed (never reverts). *)
let prop_failure_is_terminal =
  QCheck.Test.make
    ~name:"Ftmo_failed is terminal across any tick sequence"
    ~count:1000
    (gen_tick_sequence ~initial_capital:100_000.0)
    (fun ticks ->
      let intermediate_failed = ref false in
      let final = List.fold_left
        (fun s t ->
          let s' = apply_tick s t in
          (match s'.status with
           | Ftmo_failed _ -> intermediate_failed := true
           | _ -> ());
          s')
        initial ticks
      in
      if !intermediate_failed then
        match final.status with
        | Ftmo_failed _ -> true
        | _ -> false
      else true)

(** P2: Internal_killed is terminal too (mirrors P1). *)
let prop_internal_kill_is_terminal =
  QCheck.Test.make
    ~name:"Internal_killed is terminal across any tick sequence"
    ~count:1000
    (gen_tick_sequence ~initial_capital:100_000.0)
    (fun ticks ->
      let intermediate_internal = ref false in
      let final = List.fold_left
        (fun s t ->
          let s' = apply_tick s t in
          (match s'.status with
           | Internal_killed _ -> intermediate_internal := true
           | _ -> ());
          s')
        initial ticks
      in
      if !intermediate_internal then
        match final.status with
        | Internal_killed _ | Ftmo_failed _ -> true
        | _ -> false
      else true)

(** P3: Internal kill lines sit at-or-above the corresponding FTMO line.

    This is the safety margin the bot operates inside. If this property
    fails, the internal kill cannot fire BEFORE the FTMO line crosses,
    which means the architecture is broken. *)
let prop_internal_lines_at_or_above_ftmo_lines =
  QCheck.Test.make
    ~name:"internal lines >= FTMO lines for every account type"
    ~count:200
    gen_account
    (fun acct ->
      let s = new_state ~account:acct ~initial_capital:100_000.0 in
      let id = usd_to_float (internal_daily_kill_line s) in
      let fd = usd_to_float (ftmo_daily_limit s) in
      let im = usd_to_float (internal_max_kill_line s) in
      let fm = usd_to_float (ftmo_max_loss_limit s) in
      id >= fd && im > fm)

(** P4: For two equity values from the same starting state, the smaller
    equity must produce an at-least-as-severe status. *)
let prop_apply_tick_monotone_in_equity =
  let open QCheck in
  Test.make
    ~name:"apply_tick: smaller equity -> at-least-as-severe status"
    ~count:500
    (pair (float_range (-0.25) 0.25) (float_range (-0.25) 0.25))
    (fun (frac_a, frac_b) ->
      let cap = usd_to_float initial.initial_capital in
      let smaller = cap *. (1.0 +. min frac_a frac_b) in
      let larger = cap *. (1.0 +. max frac_a frac_b) in
      let s_small = apply_tick initial
        { unix_ts = 0.0; equity = usd_of_float smaller } in
      let s_large = apply_tick initial
        { unix_ts = 0.0; equity = usd_of_float larger } in
      severity s_small.status >= severity s_large.status)

(** P5: headroom_check is deterministic and conservative.
    An order that would push equity below the internal daily kill MUST
    be denied; an order that leaves equity well above all lines MUST be
    allowed. *)
let prop_headroom_kills_obviously_bad_orders =
  let open QCheck in
  Test.make
    ~name:"headroom_check denies orders that breach internal daily kill"
    ~count:200
    (float_range 0.05 0.15)
    (fun excess_loss_frac ->
      let cap = usd_to_float initial.initial_capital in
      let equity = initial.initial_capital in
      let r = rules_for initial.account in
      (* worst_case_loss large enough to cross BOTH internal daily AND ftmo daily *)
      let loss = (r.internal_daily_kill_pct +. excess_loss_frac) *. cap in
      let order = {
        symbol = "TEST";
        worst_case_loss = usd_of_float loss;
        expected_pnl = usd_of_float 0.0;
      } in
      match headroom_check initial ~equity ~order with
      | Deny _ -> true
      | _ -> false)

let prop_headroom_allows_obviously_safe_orders =
  let open QCheck in
  Test.make
    ~name:"headroom_check allows tiny orders well within all limits"
    ~count:200
    (float_range 0.0001 0.005)
    (fun tiny_loss_frac ->
      let cap = usd_to_float initial.initial_capital in
      let equity = initial.initial_capital in
      let order = {
        symbol = "TEST";
        worst_case_loss = usd_of_float (tiny_loss_frac *. cap);
        expected_pnl = usd_of_float 0.0;
      } in
      match headroom_check initial ~equity ~order with
      | Allow -> true
      | _ -> false)

(** P6: daily_reset preserves total state semantics. After reset, the
    daily anchor moves to the supplied balance and the today P&L zeros out;
    Best Day rolling sum increases iff today_closed_pnl was positive. *)
let prop_daily_reset_rolls_best_day_correctly =
  let open QCheck in
  Test.make
    ~name:"daily_reset rolls today_closed_pnl into sum iff positive"
    ~count:200
    (float_range (-1000.0) 5000.0)
    (fun today_pnl ->
      let s = { initial with today_closed_pnl = usd_of_float today_pnl } in
      let s' = daily_reset s ~at_ts:0.0 ~balance:100_500.0 in
      let before_sum = usd_to_float s.sum_profitable_pnl in
      let after_sum = usd_to_float s'.sum_profitable_pnl in
      let expected_delta = if today_pnl > 0.0 then today_pnl else 0.0 in
      let delta = after_sum -. before_sum in
      (* Allow tiny floating-point slop *)
      abs_float (delta -. expected_delta) < 1e-6
      && usd_to_float s'.today_closed_pnl = 0.0)

(* ------------------------------------------------------------------------- *)
(* Runner                                                                     *)
(* ------------------------------------------------------------------------- *)

let labelled_tests = [
  "failure_is_terminal",                       prop_failure_is_terminal;
  "internal_kill_is_terminal",                 prop_internal_kill_is_terminal;
  "internal_lines_at_or_above_ftmo_lines",     prop_internal_lines_at_or_above_ftmo_lines;
  "apply_tick_monotone_in_equity",             prop_apply_tick_monotone_in_equity;
  "headroom_denies_bad_orders",                prop_headroom_kills_obviously_bad_orders;
  "headroom_allows_safe_orders",               prop_headroom_allows_obviously_safe_orders;
  "daily_reset_best_day_correct",              prop_daily_reset_rolls_best_day_correctly;
]

let () =
  let failures = ref 0 in
  List.iter (fun (name, test) ->
    try
      QCheck.Test.check_exn test;
      Printf.printf "[PASS] %s\n" name
    with
    | QCheck.Test.Test_fail (_, msgs) ->
        incr failures;
        Printf.printf "[FAIL] %s\n" name;
        List.iter (fun m -> Printf.printf "  %s\n" m) msgs
    | e ->
        incr failures;
        Printf.printf "[ERROR] %s: %s\n" name (Printexc.to_string e)
  ) labelled_tests;
  Printf.printf "---\nRan %d tests, %d failed\n"
    (List.length labelled_tests) !failures;
  exit (if !failures = 0 then 0 else 1)
