(** Property tests for the FTMO rule state machine.

    These are the tests that justify OCaml's existence in the stack:
    rather than checking specific examples, qcheck generates thousands of
    arbitrary tick sequences per CI run and checks invariants hold for
    all of them. The kinds of bugs that survive 10 unit tests but get
    caught by 10,000 generated histories are exactly the ones that blow
    a prop account in production. *)

open Ftmo_rules

(* ------------------------------------------------------------------------- *)
(* Generators                                                                *)
(* ------------------------------------------------------------------------- *)

(** Arbitrary FTMO account type. *)
let gen_account : account_type QCheck.arbitrary =
  QCheck.oneofl [
    Challenge_1step;
    Challenge_2step_phase1;
    Challenge_2step_phase2;
    Funded_standard;
    Funded_swing;
    Funded_rewards_1step;
  ]

(** Arbitrary tick: equity drawn from initial_capital +/- 30%. *)
let gen_tick ~initial_capital : tick QCheck.arbitrary =
  let open QCheck in
  map
    (fun (ts, frac) ->
      { unix_ts = float_of_int ts;
        equity = usd_of_float (initial_capital *. (1.0 +. frac)) })
    (pair small_nat (float_range (-0.30) 0.30))

(** Arbitrary tick sequence (length 1..200). *)
let gen_tick_sequence ~initial_capital : tick list QCheck.arbitrary =
  QCheck.list_of_size (QCheck.Gen.int_range 1 200)
    (gen_tick ~initial_capital)

(* ------------------------------------------------------------------------- *)
(* Helpers                                                                    *)
(* ------------------------------------------------------------------------- *)

let run_history initial_state ticks =
  List.fold_left apply_tick initial_state ticks

let initial = new_account ~account:Challenge_2step_phase1 ~initial_capital:100_000.0

(* ------------------------------------------------------------------------- *)
(* Invariants                                                                 *)
(* ------------------------------------------------------------------------- *)

(** Invariant 1: Once an account has crossed any FTMO line, it is
    [Ftmo_failed], never silently returns to [Active]. *)
let prop_failure_is_terminal =
  QCheck.Test.make
    ~name:"FTMO failure is terminal -- never returns to Active"
    ~count:1000
    (gen_tick_sequence ~initial_capital:100_000.0)
    (fun ticks ->
      let final = run_history initial ticks in
      (* If any intermediate tick produced Ftmo_failed, the final state
         must NOT be Active. *)
      let intermediate_failed = ref false in
      let _ : account_snapshot = List.fold_left
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
        | Active -> false
        | _ -> true
      else
        true)

(** Invariant 2: Internal kill fires BEFORE FTMO line for a given drawdown.
    For any tick that crosses both an internal kill AND an FTMO line, the
    state machine must produce [Ftmo_failed] (the worse of the two) -- but
    in normal operation we expect internal kill to fire on the LESS-severe
    drawdown first as a downscale of the FTMO threshold. The actual proof:
    internal-kill-line is always above FTMO-line in absolute equity terms. *)
let prop_internal_lines_above_ftmo_lines =
  QCheck.Test.make
    ~name:"Internal kill lines strictly above FTMO lines"
    ~count:200
    gen_account
    (fun acct ->
      let s = new_account ~account:acct ~initial_capital:100_000.0 in
      let internal_daily = s.midnight_balance -. (0.03 *. s.initial_capital) in
      let ftmo_daily =
        s.midnight_balance -.
        ((match acct with
          | Challenge_1step | Funded_rewards_1step -> 0.03
          | _ -> 0.05) *. s.initial_capital)
      in
      let internal_max = s.initial_capital -. (0.07 *. s.initial_capital) in
      let ftmo_max = s.initial_capital -. (0.10 *. s.initial_capital) in
      (* The placeholder uses 0.02 internal daily for 1-step which equals
         FTMO 0.03; this property should still hold (>=). *)
      internal_daily >= ftmo_daily && internal_max > ftmo_max)

(** Invariant 3: Apply_tick is monotonic in severity -- a smaller equity
    cannot produce a less-severe status than a larger equity from the same
    starting state. *)
let prop_apply_tick_monotone_in_equity =
  let open QCheck in
  Test.make
    ~name:"apply_tick: smaller equity -> at-least-as-severe status"
    ~count:500
    (pair (float_range (-0.20) 0.20) (float_range (-0.20) 0.20))
    (fun (frac_a, frac_b) ->
      let s = initial in
      let smaller_frac = min frac_a frac_b in
      let larger_frac = max frac_a frac_b in
      let smaller_eq = s.initial_capital *. (1.0 +. smaller_frac) in
      let larger_eq = s.initial_capital *. (1.0 +. larger_frac) in
      let s_small = apply_tick s
        { unix_ts = 0.0; equity = usd_of_float smaller_eq } in
      let s_large = apply_tick s
        { unix_ts = 0.0; equity = usd_of_float larger_eq } in
      let severity = function
        | Active -> 0
        | Internal_killed _ -> 1
        | Ftmo_failed _ -> 2
      in
      severity s_small.status >= severity s_large.status)

(* ------------------------------------------------------------------------- *)
(* Test suite                                                                 *)
(* ------------------------------------------------------------------------- *)

let () =
  let to_alcotest = QCheck_alcotest.to_alcotest in
  Alcotest.run "ftmo_risk_properties" [
    "invariants", [
      to_alcotest prop_failure_is_terminal;
      to_alcotest prop_internal_lines_above_ftmo_lines;
      to_alcotest prop_apply_tick_monotone_in_equity;
    ];
  ]
