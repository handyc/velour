(* cellular.ml — OCaml port of the s3lab Cellular sublab.

   SOURCE  : static/s3lab/js/sublabs/cellular.mjs (438 LOC)
             + static/s3lab/js/engine.mjs (276 LOC)
             + isolation/artifacts/cellular/c/cellular_c.c (Phase 1)
   TARGET  : OCaml 4.14, stdlib only — no dune, no opam deps required.
   PARITY  : algorithm + scoring identical to the JS reference at the
             same seed. ANSI-256 terminal render at periodic intervals.

   Build & run:
     ocaml cellular.ml                 # interpret directly
     ocamlfind ocamlopt -package unix \
       -linkpkg cellular.ml -o cellular  # compile (optional)
     ./cellular -r 200 -s 42

   Phase 3 of the cellular multi-platform port. The previous C and
   ESP32-S3 ports show that the kernel is portable; the OCaml port
   shows it ports cleanly into a different language family too.
   Functional core, imperative shell — same as the JS but with
   stronger types. *)

(* ── compile-time constants ────────────────────────────────────── *)

let k          = 4
let nsit       = 16384      (* k^7 *)
let gbytes     = 4096       (* nsit * 2 / 8 *)
let pal_bytes  = k
let ca_w       = 16
let ca_h       = 16
let horizon    = 25

let grid_cols  = 16
let grid_rows  = 16
let n_cells    = grid_cols * grid_rows

(* hex offset deltas — match engine.mjs *)
let dy  = [| -1; -1;  0;  0;  1;  1 |]
let dxe = [|  0;  1; -1;  1; -1;  0 |]
let dxo = [| -1;  0; -1;  1;  0;  1 |]

(* toroidal pop neighbours (mirror engine.mjs::neighbourIdx) *)
let nb_dc_even = [| -1; +1; -1;  0; -1;  0 |]
let nb_dc_odd  = [| -1; +1;  0; +1;  0; +1 |]
let nb_dr      = [|  0;  0; -1; -1; +1; +1 |]

(* ── PRNG: xorshift32 (matches engine.mjs::prng exactly) ───────── *)

let prng_state = ref 0x9E3779B9

let seed_prng s = prng_state := if s = 0 then 1 else (s land 0xFFFFFFFF)

let mask32 = 0xFFFFFFFF

let prng () =
  let x = !prng_state in
  let x = (x lxor (x lsl 13)) land mask32 in
  let x = (x lxor (x lsr 17)) land mask32 in
  let x = (x lxor (x lsl 5))  land mask32 in
  prng_state := x;
  x

let prng_unit () = float_of_int (prng ()) /. 4294967296.0

(* Park-Miller LCG for grid seeding (mirror engine.mjs::lcg) *)
let lcg_state = ref 0
let lcg_seed s = lcg_state := if s = 0 then 1 else (s land mask32)
let lcg_step () =
  lcg_state := (!lcg_state * 1103515245 + 12345) land mask32;
  !lcg_state lsr 16

(* ── packed-genome accessors ───────────────────────────────────── *)

let g_get g idx =
  (Char.code (Bytes.get g (idx lsr 2)) lsr ((idx land 3) * 2)) land 3

let g_set g idx v =
  let b = idx lsr 2 and o = (idx land 3) * 2 in
  let cur = Char.code (Bytes.get g b) in
  let cleared = cur land (lnot (3 lsl o) land 0xFF) in
  Bytes.set g b (Char.chr (cleared lor ((v land 3) lsl o)))

let sit_idx self_c n =
  let i = ref self_c in
  for j = 0 to 5 do i := !i * k + n.(j) done;
  !i

(* ── grid stepping ─────────────────────────────────────────────── *)

let seed_grid_at g s =
  lcg_seed s;
  for i = 0 to ca_w * ca_h - 1 do
    Bytes.set g i (Char.chr (lcg_step () land 3))
  done

let step_grid genome ing outg =
  let n = Array.make 6 0 in
  for y = 0 to ca_h - 1 do
    let dx = if y land 1 = 1 then dxo else dxe in
    for x = 0 to ca_w - 1 do
      let self_c = Char.code (Bytes.get ing (y * ca_w + x)) in
      for kk = 0 to 5 do
        let yy = y + dy.(kk) and xx = x + dx.(kk) in
        n.(kk) <-
          if yy >= 0 && yy < ca_h && xx >= 0 && xx < ca_w
          then Char.code (Bytes.get ing (yy * ca_w + xx))
          else 0
      done;
      let v = g_get genome (sit_idx self_c n) in
      Bytes.set outg (y * ca_w + x) (Char.chr v)
    done
  done

(* ── fitness (mirror engine.mjs::fitness exactly) ──────────────── *)

let fit_a = Bytes.make (ca_w * ca_h) '\x00'
let fit_b = Bytes.make (ca_w * ca_h) '\x00'

let fitness genome grid_seed =
  seed_grid_at fit_a grid_seed;
  let act = Array.make horizon 0.0 in
  let counts = Array.make k 0 in
  for t = 0 to horizon - 1 do
    step_grid genome fit_a fit_b;
    let changed = ref 0 in
    for i = 0 to ca_w * ca_h - 1 do
      if Bytes.get fit_a i <> Bytes.get fit_b i then incr changed
    done;
    act.(t) <- float_of_int !changed /. float_of_int (ca_w * ca_h);
    Bytes.blit fit_b 0 fit_a 0 (ca_w * ca_h)
  done;
  let uniform = ref true in
  let first = Bytes.get fit_a 0 in
  for i = 1 to ca_w * ca_h - 1 do
    if Bytes.get fit_a i <> first then uniform := false
  done;
  Array.fill counts 0 k 0;
  for i = 0 to ca_w * ca_h - 1 do
    let v = Char.code (Bytes.get fit_a i) in
    counts.(v) <- counts.(v) + 1
  done;
  let diversity = ref 0 in
  for c = 0 to k - 1 do
    if counts.(c) * 100 >= ca_w * ca_h then incr diversity
  done;
  let tail_n = max 1 (horizon / 3) in
  let avg = ref 0.0 in
  for i = horizon - tail_n to horizon - 1 do avg := !avg +. act.(i) done;
  avg := !avg /. float_of_int tail_n;
  let score = ref 0.0 in
  if not !uniform then score := !score +. 1.0;
  let aperiodic = ref false in
  for i = horizon - tail_n to horizon - 1 do
    if act.(i) > 0.001 then aperiodic := true
  done;
  if !aperiodic then score := !score +. 1.5;
  let reward =
    if !avg <= 0.12 then !avg /. 0.12
    else (0.75 -. !avg) /. 0.63
  in
  let reward = if reward < 0.0 then 0.0 else reward in
  score := !score +. 2.0 *. reward;
  if !diversity >= 2 then
    score := !score +. 0.25 *. float_of_int (min !diversity k);
  !score

(* ── GA ops ────────────────────────────────────────────────────── *)

let random_genome_into g =
  for i = 0 to gbytes - 1 do
    Bytes.set g i (Char.chr (prng () land 0xFF))
  done

let invent_palette_into pal =
  let n = ref 0 in
  while !n < k do
    let c =
      if (prng () mod 10) < 9 then 16 + (prng () mod 216)
      else 232 + (prng () mod 24)
    in
    let dup = ref false in
    for j = 0 to !n - 1 do
      if Char.code (Bytes.get pal j) = c then dup := true
    done;
    if not !dup then begin
      Bytes.set pal !n (Char.chr c);
      incr n
    end
  done

let mutate_into dst src rate =
  Bytes.blit src 0 dst 0 gbytes;
  for i = 0 to nsit - 1 do
    if prng_unit () < rate then g_set dst i (prng () land 3)
  done

let palette_inherit_into dst a b =
  let src = if (prng () land 1) = 1 then a else b in
  Bytes.blit src 0 dst 0 pal_bytes;
  if (prng () mod 100) < 8 then begin
    let slot = prng () mod k in
    let c =
      if (prng () mod 10) < 9 then 16 + (prng () mod 216)
      else 232 + (prng () mod 24)
    in
    Bytes.set dst slot (Char.chr c)
  end

(* ── topology: toroidal pointy-top hex ─────────────────────────── *)

let neighbour_idx i dir =
  let r = i / grid_cols and c = i - (i / grid_cols) * grid_cols in
  let dc = if r land 1 = 1 then nb_dc_odd.(dir) else nb_dc_even.(dir) in
  let dr = nb_dr.(dir) in
  let nr = ((r + dr) mod grid_rows + grid_rows) mod grid_rows in
  let nc = ((c + dc) mod grid_cols + grid_cols) mod grid_cols in
  nr * grid_cols + nc

(* ── population state ──────────────────────────────────────────── *)

type cell = {
  genome    : bytes;
  palette   : bytes;
  mutable grid_a : bytes;
  mutable grid_b : bytes;
  mutable score : float;
  mutable refined_at : int;
}

let make_cell () = {
  genome     = Bytes.make gbytes '\x00';
  palette    = Bytes.make pal_bytes '\x00';
  grid_a     = Bytes.make (ca_w * ca_h) '\x00';
  grid_b     = Bytes.make (ca_w * ca_h) '\x00';
  score      = 0.0;
  refined_at = 0;
}

let pop : cell array = Array.init n_cells (fun _ -> make_cell ())

let bootstrap_pop master_seed =
  seed_prng master_seed;
  for i = 0 to n_cells - 1 do
    let s = (master_seed lxor (i * 2654435761)) land mask32 in
    seed_prng (if s = 0 then 1 else s);
    random_genome_into pop.(i).genome;
    invent_palette_into pop.(i).palette;
    seed_grid_at pop.(i).grid_a (prng ());
    Bytes.fill pop.(i).grid_b 0 (ca_w * ca_h) '\x00';
    pop.(i).score <- 0.0;
    pop.(i).refined_at <- 0
  done;
  seed_prng (master_seed lxor 0xDEADBEEF)

(* ── tick + round ──────────────────────────────────────────────── *)

let tick_all () =
  for i = 0 to n_cells - 1 do
    let c = pop.(i) in
    step_grid c.genome c.grid_a c.grid_b;
    let tmp = c.grid_a in
    c.grid_a <- c.grid_b;
    c.grid_b <- tmp
  done

let g_rounds = ref 0
let last_winner = ref (-1)
let last_loser  = ref (-1)

let run_round mut_rate =
  let ci  = prng () mod n_cells in
  let dir = prng () mod 6 in
  let ni  = neighbour_idx ci dir in
  if ci <> ni then begin
    let shared_seed = prng () in
    let fc = fitness pop.(ci).genome shared_seed in
    let fn = fitness pop.(ni).genome shared_seed in
    pop.(ci).score <- fc;
    pop.(ni).score <- fn;
    let winner = if fc >= fn then ci else ni in
    let loser  = if winner = ci then ni else ci in
    let w = pop.(winner) and l = pop.(loser) in
    mutate_into l.genome w.genome mut_rate;
    palette_inherit_into l.palette w.palette w.palette;
    l.score <- w.score;
    l.refined_at <- !g_rounds;
    seed_grid_at l.grid_a (prng ());
    last_winner := winner;
    last_loser  := loser;
    incr g_rounds
  end

(* ── ANSI-256 render ───────────────────────────────────────────── *)

let dominant_palette_idx c =
  let counts = Array.make k 0 in
  for i = 0 to ca_w * ca_h - 1 do
    let v = Char.code (Bytes.get c.grid_a i) in
    counts.(v) <- counts.(v) + 1
  done;
  let best = ref 0 in
  for i = 1 to k - 1 do
    if counts.(i) > counts.(!best) then best := i
  done;
  Char.code (Bytes.get c.palette !best)

let render () =
  print_string "\x1b[H\x1b[2J";
  for r = 0 to grid_rows - 1 do
    if r land 1 = 1 then print_char ' ';
    for c = 0 to grid_cols - 1 do
      let ansi = dominant_palette_idx pop.(r * grid_cols + c) in
      Printf.printf "\x1b[48;5;%dm  \x1b[0m" ansi
    done;
    print_char '\n'
  done;
  Printf.printf "round %d  pop=%dx%d  win=%d loser=%d\n%!"
    !g_rounds grid_cols grid_rows !last_winner !last_loser

(* ── argument parsing + main loop ──────────────────────────────── *)

let usage () =
  print_string
"usage: cellular [-r N] [-m RATE] [-s SEED] [-p ROUNDS_PER_RENDER]\n\
\  -r N                    run N rounds then exit (default 200)\n\
\  -m RATE                 mutation rate (default 0.005)\n\
\  -s SEED                 PRNG seed (default 42)\n\
\  -p ROUNDS_PER_RENDER    render every Nth round (default 25)\n\
\  -h                      this help\n"

let () =
  let max_rounds = ref 200 in
  let mut_rate   = ref 0.005 in
  let seed       = ref 42 in
  let render_every = ref 25 in
  let i = ref 1 in
  while !i < Array.length Sys.argv do
    let a = Sys.argv.(!i) in
    let next () = incr i; if !i >= Array.length Sys.argv then begin usage (); exit 2 end; Sys.argv.(!i) in
    (match a with
     | "-r" -> max_rounds   := int_of_string (next ())
     | "-m" -> mut_rate     := float_of_string (next ())
     | "-s" -> seed         := int_of_string (next ())
     | "-p" -> render_every := int_of_string (next ())
     | "-h" | "--help" -> usage (); exit 0
     | _    -> usage (); exit 2);
    incr i
  done;
  Printf.eprintf "cellular-ocaml: seed=%d  pop=%dx%d  rounds=%d  mut=%.4f\n%!"
    !seed grid_cols grid_rows !max_rounds !mut_rate;
  bootstrap_pop !seed;
  for _ = 0 to !max_rounds - 1 do
    tick_all ();
    run_round !mut_rate;
    if !render_every > 0 && !g_rounds mod !render_every = 0 then render ()
  done;
  render ();
  Printf.eprintf "cellular-ocaml: %d rounds completed.\n%!" !g_rounds
