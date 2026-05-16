(** Tiny CLI for ad-hoc testing the rule engine.

    Simulates a sequence of equity ticks and prints the resulting account
    state at each step. Useful for manual sanity-checking before / after
    changes to ftmo_rules.ml. *)

open Ftmo_rules

let format_status = function
  | Active -> "Active"
  | Internal_killed { reason; _ } -> Printf.sprintf "Internal_killed(%s)" reason
  | Ftmo_failed { rule; _ } -> Printf.sprintf "Ftmo_failed(%s)" rule

let () =
  let s = new_account
    ~account:Challenge_2step_phase1
    ~initial_capital:100_000.0 in
  Printf.printf "Initial: equity=%.2f status=%s\n"
    (usd_to_float s.equity) (format_status s.status);

  (* Walk through a synthetic equity drawdown. *)
  let ticks = [
    100_000.0; 99_500.0; 99_200.0; 98_500.0; 97_800.0;
    97_000.0; 96_200.0; 95_400.0; 94_500.0; 93_200.0;
  ] in

  let _final = List.fold_left
    (fun s (i, eq) ->
      let t : tick = { unix_ts = float_of_int i; equity = usd_of_float eq } in
      let s' = apply_tick s t in
      Printf.printf "Tick %d: equity=%.2f status=%s\n"
        i eq (format_status s'.status);
      s')
    s
    (List.mapi (fun i x -> (i, x)) ticks)
  in
  ()
