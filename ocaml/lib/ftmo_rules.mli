(** Production-faithful port of risk/ftmo.py.

    OCaml's variant types and pattern matching make whole categories of bug
    unrepresentable -- exactly the level of correctness FTMO's bright-line
    rules deserve (CLAUDE.md sec.3).

    All monetary values are in account currency; all percentages are stored
    as fractions (0.05 = 5%). *)

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

val account_type_to_string : account_type -> string
val account_type_of_string : string -> account_type option

(** [true] iff Best Day rule applies (1-Step variants only). *)
val best_day_rule_applies : account_type -> bool

(** [true] iff max-loss line is the trailing-up Funded-Rewards variant. *)
val max_loss_is_trailing : account_type -> bool

(* ------------------------------------------------------------------------- *)
(* Money type (abstract -- can't be confused with raw float)                  *)
(* ------------------------------------------------------------------------- *)

type usd
val usd_of_float : float -> usd
val usd_to_float : usd -> float

(* ------------------------------------------------------------------------- *)
(* Rule parameters                                                            *)
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

val rules_for : account_type -> rules

(* ------------------------------------------------------------------------- *)
(* Account status (variant: always exactly one of these)                      *)
(* ------------------------------------------------------------------------- *)

type breach_kind =
  | Daily_internal
  | Max_internal
  | Daily_ftmo
  | Max_ftmo

val breach_kind_to_string : breach_kind -> string

type account_status =
  | Active
  | Imminent of { line : breach_kind; equity : usd }
  | Internal_killed of { kind : breach_kind; equity : usd; at_ts : float }
  | Ftmo_failed of { kind : breach_kind; equity : usd; at_ts : float }

(* ------------------------------------------------------------------------- *)
(* Live state                                                                 *)
(* ------------------------------------------------------------------------- *)

type state = {
  account              : account_type;
  initial_capital      : usd;
  daily_anchor_balance : usd;  (** account balance at last Prague midnight *)
  highest_eod_balance  : usd;  (** for Funded Rewards trailing max *)
  today_closed_pnl     : usd;  (** for Best Day *)
  sum_profitable_pnl   : usd;  (** for Best Day *)
  status               : account_status;
}

(** Build a fresh state for a new session. *)
val new_state : account:account_type -> initial_capital:float -> state

(* ------------------------------------------------------------------------- *)
(* Derived limits (account currency)                                          *)
(* ------------------------------------------------------------------------- *)

val ftmo_daily_limit         : state -> usd
val ftmo_max_loss_limit      : state -> usd
val internal_daily_kill_line : state -> usd
val internal_max_kill_line   : state -> usd

(* ------------------------------------------------------------------------- *)
(* Pre-trade headroom gate                                                    *)
(* ------------------------------------------------------------------------- *)

type intended_order = {
  symbol           : string;
  worst_case_loss  : usd;       (** absolute amount; max loss on this trade *)
  expected_pnl     : usd;       (** for Best Day projection (optimistic upside) *)
}

type headroom_decision =
  | Allow
  | Deny    of { rule : string; detail : string }
  | Caution of { rule : string; detail : string }
  (** Caution = order may proceed at reduced sizing per CLAUDE.md sec.3. *)

(** Check an intended order against ALL FTMO + internal + Best Day rules. *)
val headroom_check :
  state -> equity:usd -> order:intended_order -> headroom_decision

(* ------------------------------------------------------------------------- *)
(* Equity tick (sub-second monitor)                                           *)
(* ------------------------------------------------------------------------- *)

type tick = {
  unix_ts : float;
  equity  : usd;
}

(** Apply one equity tick. Returns the new state with status updated.

    Priority order (the higher takes precedence):
      FTMO max-loss line   > FTMO daily-loss line
      Internal max kill    > Internal daily kill
      FTMO line            > Internal line     (the failure is what matters)
      Internal kill        > Imminent warning
      Imminent             > Active

    Invariants (mechanically tested by qcheck):
      - Status NEVER regresses from any killed/failed state back to Active.
      - For any monotonic equity drop, status monotonically worsens.
      - FTMO-line crossing always produces Ftmo_failed (never just Internal). *)
val apply_tick : state -> tick -> state

(* ------------------------------------------------------------------------- *)
(* Daily reset (Prague midnight)                                              *)
(* ------------------------------------------------------------------------- *)

(** Recompute daily anchors. Caller is responsible for triggering this at
    00:00 Europe/Prague. The old day's closed P&L rolls into the Best Day
    running sum (if positive). *)
val daily_reset :
  state ->
  at_ts:float ->
  balance:float ->
  state

(* ------------------------------------------------------------------------- *)
(* Best Day ratio (1-Step only)                                               *)
(* ------------------------------------------------------------------------- *)

(** Current ratio = today_pnl / sum_profitable. Returns 0 if not 1-Step
    or if no profitable days yet. *)
val best_day_ratio : ?projected_pnl:float -> state -> float
