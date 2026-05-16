(** Production-faithful port of risk/ftmo.py.

    See ftmo_rules.mli for the public interface. This file ports the rule
    logic; correctness is mechanically established by qcheck property tests
    in ../tests/test_properties.ml. *)

(* ------------------------------------------------------------------------- *)
(* Account types                                                              *)
(* ------------------------------------------------------------------------- *)

type account_type =
  | Challenge_1step
  | Challenge_2step_phase1
  | Challenge_2step_phase2
  | Funded_standard
  | Funded_swing
  | Funded_rewards_1step

let account_type_to_string = function
  | Challenge_1step        -> "CHALLENGE_1STEP"
  | Challenge_2step_phase1 -> "CHALLENGE_2STEP_PHASE1"
  | Challenge_2step_phase2 -> "CHALLENGE_2STEP_PHASE2"
  | Funded_standard        -> "FUNDED_STANDARD"
  | Funded_swing           -> "FUNDED_SWING"
  | Funded_rewards_1step   -> "FUNDED_REWARDS_1STEP"

let account_type_of_string = function
  | "CHALLENGE_1STEP"        -> Some Challenge_1step
  | "CHALLENGE_2STEP_PHASE1" -> Some Challenge_2step_phase1
  | "CHALLENGE_2STEP_PHASE2" -> Some Challenge_2step_phase2
  | "FUNDED_STANDARD"        -> Some Funded_standard
  | "FUNDED_SWING"           -> Some Funded_swing
  | "FUNDED_REWARDS_1STEP"   -> Some Funded_rewards_1step
  | _                        -> None

let best_day_rule_applies = function
  | Challenge_1step | Funded_rewards_1step -> true
  | _ -> false

let max_loss_is_trailing = function
  | Funded_rewards_1step -> true
  | _ -> false

(* ------------------------------------------------------------------------- *)
(* Money type                                                                 *)
(*                                                                            *)
(* Wrapped variant prevents OCaml 5.x unboxed-records-of-floats from making  *)
(* records whose all-float layout doesn't match the abstract .mli type.       *)
(* ------------------------------------------------------------------------- *)

type usd = U of float
let usd_of_float x = U x
let usd_to_float (U x) = x

let[@warning "-32"] ( +@ ) (U a) (U b) = U (a +. b)
let ( -@ ) (U a) (U b) = U (a -. b)
let ( *@ ) k (U a) = U (k *. a)
let ( <@ ) (U a) (U b) = a < b
let ( <=@ ) (U a) (U b) = a <= b

(* ------------------------------------------------------------------------- *)
(* Rules table                                                                *)
(* ------------------------------------------------------------------------- *)

type rules = {
  ftmo_daily_loss_pct      : float;
  ftmo_max_loss_pct        : float;
  internal_daily_kill_pct  : float;
  internal_max_kill_pct    : float;
  profit_target_pct        : float;
  headroom_buffer_pct      : float;
  imminent_buffer_pct      : float;
  best_day_throttle_ratio  : float;
}

let rules_for = function
  | Challenge_1step -> {
      ftmo_daily_loss_pct     = 0.03;
      ftmo_max_loss_pct       = 0.10;
      internal_daily_kill_pct = 0.02;
      internal_max_kill_pct   = 0.07;
      profit_target_pct       = 0.10;
      headroom_buffer_pct     = 0.01;
      imminent_buffer_pct     = 0.005;
      best_day_throttle_ratio = 0.40;
    }
  | Challenge_2step_phase1 -> {
      ftmo_daily_loss_pct     = 0.05;
      ftmo_max_loss_pct       = 0.10;
      internal_daily_kill_pct = 0.03;
      internal_max_kill_pct   = 0.07;
      profit_target_pct       = 0.10;
      headroom_buffer_pct     = 0.01;
      imminent_buffer_pct     = 0.005;
      best_day_throttle_ratio = 0.40;
    }
  | Challenge_2step_phase2 -> {
      ftmo_daily_loss_pct     = 0.05;
      ftmo_max_loss_pct       = 0.10;
      internal_daily_kill_pct = 0.03;
      internal_max_kill_pct   = 0.07;
      profit_target_pct       = 0.05;
      headroom_buffer_pct     = 0.01;
      imminent_buffer_pct     = 0.005;
      best_day_throttle_ratio = 0.40;
    }
  | Funded_standard | Funded_swing -> {
      ftmo_daily_loss_pct     = 0.05;
      ftmo_max_loss_pct       = 0.10;
      internal_daily_kill_pct = 0.03;
      internal_max_kill_pct   = 0.07;
      profit_target_pct       = 0.0;
      headroom_buffer_pct     = 0.01;
      imminent_buffer_pct     = 0.005;
      best_day_throttle_ratio = 0.40;
    }
  | Funded_rewards_1step -> {
      ftmo_daily_loss_pct     = 0.03;
      ftmo_max_loss_pct       = 0.10;
      internal_daily_kill_pct = 0.02;
      internal_max_kill_pct   = 0.07;
      profit_target_pct       = 0.0;
      headroom_buffer_pct     = 0.01;
      imminent_buffer_pct     = 0.005;
      best_day_throttle_ratio = 0.40;
    }

(* ------------------------------------------------------------------------- *)
(* Status variant                                                             *)
(* ------------------------------------------------------------------------- *)

type breach_kind =
  | Daily_internal
  | Max_internal
  | Daily_ftmo
  | Max_ftmo

let breach_kind_to_string = function
  | Daily_internal -> "daily_internal"
  | Max_internal   -> "max_internal"
  | Daily_ftmo     -> "daily_ftmo"
  | Max_ftmo       -> "max_ftmo"

type account_status =
  | Active
  | Imminent of { line : breach_kind; equity : usd }
  | Internal_killed of { kind : breach_kind; equity : usd; at_ts : float }
  | Ftmo_failed of { kind : breach_kind; equity : usd; at_ts : float }

(* Total ordering of statuses by severity (used for the monotonicity invariant). *)
let _status_severity = function
  | Active -> 0
  | Imminent _ -> 1
  | Internal_killed _ -> 2
  | Ftmo_failed _ -> 3

(* ------------------------------------------------------------------------- *)
(* State                                                                      *)
(* ------------------------------------------------------------------------- *)

type state = {
  account              : account_type;
  initial_capital      : usd;
  daily_anchor_balance : usd;
  highest_eod_balance  : usd;
  today_closed_pnl     : usd;
  sum_profitable_pnl   : usd;
  status               : account_status;
}

let new_state ~account ~initial_capital =
  let cap = usd_of_float initial_capital in
  {
    account;
    initial_capital = cap;
    daily_anchor_balance = cap;
    highest_eod_balance = cap;
    today_closed_pnl = usd_of_float 0.0;
    sum_profitable_pnl = usd_of_float 0.0;
    status = Active;
  }

(* ------------------------------------------------------------------------- *)
(* Derived limits                                                             *)
(* ------------------------------------------------------------------------- *)

let ftmo_daily_limit (s : state) : usd =
  let r = rules_for s.account in
  s.daily_anchor_balance -@ (r.ftmo_daily_loss_pct *@ s.initial_capital)

let ftmo_max_loss_limit (s : state) : usd =
  let r = rules_for s.account in
  let floor_base =
    if max_loss_is_trailing s.account then
      let (U h) = s.highest_eod_balance and (U c) = s.initial_capital in
      usd_of_float (max h c)
    else
      s.initial_capital
  in
  floor_base -@ (r.ftmo_max_loss_pct *@ s.initial_capital)

let internal_daily_kill_line (s : state) : usd =
  let r = rules_for s.account in
  s.daily_anchor_balance -@ (r.internal_daily_kill_pct *@ s.initial_capital)

let internal_max_kill_line (s : state) : usd =
  let r = rules_for s.account in
  s.initial_capital -@ (r.internal_max_kill_pct *@ s.initial_capital)

(* ------------------------------------------------------------------------- *)
(* Best Day ratio                                                             *)
(* ------------------------------------------------------------------------- *)

let best_day_ratio ?(projected_pnl=0.0) (s : state) : float =
  if not (best_day_rule_applies s.account) then 0.0
  else
    let today = usd_to_float s.today_closed_pnl +. projected_pnl in
    let denom_base = usd_to_float s.sum_profitable_pnl in
    let denom = if today > 0.0 then denom_base +. today else denom_base in
    if denom <= 0.0 then 0.0
    else today /. denom

(* ------------------------------------------------------------------------- *)
(* Headroom check                                                             *)
(* ------------------------------------------------------------------------- *)

type intended_order = {
  symbol           : string;
  worst_case_loss  : usd;
  expected_pnl     : usd;
}

type headroom_decision =
  | Allow
  | Deny    of { rule : string; detail : string }
  | Caution of { rule : string; detail : string }

let headroom_check (s : state) ~equity ~order : headroom_decision =
  let r = rules_for s.account in
  let worst_case = equity -@ order.worst_case_loss in
  let buffer = r.headroom_buffer_pct *@ s.initial_capital in

  let ftmo_daily = ftmo_daily_limit s in
  let ftmo_max = ftmo_max_loss_limit s in
  let int_daily = internal_daily_kill_line s in
  let int_max = internal_max_kill_line s in

  (* FTMO daily *)
  if worst_case <@ (ftmo_daily +@ buffer) then
    Deny { rule = "ftmo_daily";
           detail = Printf.sprintf "worst_case=%.2f within %.2f of FTMO daily %.2f"
             (usd_to_float worst_case) (usd_to_float buffer) (usd_to_float ftmo_daily) }
  (* FTMO max *)
  else if worst_case <@ (ftmo_max +@ buffer) then
    Deny { rule = "ftmo_max";
           detail = Printf.sprintf "worst_case=%.2f within %.2f of FTMO max %.2f"
             (usd_to_float worst_case) (usd_to_float buffer) (usd_to_float ftmo_max) }
  (* Internal daily *)
  else if worst_case <@ int_daily then
    Deny { rule = "internal_daily";
           detail = Printf.sprintf "worst_case=%.2f < internal daily kill %.2f"
             (usd_to_float worst_case) (usd_to_float int_daily) }
  (* Internal max *)
  else if worst_case <@ int_max then
    Deny { rule = "internal_max";
           detail = Printf.sprintf "worst_case=%.2f < internal max kill %.2f"
             (usd_to_float worst_case) (usd_to_float int_max) }
  (* Best Day (1-Step only) *)
  else if best_day_rule_applies s.account then begin
    let projected = usd_to_float order.expected_pnl in
    let ratio = best_day_ratio ~projected_pnl:projected s in
    if ratio > r.best_day_throttle_ratio then
      Deny { rule = "best_day";
             detail = Printf.sprintf "projected best-day ratio=%.3f > throttle=%.3f"
               ratio r.best_day_throttle_ratio }
    else
      Allow
  end
  else Allow

(* ------------------------------------------------------------------------- *)
(* equity_tick / apply_tick                                                   *)
(* ------------------------------------------------------------------------- *)

type tick = {
  unix_ts : float;
  equity  : usd;
}

let apply_tick (s : state) (t : tick) : state =
  (* Once killed/failed, the state is terminal except for the equity field. *)
  match s.status with
  | Internal_killed _ | Ftmo_failed _ ->
      s   (* status frozen, no further transitions *)
  | _ ->
      let r = rules_for s.account in
      let imminent_buf = r.imminent_buffer_pct *@ s.initial_capital in
      let new_eq = t.equity in
      let ftmo_daily = ftmo_daily_limit s in
      let ftmo_max = ftmo_max_loss_limit s in
      let int_daily = internal_daily_kill_line s in
      let int_max = internal_max_kill_line s in

      (* Priority: FTMO max > FTMO daily > internal max > internal daily
                  > imminent max > imminent daily > Active.

         FTMO line crossing always produces Ftmo_failed -- that's the actual
         account failure. Internal kill is what we use to STOP TRADING before
         hitting the FTMO line; if both fire simultaneously, the failure
         wins because that's the real-world state. *)
      let new_status =
        if new_eq <=@ ftmo_max then
          Ftmo_failed { kind = Max_ftmo; equity = new_eq; at_ts = t.unix_ts }
        else if new_eq <=@ ftmo_daily then
          Ftmo_failed { kind = Daily_ftmo; equity = new_eq; at_ts = t.unix_ts }
        else if new_eq <=@ int_max then
          Internal_killed { kind = Max_internal; equity = new_eq; at_ts = t.unix_ts }
        else if new_eq <=@ int_daily then
          Internal_killed { kind = Daily_internal; equity = new_eq; at_ts = t.unix_ts }
        else if new_eq <@ (ftmo_max +@ imminent_buf) then
          Imminent { line = Max_ftmo; equity = new_eq }
        else if new_eq <@ (ftmo_daily +@ imminent_buf) then
          Imminent { line = Daily_ftmo; equity = new_eq }
        else
          Active
      in
      { s with status = new_status }

(* ------------------------------------------------------------------------- *)
(* daily_reset                                                                *)
(* ------------------------------------------------------------------------- *)

let daily_reset (s : state) ~at_ts:_ ~balance : state =
  let new_balance = usd_of_float balance in
  (* Roll today's closed P&L into the Best Day running sum (positive only). *)
  let new_sum =
    if usd_to_float s.today_closed_pnl > 0.0 then
      s.sum_profitable_pnl +@ s.today_closed_pnl
    else
      s.sum_profitable_pnl
  in
  let (U cur_high) = s.highest_eod_balance in
  let new_high = usd_of_float (max cur_high balance) in
  {
    s with
    daily_anchor_balance = new_balance;
    highest_eod_balance = new_high;
    today_closed_pnl = usd_of_float 0.0;
    sum_profitable_pnl = new_sum;
    status = Active;   (* daily reset clears intra-day imminent flags *)
  }
