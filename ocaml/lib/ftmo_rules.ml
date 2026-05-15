(** SCAFFOLDING ONLY -- the type shape is right but the transitions are
    placeholder. Phase 5 of the build plan will port the real rule logic
    from [risk/ftmo.py]. The .mli file is the contract; tests below pin
    down the invariants the real implementation must satisfy. *)

type account_type =
  | Challenge_1step
  | Challenge_2step_phase1
  | Challenge_2step_phase2
  | Funded_standard
  | Funded_swing
  | Funded_rewards_1step

type usd = float
let usd_of_float x = x
let usd_to_float x = x

type account_status =
  | Active
  | Internal_killed of { reason : string; killed_at : float }
  | Ftmo_failed of { rule : string; failed_at : float }

type account_snapshot = {
  status : account_status;
  initial_capital : usd;
  midnight_balance : usd;
  equity : usd;
  highest_midnight_balance : usd;
  account : account_type;
}

type tick = {
  unix_ts : float;
  equity : usd;
}

type pretrade_request = {
  current_equity : usd;
  worst_case_drawdown : usd;
}

type pretrade_decision =
  | Allow
  | Deny of string
  | Imminent of string

(* ----- Rule constants per CLAUDE.md sec.3 ----- *)

(** Internal daily-loss kill, as a fraction of initial sim capital. *)
let internal_daily_kill_pct (acct : account_type) : float =
  match acct with
  | Challenge_1step | Funded_rewards_1step -> 0.02
  | _ -> 0.03

(** Internal max-loss kill, as a fraction of initial sim capital. *)
let internal_max_kill_pct : float = 0.07

(** FTMO daily-loss line, as a fraction of initial sim capital. *)
let ftmo_daily_pct (acct : account_type) : float =
  match acct with
  | Challenge_1step | Funded_rewards_1step -> 0.03
  | _ -> 0.05

(** FTMO max-loss line, as a fraction of initial sim capital. *)
let ftmo_max_pct : float = 0.10

(* ----- State machine ----- *)

let new_account ~account ~initial_capital =
  {
    status = Active;
    initial_capital = usd_of_float initial_capital;
    midnight_balance = usd_of_float initial_capital;
    equity = usd_of_float initial_capital;
    highest_midnight_balance = usd_of_float initial_capital;
    account;
  }

(** Daily loss line in absolute USD terms.

    Computed as midnight_balance - daily_pct * initial_capital. *)
let daily_loss_line (s : account_snapshot) : usd =
  s.midnight_balance -. (ftmo_daily_pct s.account *. s.initial_capital)

(** Max loss line in absolute USD terms. Static for Challenge / Funded
    standard; trailing-up only for Funded Rewards (TODO in real impl). *)
let max_loss_line (s : account_snapshot) : usd =
  s.initial_capital -. (ftmo_max_pct *. s.initial_capital)

(** Internal daily kill line. *)
let internal_daily_line (s : account_snapshot) : usd =
  s.midnight_balance -. (internal_daily_kill_pct s.account *. s.initial_capital)

(** Internal max kill line. *)
let internal_max_line (s : account_snapshot) : usd =
  s.initial_capital -. (internal_max_kill_pct *. s.initial_capital)

(** [apply_tick] enforces the priority order: FTMO lines BEAT internal kill
    BEAT continued operation. Internal kill is a safety mechanism to PREVENT
    the FTMO breach -- once the FTMO line is crossed, the account is failed
    regardless of internal-kill status.

    PLACEHOLDER: real implementation will live in Phase 5. The current logic
    is enough to validate the type shape and let the qcheck property tests
    compile. *)
let apply_tick (s : account_snapshot) (t : tick) : account_snapshot =
  match s.status with
  | Internal_killed _ | Ftmo_failed _ ->
      (* Once killed/failed, no further state change from a tick. *)
      { s with equity = t.equity }
  | Active ->
      let new_equity = t.equity in
      let s' = { s with equity = new_equity } in
      (* Priority: FTMO max > FTMO daily > internal max > internal daily *)
      if new_equity <= max_loss_line s' then
        { s' with status =
            Ftmo_failed { rule = "max_loss"; failed_at = t.unix_ts } }
      else if new_equity <= daily_loss_line s' then
        { s' with status =
            Ftmo_failed { rule = "daily_loss"; failed_at = t.unix_ts } }
      else if new_equity <= internal_max_line s' then
        { s' with status =
            Internal_killed { reason = "internal_max"; killed_at = t.unix_ts } }
      else if new_equity <= internal_daily_line s' then
        { s' with status =
            Internal_killed { reason = "internal_daily"; killed_at = t.unix_ts } }
      else
        s'

(** Pre-trade gate: simulate worst-case fill and reject if too close to a
    line. PLACEHOLDER -- real impl in Phase 5. *)
let check_pretrade (s : account_snapshot) (req : pretrade_request)
    : pretrade_decision =
  let projected = req.current_equity -. req.worst_case_drawdown in
  let imminent_buffer = 0.01 *. s.initial_capital in
  if projected <= internal_max_line s then
    Deny "would breach internal max kill"
  else if projected <= internal_daily_line s then
    Deny "would breach internal daily kill"
  else if projected -. internal_max_line s < imminent_buffer then
    Imminent "within 1% of max-loss line"
  else if projected -. internal_daily_line s < imminent_buffer then
    Imminent "within 1% of daily-loss line"
  else
    Allow
