(** Type-safe FTMO risk-rule state machine.

    Mirrors [risk/ftmo.py] in the Python tree, but uses OCaml's variant types
    and abstract records to make whole categories of bug unrepresentable. *)

(** Account type -- mirrors [risk.ftmo.FTMOAccountType]. *)
type account_type =
  | Challenge_1step
  | Challenge_2step_phase1
  | Challenge_2step_phase2
  | Funded_standard
  | Funded_swing
  | Funded_rewards_1step

(** Equity-derived monetary values. Abstract: cannot be confused with each
    other or with raw floats. Constructors are private. *)
type usd
val usd_of_float : float -> usd
val usd_to_float : usd -> float

(** Account state. Mutually exclusive (variant): an account is exactly one of
    these at any moment. *)
type account_status =
  | Active
  | Internal_killed of { reason : string; killed_at : float (* unix ts *) }
  | Ftmo_failed of { rule : string; failed_at : float }

(** Snapshot of the account at a point in time. *)
type account_snapshot = {
  status : account_status;
  initial_capital : usd;
  midnight_balance : usd;       (** balance at last 00:00 Europe/Prague *)
  equity : usd;                 (** balance + floating P&L + swaps - commissions *)
  highest_midnight_balance : usd;  (** for Funded Rewards trailing max *)
  account : account_type;
}

(** A single equity tick driving the state machine forward. *)
type tick = {
  unix_ts : float;
  equity : usd;
}

(** Pre-trade headroom-check inputs and result. *)
type pretrade_request = {
  current_equity : usd;
  worst_case_drawdown : usd;  (** projected adverse-fill drawdown if order fires *)
}

type pretrade_decision =
  | Allow
  | Deny of string
  | Imminent of string  (** within 1% of an FTMO line; reduce sizing *)

(** Apply one tick to the state machine. Returns the new snapshot.

    Invariant: if the input snapshot is [Active] and this tick crosses an
    FTMO line, the output snapshot will be [Ftmo_failed], NEVER [Active].
    If it crosses an internal kill line first, output is [Internal_killed]. *)
val apply_tick : account_snapshot -> tick -> account_snapshot

(** Pre-trade gate. Returns [Allow] / [Deny] / [Imminent]. *)
val check_pretrade : account_snapshot -> pretrade_request -> pretrade_decision

(** Construct a fresh active snapshot for a new account. *)
val new_account :
  account:account_type ->
  initial_capital:float ->
  account_snapshot
