(** CLI demo of the FTMO rule state machine.

    Walks a synthetic equity series through apply_tick and prints the
    status at each step. Useful for manual sanity-checks. *)

open Ftmo_rules

let format_status = function
  | Active -> "Active"
  | Imminent { line; _ } ->
      Printf.sprintf "Imminent(%s)" (breach_kind_to_string line)
  | Internal_killed { kind; _ } ->
      Printf.sprintf "Internal_killed(%s)" (breach_kind_to_string kind)
  | Ftmo_failed { kind; _ } ->
      Printf.sprintf "Ftmo_failed(%s)" (breach_kind_to_string kind)

let () =
  let s = new_state
    ~account:Challenge_2step_phase1
    ~initial_capital:100_000.0 in
  Printf.printf "Initial: status=%s daily=%.2f max=%.2f\n"
    (format_status s.status)
    (usd_to_float (ftmo_daily_limit s))
    (usd_to_float (ftmo_max_loss_limit s));

  let ticks = [
    100_000.0; 99_500.0; 99_200.0; 98_500.0; 97_800.0;
    97_000.0; 96_200.0; 95_400.0; 94_500.0; 93_200.0;
    91_500.0; 89_000.0;
  ] in
  let _ = List.fold_left
    (fun s (i, eq) ->
      let t : tick = { unix_ts = float_of_int i; equity = usd_of_float eq } in
      let s' = apply_tick s t in
      Printf.printf "Tick %2d  equity=%.2f  status=%s\n"
        i eq (format_status s'.status);
      s')
    s
    (List.mapi (fun i x -> (i, x)) ticks)
  in
  Printf.printf "\nHeadroom check on small order ($300 worst-case loss):\n";
  let order = {
    symbol = "TEST";
    worst_case_loss = usd_of_float 300.0;
    expected_pnl = usd_of_float 600.0;
  } in
  (match headroom_check s ~equity:s.initial_capital ~order with
   | Allow -> Printf.printf "  -> Allow\n"
   | Deny { rule; detail } ->
       Printf.printf "  -> Deny: %s -- %s\n" rule detail
   | Caution { rule; detail } ->
       Printf.printf "  -> Caution: %s -- %s\n" rule detail);

  Printf.printf "\nHeadroom check on huge order ($4000 worst-case loss):\n";
  let big_order = {
    symbol = "TEST";
    worst_case_loss = usd_of_float 4000.0;
    expected_pnl = usd_of_float 8000.0;
  } in
  match headroom_check s ~equity:s.initial_capital ~order:big_order with
  | Allow -> Printf.printf "  -> Allow\n"
  | Deny { rule; detail } ->
      Printf.printf "  -> Deny: %s -- %s\n" rule detail
  | Caution { rule; detail } ->
      Printf.printf "  -> Caution: %s -- %s\n" rule detail
