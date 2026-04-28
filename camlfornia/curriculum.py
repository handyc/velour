"""Extended OCaml curriculum for Camlfornia.

The original 11 lessons live in ``management/commands/seed_camlfornia.py``;
this module adds the rest — fundamentals the intro skipped, intermediate
topics (modules, exceptions, mutability, data structures), and a string
of advanced lessons climbing through GADTs, classes, multicore, and a
mini-interpreter built from first principles.

Lessons added here use the same dict shape: slug / order / title /
difficulty / prompt_md / starter_code / solution_code / expected_output.
``order`` numbers leave room (multiples of 10) so future lessons can
slot between siblings without renumbering.
"""


EXTRA_LESSONS = [
    # ─── INTRO additions (gaps in the original 11) ─────────────────
    {
        'slug': 'comments',
        'order': 12,
        'title': 'Comments',
        'difficulty': 'intro',
        'prompt_md': (
            '## Notes for humans\n\n'
            'OCaml comments are nestable: `(* ... *)`. They can wrap '
            'multiple lines and even contain other comments — handy '
            'for commenting out a block that already has one.\n\n'
            '**Task.** Print `commented` after a comment that contains '
            'another comment.'
        ),
        'starter_code': 'print_endline "uncomment me";;\n',
        'solution_code': '(* outer (* inner *) outer *)\nprint_endline "commented";;\n',
        'expected_output': 'commented',
    },
    {
        'slug': 'integers',
        'order': 14,
        'title': 'Integer arithmetic',
        'difficulty': 'intro',
        'prompt_md': (
            '## Integers\n\n'
            'OCaml integers are 63-bit on 64-bit systems. Operators: '
            '`+`, `-`, `*`, `/`, and `mod` for remainder. Integer '
            'division truncates toward zero.\n\n'
            '**Task.** Print `17 / 5 = 3 r 2` using `Printf.printf`.'
        ),
        'starter_code': 'Printf.printf "17 / 5 = %d r %d\\n" 0 0;;\n',
        'solution_code': 'Printf.printf "17 / 5 = %d r %d\\n" (17 / 5) (17 mod 5);;\n',
        'expected_output': '17 / 5 = 3 r 2',
    },
    {
        'slug': 'floats',
        'order': 16,
        'title': 'Floats',
        'difficulty': 'intro',
        'prompt_md': (
            '## Floats need their own operators\n\n'
            'OCaml does not auto-promote ints to floats. Float ops are '
            '`+.`, `-.`, `*.`, `/.`, with float literals written `1.0` '
            'or `1.` (note the trailing dot).\n\n'
            '**Task.** Compute the area of a circle with radius `2.0` '
            'and print it with two decimal places.'
        ),
        'starter_code': 'let pi = 3.14159 in\nlet r = 2.0 in\nPrintf.printf "%.2f\\n" 0.0;;\n',
        'solution_code': 'let pi = 3.14159 in\nlet r = 2.0 in\nPrintf.printf "%.2f\\n" (pi *. r *. r);;\n',
        'expected_output': '12.57',
    },
    {
        'slug': 'strings-basic',
        'order': 18,
        'title': 'Strings',
        'difficulty': 'intro',
        'prompt_md': (
            '## Strings\n\n'
            'Strings are immutable. Concatenate with `^`, get length '
            'with `String.length s`, take a substring with '
            '`String.sub s start length`.\n\n'
            '**Task.** Take `"OCaml is lovely"`, build the prefix '
            '`"OCaml"` with `String.sub`, and print `OCaml has 5 letters`.'
        ),
        'starter_code': (
            'let s = "OCaml is lovely" in\n'
            'let prefix = "" in\n'
            'Printf.printf "%s has %d letters\\n" prefix (String.length prefix);;\n'
        ),
        'solution_code': (
            'let s = "OCaml is lovely" in\n'
            'let prefix = String.sub s 0 5 in\n'
            'Printf.printf "%s has %d letters\\n" prefix (String.length prefix);;\n'
        ),
        'expected_output': 'OCaml has 5 letters',
    },
    {
        'slug': 'chars',
        'order': 19,
        'title': 'Chars',
        'difficulty': 'intro',
        'prompt_md': (
            '## Chars\n\n'
            'A char literal is `\'a\'`. `Char.code c` gives its byte '
            'value; `Char.chr n` is the inverse.\n\n'
            '**Task.** Print the byte code of `\'A\'` followed by the '
            'character whose code is 90.'
        ),
        'starter_code': 'Printf.printf "%d %c\\n" 0 \' \';;\n',
        'solution_code': 'Printf.printf "%d %c\\n" (Char.code \'A\') (Char.chr 90);;\n',
        'expected_output': '65 Z',
    },
    {
        'slug': 'booleans',
        'order': 21,
        'title': 'Booleans',
        'difficulty': 'intro',
        'prompt_md': (
            '## Booleans\n\n'
            'OCaml booleans are `true` and `false`. Operators: `&&` '
            '(short-circuit and), `||` (short-circuit or), `not`.\n\n'
            '`Printf.printf "%b\\n"` prints a boolean.\n\n'
            '**Task.** Print `true` if 5 is between 1 and 10 inclusive.'
        ),
        'starter_code': 'let n = 5 in\nPrintf.printf "%b\\n" false;;\n',
        'solution_code': 'let n = 5 in\nPrintf.printf "%b\\n" (n >= 1 && n <= 10);;\n',
        'expected_output': 'true',
    },
    {
        'slug': 'comparison',
        'order': 23,
        'title': 'Comparison',
        'difficulty': 'intro',
        'prompt_md': (
            '## Structural comparison\n\n'
            '`=` and `<>` compare for structural equality (deep). '
            '`<`, `>`, `<=`, `>=` work on most ordered types. '
            '`compare a b` returns a negative, zero, or positive int.\n\n'
            '**Task.** Print `compare [1;2] [1;3]` (a negative integer).'
        ),
        'starter_code': 'Printf.printf "%d\\n" 0;;\n',
        'solution_code': 'Printf.printf "%d\\n" (compare [1;2] [1;3]);;\n',
        'expected_output': '-1',
    },
    {
        'slug': 'sequencing',
        'order': 25,
        'title': 'Sequencing with ;',
        'difficulty': 'intro',
        'prompt_md': (
            '## ; vs ;;\n\n'
            'Inside an expression, `;` sequences side effects: the '
            'left side must be `unit`, the right side\'s value is the '
            'result. `;;` ends a top-level phrase in the toplevel.\n\n'
            '**Task.** Print three lines `one`, `two`, `three` using '
            '`begin ... end` and `;`.'
        ),
        'starter_code': (
            'begin\n'
            '  print_endline "one"\n'
            'end;;\n'
        ),
        'solution_code': (
            'begin\n'
            '  print_endline "one";\n'
            '  print_endline "two";\n'
            '  print_endline "three"\n'
            'end;;\n'
        ),
        'expected_output': 'one\ntwo\nthree',
    },

    # ─── BASIC additions ───────────────────────────────────────────
    {
        'slug': 'shadowing',
        'order': 55,
        'title': 'Shadowing',
        'difficulty': 'basic',
        'prompt_md': (
            '## Names can be redefined\n\n'
            'A new `let x = ...` shadows the previous `x` for the '
            'rest of the scope. The old binding still exists where '
            'it was visible — closures captured it.\n\n'
            '**Task.** Bind `x = 1`, then re-bind `x = x + 41`, and '
            'print `x`.'
        ),
        'starter_code': 'let x = 1 in\n(* shadow x here *)\nPrintf.printf "%d\\n" x;;\n',
        'solution_code': 'let x = 1 in\nlet x = x + 41 in\nPrintf.printf "%d\\n" x;;\n',
        'expected_output': '42',
    },
    {
        'slug': 'type-annotations',
        'order': 57,
        'title': 'Type annotations',
        'difficulty': 'basic',
        'prompt_md': (
            '## Annotating types\n\n'
            'OCaml infers types, but you can annotate parameters and '
            'return types: `let f (x : int) : int = x + 1`. Useful '
            'for documentation and to nudge inference toward what '
            'you meant.\n\n'
            '**Task.** Define `triple : int -> int` with explicit '
            'annotations on both parameter and result, and print `triple 14`.'
        ),
        'starter_code': 'let triple x = 0;;\nPrintf.printf "%d\\n" (triple 14);;\n',
        'solution_code': 'let triple (x : int) : int = x * 3;;\nPrintf.printf "%d\\n" (triple 14);;\n',
        'expected_output': '42',
    },
    {
        'slug': 'currying',
        'order': 65,
        'title': 'Currying & partial application',
        'difficulty': 'basic',
        'prompt_md': (
            '## Curried functions\n\n'
            'In OCaml, `let f a b = ...` is sugar for '
            '`let f = fun a -> fun b -> ...`. Partial application '
            'builds a new function: `let add5 = (+) 5`.\n\n'
            '**Task.** Build `add10` from `(+) 10`, then print `add10 32`.'
        ),
        'starter_code': 'let add10 = (+) 0 in\nPrintf.printf "%d\\n" (add10 32);;\n',
        'solution_code': 'let add10 = (+) 10 in\nPrintf.printf "%d\\n" (add10 32);;\n',
        'expected_output': '42',
    },
    {
        'slug': 'pipe-operator',
        'order': 67,
        'title': 'The pipe operator |>',
        'difficulty': 'basic',
        'prompt_md': (
            '## |> reads left-to-right\n\n'
            '`x |> f` is `f x` — useful for pipelines:\n\n'
            '```\n[1;2;3;4] |> List.map ((*)2) |> List.fold_left (+) 0\n```\n\n'
            '**Task.** Use `|>` to double each item of `[1;2;3;4;5]` '
            'then sum them. Print the result.'
        ),
        'starter_code': (
            'let xs = [1;2;3;4;5] in\n'
            'let total = 0 in\n'
            'Printf.printf "%d\\n" total;;\n'
        ),
        'solution_code': (
            'let xs = [1;2;3;4;5] in\n'
            'let total = xs |> List.map (fun x -> x * 2) |> List.fold_left (+) 0 in\n'
            'Printf.printf "%d\\n" total;;\n'
        ),
        'expected_output': '30',
    },
    {
        'slug': 'function-composition',
        'order': 69,
        'title': 'Function composition',
        'difficulty': 'basic',
        'prompt_md': (
            '## Compose your own\n\n'
            'OCaml has no built-in `compose`, but it is one line:\n\n'
            '```\nlet (%) f g x = f (g x)\n```\n\n'
            '**Task.** Define `inc` and `double`, compose them as '
            '`double % inc`, and print `(double % inc) 20`.'
        ),
        'starter_code': (
            'let inc x = x + 1 in\n'
            'let double x = x * 2 in\n'
            'let (%) f g x = f (g x) in\n'
            'Printf.printf "%d\\n" 0;;\n'
        ),
        'solution_code': (
            'let inc x = x + 1 in\n'
            'let double x = x * 2 in\n'
            'let (%) f g x = f (g x) in\n'
            'Printf.printf "%d\\n" ((double % inc) 20);;\n'
        ),
        'expected_output': '42',
    },

    # ─── INTERMEDIATE: list standard library ───────────────────────
    {
        'slug': 'list-length-rev',
        'order': 120,
        'title': 'List.length, List.rev',
        'difficulty': 'interm',
        'prompt_md': (
            '## Two staples\n\n'
            '`List.length xs` and `List.rev xs` do what you expect. '
            'Both are O(n).\n\n'
            '**Task.** Print the length of `[10;20;30;40]` then the '
            'reversed list (use `List.iter (Printf.printf "%d ")`).'
        ),
        'starter_code': (
            'let xs = [10;20;30;40] in\n'
            'Printf.printf "len=%d\\n" 0;\n'
            'print_endline ""\n;;\n'
        ),
        'solution_code': (
            'let xs = [10;20;30;40] in\n'
            'Printf.printf "len=%d\\n" (List.length xs);\n'
            'List.iter (Printf.printf "%d ") (List.rev xs);\n'
            'print_endline ""\n;;\n'
        ),
        'expected_output': 'len=4\n40 30 20 10 ',
    },
    {
        'slug': 'list-map',
        'order': 130,
        'title': 'List.map',
        'difficulty': 'interm',
        'prompt_md': (
            '## map\n\n'
            '`List.map f xs` builds a new list by applying `f` to '
            'each element. Type: `(\'a -> \'b) -> \'a list -> \'b list`.\n\n'
            '**Task.** Square `[1;2;3;4]` and print the result with '
            '`List.iter`.'
        ),
        'starter_code': (
            'let xs = [1;2;3;4] in\n'
            'let ys = xs in\n'
            'List.iter (Printf.printf "%d ") ys;\n'
            'print_endline ""\n;;\n'
        ),
        'solution_code': (
            'let xs = [1;2;3;4] in\n'
            'let ys = List.map (fun x -> x * x) xs in\n'
            'List.iter (Printf.printf "%d ") ys;\n'
            'print_endline ""\n;;\n'
        ),
        'expected_output': '1 4 9 16 ',
    },
    {
        'slug': 'list-filter',
        'order': 140,
        'title': 'List.filter',
        'difficulty': 'interm',
        'prompt_md': (
            '## filter\n\n'
            '`List.filter pred xs` keeps elements where `pred` is true.\n\n'
            '**Task.** Keep the even numbers from `[1;2;3;4;5;6]` and '
            'print them.'
        ),
        'starter_code': (
            'let xs = [1;2;3;4;5;6] in\n'
            'let evens = xs in\n'
            'List.iter (Printf.printf "%d ") evens;\n'
            'print_endline ""\n;;\n'
        ),
        'solution_code': (
            'let xs = [1;2;3;4;5;6] in\n'
            'let evens = List.filter (fun x -> x mod 2 = 0) xs in\n'
            'List.iter (Printf.printf "%d ") evens;\n'
            'print_endline ""\n;;\n'
        ),
        'expected_output': '2 4 6 ',
    },
    {
        'slug': 'list-fold-left',
        'order': 150,
        'title': 'List.fold_left',
        'difficulty': 'interm',
        'prompt_md': (
            '## fold_left\n\n'
            '`List.fold_left f init xs` walks left-to-right, threading '
            'the accumulator through `f`. It is the workhorse for sums, '
            'products, max, etc.\n\n'
            '**Task.** Sum `[1;2;3;4;5]` with `fold_left` and print it.'
        ),
        'starter_code': (
            'let xs = [1;2;3;4;5] in\n'
            'let total = 0 in\n'
            'Printf.printf "%d\\n" total;;\n'
        ),
        'solution_code': (
            'let xs = [1;2;3;4;5] in\n'
            'let total = List.fold_left (+) 0 xs in\n'
            'Printf.printf "%d\\n" total;;\n'
        ),
        'expected_output': '15',
    },
    {
        'slug': 'list-fold-right',
        'order': 155,
        'title': 'List.fold_right',
        'difficulty': 'interm',
        'prompt_md': (
            '## fold_right\n\n'
            '`List.fold_right f xs init` walks right-to-left. It builds '
            'in the natural order for cons-style construction:\n\n'
            '```\nList.fold_right (fun x acc -> x :: acc) xs []\n```\n\n'
            '**Task.** Re-implement `List.map (fun x -> x * 10)` using '
            '`fold_right`. Print the mapped `[1;2;3]`.'
        ),
        'starter_code': (
            'let xs = [1;2;3] in\n'
            'let ys = xs in\n'
            'List.iter (Printf.printf "%d ") ys;\n'
            'print_endline ""\n;;\n'
        ),
        'solution_code': (
            'let xs = [1;2;3] in\n'
            'let ys = List.fold_right (fun x acc -> (x * 10) :: acc) xs [] in\n'
            'List.iter (Printf.printf "%d ") ys;\n'
            'print_endline ""\n;;\n'
        ),
        'expected_output': '10 20 30 ',
    },
    {
        'slug': 'list-iter',
        'order': 160,
        'title': 'List.iter',
        'difficulty': 'interm',
        'prompt_md': (
            '## Iter for side effects\n\n'
            '`List.iter f xs` is fold for `unit` — `f` runs for each '
            'element, return value discarded.\n\n'
            '**Task.** Print each item of `["A";"B";"C"]` on its own line.'
        ),
        'starter_code': 'let xs = ["A";"B";"C"] in\n(* call iter here *) ();;\n',
        'solution_code': 'let xs = ["A";"B";"C"] in\nList.iter print_endline xs;;\n',
        'expected_output': 'A\nB\nC',
    },
    {
        'slug': 'list-append-concat',
        'order': 165,
        'title': 'append & concat',
        'difficulty': 'interm',
        'prompt_md': (
            '## Joining lists\n\n'
            '`List.append a b` (also written `a @ b`) is O(|a|). '
            '`List.concat [[1;2];[3];[4;5]]` flattens a list of lists.\n\n'
            '**Task.** Flatten `[[1;2];[3];[4;5;6]]` and print with iter.'
        ),
        'starter_code': (
            'let xss = [[1;2];[3];[4;5;6]] in\n'
            'let flat = [] in\n'
            'List.iter (Printf.printf "%d ") flat;\n'
            'print_endline ""\n;;\n'
        ),
        'solution_code': (
            'let xss = [[1;2];[3];[4;5;6]] in\n'
            'let flat = List.concat xss in\n'
            'List.iter (Printf.printf "%d ") flat;\n'
            'print_endline ""\n;;\n'
        ),
        'expected_output': '1 2 3 4 5 6 ',
    },

    # ─── INTERMEDIATE: recursion patterns ──────────────────────────
    {
        'slug': 'mutual-recursion',
        'order': 175,
        'title': 'Mutual recursion (let rec...and)',
        'difficulty': 'interm',
        'prompt_md': (
            '## Two functions that call each other\n\n'
            'Use `let rec f ... and g ...` to define a pair that '
            'reference each other:\n\n'
            '```\nlet rec is_even n = if n = 0 then true  else is_odd  (n - 1)\n'
            'and is_odd  n = if n = 0 then false else is_even (n - 1)\n```\n\n'
            '**Task.** Define `is_even`/`is_odd` mutually and print '
            '`is_even 10` then `is_odd 10`.'
        ),
        'starter_code': (
            'let rec is_even n = false\n'
            'and is_odd  n = false in\n'
            'Printf.printf "%b %b\\n" (is_even 10) (is_odd 10);;\n'
        ),
        'solution_code': (
            'let rec is_even n = if n = 0 then true  else is_odd  (n - 1)\n'
            'and     is_odd  n = if n = 0 then false else is_even (n - 1) in\n'
            'Printf.printf "%b %b\\n" (is_even 10) (is_odd 10);;\n'
        ),
        'expected_output': 'true false',
    },
    {
        'slug': 'tail-recursion',
        'order': 180,
        'title': 'Tail recursion',
        'difficulty': 'interm',
        'prompt_md': (
            '## Tail calls — a free win\n\n'
            'OCaml optimises tail calls into jumps. A function whose '
            'recursive call is the last thing it does runs in '
            'constant stack space.\n\n'
            'Naive `factorial` is NOT tail-recursive — the multiply '
            'happens after the call returns. Add an accumulator:\n\n'
            '```\nlet factorial n =\n  let rec go n acc = if n <= 1 then acc else go (n - 1) (n * acc) in\n  go n 1\n```\n\n'
            '**Task.** Implement tail-recursive `factorial 10` and print it.'
        ),
        'starter_code': (
            'let factorial n =\n'
            '  let rec go n acc = acc in\n'
            '  go n 1\n'
            'in\n'
            'Printf.printf "%d\\n" (factorial 10);;\n'
        ),
        'solution_code': (
            'let factorial n =\n'
            '  let rec go n acc =\n'
            '    if n <= 1 then acc else go (n - 1) (n * acc)\n'
            '  in go n 1\n'
            'in\n'
            'Printf.printf "%d\\n" (factorial 10);;\n'
        ),
        'expected_output': '3628800',
    },
    {
        'slug': 'accumulator-pattern',
        'order': 185,
        'title': 'Accumulator pattern',
        'difficulty': 'interm',
        'prompt_md': (
            '## Accumulators — generalising tail recursion\n\n'
            'Many recursive functions become tail-recursive when you '
            'thread an accumulator through. The price is that the '
            'natural reading order reverses, so you often `List.rev` '
            'at the end.\n\n'
            '**Task.** Reverse `[1;2;3;4;5]` with a tail-recursive '
            'helper and print with iter.'
        ),
        'starter_code': (
            'let my_rev xs =\n'
            '  let rec go xs acc = acc in\n'
            '  go xs []\n'
            'in\n'
            'List.iter (Printf.printf "%d ") (my_rev [1;2;3;4;5]);\n'
            'print_endline ""\n;;\n'
        ),
        'solution_code': (
            'let my_rev xs =\n'
            '  let rec go xs acc = match xs with\n'
            '    | [] -> acc\n'
            '    | x :: rest -> go rest (x :: acc)\n'
            '  in go xs []\n'
            'in\n'
            'List.iter (Printf.printf "%d ") (my_rev [1;2;3;4;5]);\n'
            'print_endline ""\n;;\n'
        ),
        'expected_output': '5 4 3 2 1 ',
    },

    # ─── INTERMEDIATE: mutability ──────────────────────────────────
    {
        'slug': 'refs',
        'order': 200,
        'title': 'Refs',
        'difficulty': 'interm',
        'prompt_md': (
            '## Refs — mutable cells\n\n'
            '`ref v` makes a mutable cell holding `v`. `!r` reads, '
            '`r := v\'` writes. Useful for counters, accumulators '
            'across imperative loops.\n\n'
            '**Task.** Use a ref to count from 1 to 5 with a `for` '
            'loop and print the final count.'
        ),
        'starter_code': (
            'let n = ref 0 in\n'
            'for _ = 1 to 5 do () done;\n'
            'Printf.printf "%d\\n" !n;;\n'
        ),
        'solution_code': (
            'let n = ref 0 in\n'
            'for _ = 1 to 5 do incr n done;\n'
            'Printf.printf "%d\\n" !n;;\n'
        ),
        'expected_output': '5',
    },
    {
        'slug': 'mutable-records',
        'order': 210,
        'title': 'Mutable record fields',
        'difficulty': 'interm',
        'prompt_md': (
            '## Records can be mutable per-field\n\n'
            'Mark a field `mutable` to allow `r.field <- v\'`:\n\n'
            '```\ntype counter = { mutable count : int }\nlet c = { count = 0 }\nlet () = c.count <- c.count + 1\n```\n\n'
            '**Task.** Define a `counter` record, increment it three '
            'times, print its count.'
        ),
        'starter_code': (
            'type counter = { mutable count : int };;\n'
            'let c = { count = 0 } in\n'
            '(* increment c three times *)\n'
            'Printf.printf "%d\\n" c.count;;\n'
        ),
        'solution_code': (
            'type counter = { mutable count : int };;\n'
            'let c = { count = 0 } in\n'
            'c.count <- c.count + 1;\n'
            'c.count <- c.count + 1;\n'
            'c.count <- c.count + 1;\n'
            'Printf.printf "%d\\n" c.count;;\n'
        ),
        'expected_output': '3',
    },
    {
        'slug': 'arrays',
        'order': 220,
        'title': 'Arrays',
        'difficulty': 'interm',
        'prompt_md': (
            '## Arrays — fixed-length, mutable\n\n'
            '`Array.make n v` allocates. `a.(i)` reads, `a.(i) <- v` '
            'writes. `Array.length` is O(1).\n\n'
            '**Task.** Make a length-5 int array of zeros, set '
            '`a.(2) <- 42`, and print `a.(2)`.'
        ),
        'starter_code': (
            'let a = Array.make 5 0 in\n'
            'Printf.printf "%d\\n" a.(2);;\n'
        ),
        'solution_code': (
            'let a = Array.make 5 0 in\n'
            'a.(2) <- 42;\n'
            'Printf.printf "%d\\n" a.(2);;\n'
        ),
        'expected_output': '42',
    },
    {
        'slug': 'hashtbl',
        'order': 225,
        'title': 'Hashtables',
        'difficulty': 'interm',
        'prompt_md': (
            '## Hashtables\n\n'
            '`Hashtbl.create 16` builds one. `Hashtbl.add h k v` '
            'and `Hashtbl.find h k` are the basics.\n\n'
            '**Task.** Insert `("a", 1)` and `("b", 2)`, then print '
            '`Hashtbl.find h "b"`.'
        ),
        'starter_code': (
            'let h = Hashtbl.create 16 in\n'
            'Printf.printf "%d\\n" 0;;\n'
        ),
        'solution_code': (
            'let h = Hashtbl.create 16 in\n'
            'Hashtbl.add h "a" 1;\n'
            'Hashtbl.add h "b" 2;\n'
            'Printf.printf "%d\\n" (Hashtbl.find h "b");;\n'
        ),
        'expected_output': '2',
    },

    # ─── INTERMEDIATE: errors and Result ──────────────────────────
    {
        'slug': 'exceptions',
        'order': 240,
        'title': 'Exceptions',
        'difficulty': 'interm',
        'prompt_md': (
            '## try ... with\n\n'
            '`raise Exit` raises a built-in exception. Catch with:\n\n'
            '```\ntry expr with\n  | Not_found -> ...\n  | Exit -> ...\n```\n\n'
            '**Task.** Catch `Not_found` from `List.find ((=) 99) [1;2;3]` '
            'and print `missing`.'
        ),
        'starter_code': (
            'let r = (try string_of_int (List.find ((=) 99) [1;2;3])\n'
            '         with Not_found -> "found") in\n'
            'print_endline r;;\n'
        ),
        'solution_code': (
            'let r = (try string_of_int (List.find ((=) 99) [1;2;3])\n'
            '         with Not_found -> "missing") in\n'
            'print_endline r;;\n'
        ),
        'expected_output': 'missing',
    },
    {
        'slug': 'custom-exceptions',
        'order': 250,
        'title': 'Custom exceptions',
        'difficulty': 'interm',
        'prompt_md': (
            '## exception E of t\n\n'
            'You can declare your own carrying any payload:\n\n'
            '```\nexception Bad_input of string\n'
            'raise (Bad_input "expected an int")\n```\n\n'
            '**Task.** Define `exception Bad_input of string`, raise '
            'it, and in the catch print `caught: <message>`.'
        ),
        'starter_code': (
            'exception Bad_input of string;;\n'
            '(try raise (Bad_input "oops") with _ -> print_endline "ok");;\n'
        ),
        'solution_code': (
            'exception Bad_input of string;;\n'
            '(try raise (Bad_input "oops")\n'
            ' with Bad_input msg -> Printf.printf "caught: %s\\n" msg);;\n'
        ),
        'expected_output': 'caught: oops',
    },
    {
        'slug': 'result-type',
        'order': 260,
        'title': 'Result type',
        'difficulty': 'interm',
        'prompt_md': (
            '## Result — exceptions without raising\n\n'
            'OCaml ships `type (\'a, \'b) result = Ok of \'a | Error of \'b`. '
            'Pattern-match like any variant; chain with `Result.bind`.\n\n'
            '**Task.** Define `safe_div` that returns `Error "div by 0"` '
            'on zero, otherwise `Ok q`. Print `safe_div 10 0`\'s message.'
        ),
        'starter_code': (
            'let safe_div a b = Ok 0 in\n'
            'let r = safe_div 10 0 in\n'
            '(match r with\n'
            ' | Ok q -> Printf.printf "got %d\\n" q\n'
            ' | Error e -> Printf.printf "err: %s\\n" e);;\n'
        ),
        'solution_code': (
            'let safe_div a b =\n'
            '  if b = 0 then Error "div by 0" else Ok (a / b)\n'
            'in\n'
            'let r = safe_div 10 0 in\n'
            '(match r with\n'
            ' | Ok q -> Printf.printf "got %d\\n" q\n'
            ' | Error e -> Printf.printf "err: %s\\n" e);;\n'
        ),
        'expected_output': 'err: div by 0',
    },

    # ─── INTERMEDIATE: data structures ─────────────────────────────
    {
        'slug': 'recursive-types',
        'order': 280,
        'title': 'Recursive types',
        'difficulty': 'interm',
        'prompt_md': (
            '## Recursive types\n\n'
            'Variants can refer to themselves, giving you trees and '
            'lists by hand:\n\n'
            '```\ntype \'a my_list = Nil | Cons of \'a * \'a my_list\n```\n\n'
            '**Task.** Build `Cons (1, Cons (2, Cons (3, Nil)))`, write '
            'a recursive `sum`, and print it.'
        ),
        'starter_code': (
            'type \'a my_list = Nil | Cons of \'a * \'a my_list;;\n'
            'let rec sum = function _ -> 0 in\n'
            'Printf.printf "%d\\n" (sum (Cons (1, Cons (2, Cons (3, Nil)))));;\n'
        ),
        'solution_code': (
            'type \'a my_list = Nil | Cons of \'a * \'a my_list;;\n'
            'let rec sum = function\n'
            '  | Nil -> 0\n'
            '  | Cons (x, rest) -> x + sum rest\n'
            'in\n'
            'Printf.printf "%d\\n" (sum (Cons (1, Cons (2, Cons (3, Nil)))));;\n'
        ),
        'expected_output': '6',
    },
    {
        'slug': 'binary-tree',
        'order': 290,
        'title': 'Binary trees',
        'difficulty': 'interm',
        'prompt_md': (
            '## Trees from variants\n\n'
            '```\ntype \'a tree = Leaf | Node of \'a tree * \'a * \'a tree\n```\n\n'
            '**Task.** Define `tree`, build a small one, and write '
            '`size : \'a tree -> int` returning the number of nodes. '
            'Print the size of `Node (Node (Leaf, 1, Leaf), 2, Node (Leaf, 3, Leaf))`.'
        ),
        'starter_code': (
            'type \'a tree = Leaf | Node of \'a tree * \'a * \'a tree;;\n'
            'let rec size _ = 0 in\n'
            'let t = Node (Node (Leaf, 1, Leaf), 2, Node (Leaf, 3, Leaf)) in\n'
            'Printf.printf "%d\\n" (size t);;\n'
        ),
        'solution_code': (
            'type \'a tree = Leaf | Node of \'a tree * \'a * \'a tree;;\n'
            'let rec size = function\n'
            '  | Leaf -> 0\n'
            '  | Node (l, _, r) -> 1 + size l + size r\n'
            'in\n'
            'let t = Node (Node (Leaf, 1, Leaf), 2, Node (Leaf, 3, Leaf)) in\n'
            'Printf.printf "%d\\n" (size t);;\n'
        ),
        'expected_output': '3',
    },
    {
        'slug': 'tree-inorder',
        'order': 295,
        'title': 'Tree traversal',
        'difficulty': 'interm',
        'prompt_md': (
            '## Inorder, preorder, postorder\n\n'
            'With the same `\'a tree` variant, traverse in different '
            'orders by re-arranging the recursive calls.\n\n'
            '**Task.** Inorder-print the tree below — should yield '
            '`1 2 3 4 5`.'
        ),
        'starter_code': (
            'type \'a tree = Leaf | Node of \'a tree * \'a * \'a tree;;\n'
            'let rec inorder _ = () in\n'
            'let t =\n'
            '  Node (Node (Node (Leaf, 1, Leaf), 2, Node (Leaf, 3, Leaf)),\n'
            '        4,\n'
            '        Node (Leaf, 5, Leaf)) in\n'
            'inorder t;\n'
            'print_endline ""\n;;\n'
        ),
        'solution_code': (
            'type \'a tree = Leaf | Node of \'a tree * \'a * \'a tree;;\n'
            'let rec inorder = function\n'
            '  | Leaf -> ()\n'
            '  | Node (l, x, r) -> inorder l; Printf.printf "%d " x; inorder r\n'
            'in\n'
            'let t =\n'
            '  Node (Node (Node (Leaf, 1, Leaf), 2, Node (Leaf, 3, Leaf)),\n'
            '        4,\n'
            '        Node (Leaf, 5, Leaf)) in\n'
            'inorder t;\n'
            'print_endline ""\n;;\n'
        ),
        'expected_output': '1 2 3 4 5 ',
    },

    # ─── INTERMEDIATE: standard library containers ─────────────────
    {
        'slug': 'stdlib-map',
        'order': 320,
        'title': 'Standard library Map',
        'difficulty': 'interm',
        'prompt_md': (
            '## Map — functorial dictionaries\n\n'
            '`Map.Make(Ord)` produces a module with `add`, `find`, '
            '`mem`. The keys are immutable; the resulting map is too.\n\n'
            '**Task.** Build `IntMap`, insert 1→"a", 2→"b", and '
            'print `find 2 m`.'
        ),
        'starter_code': (
            'module IntMap = Map.Make (Int);;\n'
            'let m = IntMap.empty in\n'
            'print_endline "?";;\n'
        ),
        'solution_code': (
            'module IntMap = Map.Make (Int);;\n'
            'let m = IntMap.empty\n'
            '        |> IntMap.add 1 "a"\n'
            '        |> IntMap.add 2 "b" in\n'
            'print_endline (IntMap.find 2 m);;\n'
        ),
        'expected_output': 'b',
    },
    {
        'slug': 'stdlib-set',
        'order': 330,
        'title': 'Standard library Set',
        'difficulty': 'interm',
        'prompt_md': (
            '## Set — functorial sets\n\n'
            '`Set.Make(Ord)` mirrors `Map`. Useful for membership '
            'checks and union/intersection.\n\n'
            '**Task.** Build `IntSet`, add 1, 2, 3, and print '
            '`cardinal s`.'
        ),
        'starter_code': (
            'module IntSet = Set.Make (Int);;\n'
            'let s = IntSet.empty in\n'
            'Printf.printf "%d\\n" 0;;\n'
        ),
        'solution_code': (
            'module IntSet = Set.Make (Int);;\n'
            'let s = IntSet.empty |> IntSet.add 1 |> IntSet.add 2 |> IntSet.add 3 in\n'
            'Printf.printf "%d\\n" (IntSet.cardinal s);;\n'
        ),
        'expected_output': '3',
    },
    {
        'slug': 'stdlib-stack',
        'order': 340,
        'title': 'Stack',
        'difficulty': 'interm',
        'prompt_md': (
            '## Mutable stack\n\n'
            '`Stack.create ()` allocates. `push v s`, `pop s`, '
            '`top s`. Raises `Stack.Empty` on empty pop.\n\n'
            '**Task.** Push 1, 2, 3, then print pops until empty.'
        ),
        'starter_code': (
            'let s = Stack.create () in\n'
            '(* push then pop *)\n'
            '();;\n'
        ),
        'solution_code': (
            'let s = Stack.create () in\n'
            'Stack.push 1 s; Stack.push 2 s; Stack.push 3 s;\n'
            'while not (Stack.is_empty s) do\n'
            '  Printf.printf "%d " (Stack.pop s)\n'
            'done;\n'
            'print_endline ""\n;;\n'
        ),
        'expected_output': '3 2 1 ',
    },
    {
        'slug': 'stdlib-queue',
        'order': 345,
        'title': 'Queue',
        'difficulty': 'interm',
        'prompt_md': (
            '## Queue\n\n'
            '`Queue.create ()`, `Queue.add v q`, `Queue.pop q`. '
            'FIFO mirror of Stack.\n\n'
            '**Task.** Add 1, 2, 3, then drain the queue printing '
            'each.'
        ),
        'starter_code': (
            'let q = Queue.create () in\n'
            '();;\n'
        ),
        'solution_code': (
            'let q = Queue.create () in\n'
            'Queue.add 1 q; Queue.add 2 q; Queue.add 3 q;\n'
            'while not (Queue.is_empty q) do\n'
            '  Printf.printf "%d " (Queue.pop q)\n'
            'done;\n'
            'print_endline ""\n;;\n'
        ),
        'expected_output': '1 2 3 ',
    },

    # ─── INTERMEDIATE: modules ─────────────────────────────────────
    {
        'slug': 'modules',
        'order': 360,
        'title': 'Modules',
        'difficulty': 'interm',
        'prompt_md': (
            '## Inline modules\n\n'
            '`module M = struct let x = 1 let f y = y + x end` '
            'creates a structure. Access via `M.x`, `M.f 41`.\n\n'
            '**Task.** Build a module `Geom` exposing `pi` and '
            '`area_circle`, and print `area_circle 1.0`.'
        ),
        'starter_code': (
            'module Geom = struct\n'
            '  let pi = 3.14159\n'
            '  let area_circle r = 0.0\n'
            'end;;\n'
            'Printf.printf "%.5f\\n" (Geom.area_circle 1.0);;\n'
        ),
        'solution_code': (
            'module Geom = struct\n'
            '  let pi = 3.14159\n'
            '  let area_circle r = pi *. r *. r\n'
            'end;;\n'
            'Printf.printf "%.5f\\n" (Geom.area_circle 1.0);;\n'
        ),
        'expected_output': '3.14159',
    },
    {
        'slug': 'module-signature',
        'order': 365,
        'title': 'Module signatures',
        'difficulty': 'interm',
        'prompt_md': (
            '## Sealing a module with a signature\n\n'
            'Constrain a module against an interface to hide '
            'internals:\n\n'
            '```\nmodule type COUNTER = sig\n  val tick : unit -> int\nend\n'
            'module Counter : COUNTER = struct ... end\n```\n\n'
            '**Task.** Define `COUNTER` and `Counter` with a private '
            'ref. Call `tick` three times and print the last result.'
        ),
        'starter_code': (
            'module type COUNTER = sig val tick : unit -> int end;;\n'
            'module Counter : COUNTER = struct\n'
            '  let tick () = 0\n'
            'end;;\n'
            'let _ = Counter.tick () in\n'
            'let _ = Counter.tick () in\n'
            'Printf.printf "%d\\n" (Counter.tick ());;\n'
        ),
        'solution_code': (
            'module type COUNTER = sig val tick : unit -> int end;;\n'
            'module Counter : COUNTER = struct\n'
            '  let n = ref 0\n'
            '  let tick () = incr n; !n\n'
            'end;;\n'
            'let _ = Counter.tick () in\n'
            'let _ = Counter.tick () in\n'
            'Printf.printf "%d\\n" (Counter.tick ());;\n'
        ),
        'expected_output': '3',
    },

    # ─── ADVANCED ──────────────────────────────────────────────────
    {
        'slug': 'functors',
        'order': 400,
        'title': 'Functors',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Functors — modules parametrised by modules\n\n'
            '`Map.Make` and `Set.Make` are functors. Defining one:\n\n'
            '```\nmodule type SHOW = sig type t val show : t -> string end\n'
            'module Pair (A : SHOW) (B : SHOW) = struct\n'
            '  type t = A.t * B.t\n'
            '  let show (a, b) = "(" ^ A.show a ^ ", " ^ B.show b ^ ")"\n'
            'end\n```\n\n'
            '**Task.** Apply `Pair (IntShow) (StringShow)` and print '
            '`show (1, "hi")`.'
        ),
        'starter_code': (
            'module type SHOW = sig type t val show : t -> string end;;\n'
            'module IntShow : SHOW with type t = int = struct\n'
            '  type t = int let show = string_of_int\n'
            'end;;\n'
            'module StringShow : SHOW with type t = string = struct\n'
            '  type t = string let show s = "\\"" ^ s ^ "\\""\n'
            'end;;\n'
            'module Pair (A : SHOW) (B : SHOW) = struct\n'
            '  type t = A.t * B.t\n'
            '  let show (_a, _b) = "?"\n'
            'end;;\n'
            'module P = Pair (IntShow) (StringShow);;\n'
            'print_endline (P.show (1, "hi"));;\n'
        ),
        'solution_code': (
            'module type SHOW = sig type t val show : t -> string end;;\n'
            'module IntShow : SHOW with type t = int = struct\n'
            '  type t = int let show = string_of_int\n'
            'end;;\n'
            'module StringShow : SHOW with type t = string = struct\n'
            '  type t = string let show s = "\\"" ^ s ^ "\\""\n'
            'end;;\n'
            'module Pair (A : SHOW) (B : SHOW) = struct\n'
            '  type t = A.t * B.t\n'
            '  let show (a, b) = "(" ^ A.show a ^ ", " ^ B.show b ^ ")"\n'
            'end;;\n'
            'module P = Pair (IntShow) (StringShow);;\n'
            'print_endline (P.show (1, "hi"));;\n'
        ),
        'expected_output': '(1, "hi")',
    },
    {
        'slug': 'polymorphic-variants',
        'order': 410,
        'title': 'Polymorphic variants',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Polymorphic variants — variants without declarations\n\n'
            'Backtick prefix: `` `On ``, `` `Off ``. They unify '
            'structurally — handy for open extensions, exhaustive '
            'matching is enforced contextually.\n\n'
            '**Task.** Match on a polymorphic variant `[`On | `Off | `Dim of int]` '
            'and print "lit" for `\\`Dim 5`.'
        ),
        'starter_code': (
            'let label = function\n'
            '  | `On  -> "on"\n'
            '  | `Off -> "off"\n'
            '  | `Dim n -> "?"\n'
            'in\n'
            'print_endline (label (`Dim 5));;\n'
        ),
        'solution_code': (
            'let label = function\n'
            '  | `On  -> "on"\n'
            '  | `Off -> "off"\n'
            '  | `Dim n -> if n > 0 then "lit" else "off"\n'
            'in\n'
            'print_endline (label (`Dim 5));;\n'
        ),
        'expected_output': 'lit',
    },
    {
        'slug': 'classes-objects',
        'order': 420,
        'title': 'Classes & objects',
        'difficulty': 'advanced',
        'prompt_md': (
            '## OO OCaml\n\n'
            'OCaml has classes with row-polymorphic objects:\n\n'
            '```\nclass counter = object\n'
            '  val mutable n = 0\n'
            '  method incr = n <- n + 1\n'
            '  method get = n\n'
            'end\n```\n\n'
            '**Task.** Instantiate `new counter`, call `#incr` three '
            'times, print `#get`.'
        ),
        'starter_code': (
            'class counter = object\n'
            '  val mutable n = 0\n'
            '  method incr = n <- n + 1\n'
            '  method get = n\n'
            'end;;\n'
            'let c = new counter in\n'
            'Printf.printf "%d\\n" c#get;;\n'
        ),
        'solution_code': (
            'class counter = object\n'
            '  val mutable n = 0\n'
            '  method incr = n <- n + 1\n'
            '  method get = n\n'
            'end;;\n'
            'let c = new counter in\n'
            'c#incr; c#incr; c#incr;\n'
            'Printf.printf "%d\\n" c#get;;\n'
        ),
        'expected_output': '3',
    },
    {
        'slug': 'lazy',
        'order': 430,
        'title': 'Lazy values',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Lazy — defer until forced\n\n'
            '`lazy expr` builds a thunk. `Lazy.force t` evaluates it '
            'once and memoises the result.\n\n'
            '**Task.** Build a `lazy` of an expensive print, force it '
            'twice, and observe the print only once.'
        ),
        'starter_code': (
            'let t = lazy (print_endline "computing"; 42) in\n'
            'let _ = Lazy.force t in\n'
            'Printf.printf "got %d\\n" 0;;\n'
        ),
        'solution_code': (
            'let t = lazy (print_endline "computing"; 42) in\n'
            'let v1 = Lazy.force t in\n'
            'let v2 = Lazy.force t in\n'
            'Printf.printf "got %d %d\\n" v1 v2;;\n'
        ),
        'expected_output': 'computing\ngot 42 42',
    },
    {
        'slug': 'seq',
        'order': 440,
        'title': 'Seq — lazy sequences',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Seq — pull-based, lazy\n\n'
            '`Seq.t` represents a possibly-infinite sequence. '
            '`Seq.unfold` is the constructor.\n\n'
            '**Task.** Build the integers 1.. with `unfold` and print '
            'the first 5 with `Seq.take` + `Seq.iter`.'
        ),
        'starter_code': (
            'let nats = Seq.unfold (fun n -> Some (n, n + 1)) 1 in\n'
            'Seq.take 0 nats |> Seq.iter (Printf.printf "%d ");\n'
            'print_endline ""\n;;\n'
        ),
        'solution_code': (
            'let nats = Seq.unfold (fun n -> Some (n, n + 1)) 1 in\n'
            'Seq.take 5 nats |> Seq.iter (Printf.printf "%d ");\n'
            'print_endline ""\n;;\n'
        ),
        'expected_output': '1 2 3 4 5 ',
    },
    {
        'slug': 'fixpoint-y',
        'order': 460,
        'title': 'Fixpoint combinator',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Recursion without `let rec`\n\n'
            'You can define `fix` so that `fix f` behaves like a '
            'recursive function:\n\n'
            '```\nlet rec fix f x = f (fix f) x\n```\n\n'
            'Then any recursive function can be written in open '
            'form: `fix (fun fact n -> if n <= 1 then 1 else n * fact (n - 1))`.\n\n'
            '**Task.** Use `fix` to compute factorial of 6 and print it.'
        ),
        'starter_code': (
            'let rec fix f x = f (fix f) x in\n'
            'let fact = fix (fun _self n -> 0) in\n'
            'Printf.printf "%d\\n" (fact 6);;\n'
        ),
        'solution_code': (
            'let rec fix f x = f (fix f) x in\n'
            'let fact = fix (fun self n -> if n <= 1 then 1 else n * self (n - 1)) in\n'
            'Printf.printf "%d\\n" (fact 6);;\n'
        ),
        'expected_output': '720',
    },
    {
        'slug': 'memoization',
        'order': 470,
        'title': 'Memoization',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Cache results\n\n'
            'Wrap a function so each input is computed at most once. '
            'A `Hashtbl` works.\n\n'
            '**Task.** Memoise the recursive Fibonacci and print '
            '`fib 30`.'
        ),
        'starter_code': (
            'let memo f =\n'
            '  let h = Hashtbl.create 16 in\n'
            '  fun x -> f x  (* TODO: cache *)\n'
            'in\n'
            'let rec fib n = if n < 2 then n else fib (n - 1) + fib (n - 2) in\n'
            'let fast = memo fib in\n'
            'Printf.printf "%d\\n" (fast 30);;\n'
        ),
        'solution_code': (
            'let rec fib_memo h n =\n'
            '  if n < 2 then n\n'
            '  else match Hashtbl.find_opt h n with\n'
            '    | Some v -> v\n'
            '    | None ->\n'
            '        let v = fib_memo h (n - 1) + fib_memo h (n - 2) in\n'
            '        Hashtbl.add h n v; v\n'
            'in\n'
            'let h = Hashtbl.create 64 in\n'
            'Printf.printf "%d\\n" (fib_memo h 30);;\n'
        ),
        'expected_output': '832040',
    },
    {
        'slug': 'cps',
        'order': 480,
        'title': 'Continuation-passing style',
        'difficulty': 'advanced',
        'prompt_md': (
            '## CPS — every call is a tail call\n\n'
            'Pass a continuation `k : \'b -> \'r` instead of returning. '
            'Sum a list in CPS:\n\n'
            '```\nlet rec sum_k xs k = match xs with\n'
            '  | [] -> k 0\n'
            '  | x :: rest -> sum_k rest (fun s -> k (x + s))\n```\n\n'
            '**Task.** Implement `sum_k` and use it with `Fun.id` on '
            '`[1;2;3;4;5]`.'
        ),
        'starter_code': (
            'let rec sum_k xs k = k 0 in\n'
            'Printf.printf "%d\\n" (sum_k [1;2;3;4;5] Fun.id);;\n'
        ),
        'solution_code': (
            'let rec sum_k xs k = match xs with\n'
            '  | [] -> k 0\n'
            '  | x :: rest -> sum_k rest (fun s -> k (x + s))\n'
            'in\n'
            'Printf.printf "%d\\n" (sum_k [1;2;3;4;5] Fun.id);;\n'
        ),
        'expected_output': '15',
    },
    {
        'slug': 'church-booleans',
        'order': 490,
        'title': 'Church booleans',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Booleans as functions\n\n'
            'Encode `true` as `fun x _ -> x` and `false` as `fun _ y -> y`. '
            '`if b then a else c` becomes `b a c`.\n\n'
            '**Task.** Define `ctrue`, `cfalse`, and `c_if`, then '
            'print `c_if cfalse "yes" "no"`.'
        ),
        'starter_code': (
            'let ctrue  = fun x _ -> x in\n'
            'let cfalse = fun _ y -> y in\n'
            'let c_if b a c = b a c in\n'
            'print_endline (c_if cfalse "yes" "no");;\n'
        ),
        'solution_code': (
            'let ctrue  = fun x _ -> x in\n'
            'let cfalse = fun _ y -> y in\n'
            'let c_if b a c = b a c in\n'
            'print_endline (c_if cfalse "yes" "no");;\n'
        ),
        'expected_output': 'no',
    },
    {
        'slug': 'church-numerals',
        'order': 500,
        'title': 'Church numerals',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Numbers as functions\n\n'
            '`zero = fun _ x -> x`, `succ n = fun f x -> f (n f x)`. '
            'Convert back to int via `to_int n = n (fun x -> x + 1) 0`.\n\n'
            '**Task.** Build `three` from `succ (succ (succ zero))` '
            'and print `to_int three`.'
        ),
        'starter_code': (
            'let zero = fun _ x -> x in\n'
            'let succ n = fun f x -> f (n f x) in\n'
            'let to_int n = n (fun x -> x + 1) 0 in\n'
            'let three = zero in\n'
            'Printf.printf "%d\\n" (to_int three);;\n'
        ),
        'solution_code': (
            'let zero = fun _ x -> x in\n'
            'let succ n = fun f x -> f (n f x) in\n'
            'let to_int n = n (fun x -> x + 1) 0 in\n'
            'let three = succ (succ (succ zero)) in\n'
            'Printf.printf "%d\\n" (to_int three);;\n'
        ),
        'expected_output': '3',
    },
    {
        'slug': 'state-monad',
        'order': 520,
        'title': 'A tiny state monad',
        'difficulty': 'advanced',
        'prompt_md': (
            '## State as a value\n\n'
            'Pure state-passing: a `state` action is `state -> a * state`. '
            'Compose with `bind`:\n\n'
            '```\nlet return a s = (a, s)\n'
            'let bind m f s = let (a, s\') = m s in f a s\'\n'
            'let get s = (s, s)\n'
            'let put v _ = ((), v)\n```\n\n'
            '**Task.** Run `bind get (fun n -> put (n + 1))` starting '
            'at state `41` and print the resulting state.'
        ),
        'starter_code': (
            'let return a s = (a, s) in\n'
            'let bind m f s = let (a, s\') = m s in f a s\' in\n'
            'let get s = (s, s) in\n'
            'let put v _ = ((), v) in\n'
            'let _action = bind get (fun n -> return n) in\n'
            'let (_, s_final) = _action 41 in\n'
            'Printf.printf "%d\\n" s_final;;\n'
        ),
        'solution_code': (
            'let return a s = (a, s) in\n'
            'let bind m f s = let (a, s\') = m s in f a s\' in\n'
            'let get s = (s, s) in\n'
            'let put v _ = ((), v) in\n'
            'let action = bind get (fun n -> put (n + 1)) in\n'
            'let (_, s_final) = action 41 in\n'
            'Printf.printf "%d\\n" s_final;;\n'
        ),
        'expected_output': '42',
    },
    {
        'slug': 'mini-interpreter',
        'order': 550,
        'title': 'Mini lambda interpreter',
        'difficulty': 'advanced',
        'prompt_md': (
            '## A tiny calculator\n\n'
            'Smallest possible AST: numbers, addition, multiplication.\n\n'
            '```\ntype expr = Num of int | Add of expr * expr | Mul of expr * expr\n'
            'let rec eval = function\n'
            '  | Num n -> n\n'
            '  | Add (a, b) -> eval a + eval b\n'
            '  | Mul (a, b) -> eval a * eval b\n```\n\n'
            '**Task.** Eval `Mul (Num 6, Add (Num 4, Num 3))` and print it.'
        ),
        'starter_code': (
            'type expr = Num of int | Add of expr * expr | Mul of expr * expr;;\n'
            'let rec eval _ = 0 in\n'
            'Printf.printf "%d\\n" (eval (Mul (Num 6, Add (Num 4, Num 3))));;\n'
        ),
        'solution_code': (
            'type expr = Num of int | Add of expr * expr | Mul of expr * expr;;\n'
            'let rec eval = function\n'
            '  | Num n -> n\n'
            '  | Add (a, b) -> eval a + eval b\n'
            '  | Mul (a, b) -> eval a * eval b\n'
            'in\n'
            'Printf.printf "%d\\n" (eval (Mul (Num 6, Add (Num 4, Num 3))));;\n'
        ),
        'expected_output': '42',
    },
    {
        'slug': 'parser-combinator',
        'order': 560,
        'title': 'Parser combinator skeleton',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Parsing as functions\n\n'
            'A parser is `string -> int -> (\'a * int) option` — read '
            'starting at offset, return value + new offset on success. '
            'Combinators stitch them together.\n\n'
            '**Task.** Parse a single digit at offset 0 of `"7abc"` '
            'and print the value.'
        ),
        'starter_code': (
            'let digit s i =\n'
            '  if i < String.length s && s.[i] >= \'0\' && s.[i] <= \'9\'\n'
            '  then None  (* TODO *)\n'
            '  else None\n'
            'in\n'
            '(match digit "7abc" 0 with\n'
            ' | Some (n, _) -> Printf.printf "%d\\n" n\n'
            ' | None -> print_endline "fail");;\n'
        ),
        'solution_code': (
            'let digit s i =\n'
            '  if i < String.length s && s.[i] >= \'0\' && s.[i] <= \'9\'\n'
            '  then Some (Char.code s.[i] - Char.code \'0\', i + 1)\n'
            '  else None\n'
            'in\n'
            '(match digit "7abc" 0 with\n'
            ' | Some (n, _) -> Printf.printf "%d\\n" n\n'
            ' | None -> print_endline "fail");;\n'
        ),
        'expected_output': '7',
    },
    {
        'slug': 'string-format',
        'order': 580,
        'title': 'Format module',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Pretty-printing with Format\n\n'
            '`Format.printf` understands `@,` (cut), `@ ` (break), '
            '`@[`/`@]` (open/close box) for layout that adapts to '
            'output width.\n\n'
            '**Task.** Print `[ 1, 2, 3 ]` with one space padding '
            'around the brackets using a Format box.'
        ),
        'starter_code': (
            'Format.printf "@[<h>[ %d, %d, %d ]@]@." 1 2 3;;\n'
        ),
        'solution_code': (
            'Format.printf "@[<h>[ %d, %d, %d ]@]@." 1 2 3;;\n'
        ),
        'expected_output': '[ 1, 2, 3 ]',
    },
    {
        'slug': 'first-class-modules',
        'order': 600,
        'title': 'First-class modules',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Modules as values\n\n'
            'Wrap a module in a value with `(module M : S)`, unpack '
            'with `let module N = (val v) in ...`. Useful when the '
            'module choice is runtime data.\n\n'
            '**Task.** Pack `IntShow` (defined inline) into a value '
            'of type `(module SHOW with type t = int)` and call '
            '`show 41` through it.'
        ),
        'starter_code': (
            'module type SHOW = sig type t val show : t -> string end;;\n'
            'module IntShow : SHOW with type t = int = struct\n'
            '  type t = int let show = string_of_int\n'
            'end;;\n'
            'let v = (module IntShow : SHOW with type t = int) in\n'
            'let module M = (val v) in\n'
            'print_endline (M.show 0);;\n'
        ),
        'solution_code': (
            'module type SHOW = sig type t val show : t -> string end;;\n'
            'module IntShow : SHOW with type t = int = struct\n'
            '  type t = int let show = string_of_int\n'
            'end;;\n'
            'let v = (module IntShow : SHOW with type t = int) in\n'
            'let module M = (val v) in\n'
            'print_endline (M.show 41);;\n'
        ),
        'expected_output': '41',
    },
    {
        'slug': 'gadts',
        'order': 620,
        'title': 'GADTs (a taste)',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Generalised Algebraic Data Types\n\n'
            'GADTs let constructors fix the type parameter:\n\n'
            '```\ntype _ tag =\n'
            '  | TInt    : int tag\n'
            '  | TString : string tag\n```\n\n'
            'A function `to_string : \'a tag -> \'a -> string` can '
            'switch on the tag and have the type of `x` line up.\n\n'
            '**Task.** Implement `to_string` for `TInt`/`TString` and '
            'print `to_string TInt 7` then `to_string TString "hi"`.'
        ),
        'starter_code': (
            'type _ tag = TInt : int tag | TString : string tag;;\n'
            'let to_string : type a. a tag -> a -> string =\n'
            '  fun _ _ -> "?"\n'
            'in\n'
            'print_endline (to_string TInt 7);\n'
            'print_endline (to_string TString "hi");;\n'
        ),
        'solution_code': (
            'type _ tag = TInt : int tag | TString : string tag;;\n'
            'let to_string : type a. a tag -> a -> string =\n'
            '  fun t v -> match t with\n'
            '    | TInt -> string_of_int v\n'
            '    | TString -> v\n'
            'in\n'
            'print_endline (to_string TInt 7);\n'
            'print_endline (to_string TString "hi");;\n'
        ),
        'expected_output': '7\nhi',
    },
    {
        'slug': 'string-of-int-ladder',
        'order': 700,
        'title': 'Stdlib string conversions',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Round-tripping numbers\n\n'
            '`string_of_int`, `int_of_string`, `string_of_float`, '
            '`float_of_string`. The string-of forms are total; the '
            'inverse direction raises `Failure` on bad input.\n\n'
            '**Task.** Parse `"42"` to int, multiply by 2, print as a string.'
        ),
        'starter_code': (
            'let n = 0 in\n'
            'print_endline (string_of_int n);;\n'
        ),
        'solution_code': (
            'let n = int_of_string "42" * 2 in\n'
            'print_endline (string_of_int n);;\n'
        ),
        'expected_output': '84',
    },
    {
        'slug': 'list-find-opt',
        'order': 730,
        'title': 'Option-returning lookups',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Avoiding exceptions\n\n'
            'Stdlib offers `*_opt` variants for partial functions: '
            '`List.find_opt`, `Hashtbl.find_opt`, `int_of_string_opt`. '
            'Prefer these over `try`/`with` for ordinary control flow.\n\n'
            '**Task.** Print the first even of `[1;3;5;6;7]` using '
            '`find_opt` and a match.'
        ),
        'starter_code': (
            'match List.find_opt (fun x -> x mod 2 = 0) [1;3;5;6;7] with\n'
            '| Some n -> Printf.printf "%d\\n" 0\n'
            '| None   -> print_endline "no even";;\n'
        ),
        'solution_code': (
            'match List.find_opt (fun x -> x mod 2 = 0) [1;3;5;6;7] with\n'
            '| Some n -> Printf.printf "%d\\n" n\n'
            '| None   -> print_endline "no even";;\n'
        ),
        'expected_output': '6',
    },
    {
        'slug': 'streams-fibonacci',
        'order': 760,
        'title': 'Lazy infinite Fibonacci',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Infinite Fibonacci as a Seq\n\n'
            '`Seq.unfold` makes infinite sequences trivial. The state '
            'is `(a, b)`; emit `a`, advance to `(b, a+b)`.\n\n'
            '**Task.** Build the Fibonacci sequence and print the '
            'first 10 with iter.'
        ),
        'starter_code': (
            'let fibs = Seq.unfold (fun (a, b) -> Some (a, (b, a + b))) (0, 1) in\n'
            'Seq.take 0 fibs |> Seq.iter (Printf.printf "%d ");\n'
            'print_endline ""\n;;\n'
        ),
        'solution_code': (
            'let fibs = Seq.unfold (fun (a, b) -> Some (a, (b, a + b))) (0, 1) in\n'
            'Seq.take 10 fibs |> Seq.iter (Printf.printf "%d ");\n'
            'print_endline ""\n;;\n'
        ),
        'expected_output': '0 1 1 2 3 5 8 13 21 34 ',
    },
    {
        'slug': 'extensible-types',
        'order': 800,
        'title': 'Extensible variants',
        'difficulty': 'advanced',
        'prompt_md': (
            '## type t = ..\n\n'
            'Open variant types accept new constructors anywhere:\n\n'
            '```\ntype shape = ..\n'
            'type shape += Circle of float\n'
            'type shape += Square of float\n```\n\n'
            'Used by OCaml\'s extensible `exn` type and effect '
            'declarations.\n\n'
            '**Task.** Declare extensible `shape`, add `Circle` and '
            '`Square`, write `area` returning `0.0` for unknown '
            'cases, and print `area (Circle 1.0)`.'
        ),
        'starter_code': (
            'type shape = ..\n'
            'type shape += Circle of float\n'
            'type shape += Square of float;;\n'
            'let area = function _ -> 0.0 in\n'
            'Printf.printf "%.5f\\n" (area (Circle 1.0));;\n'
        ),
        'solution_code': (
            'type shape = ..\n'
            'type shape += Circle of float\n'
            'type shape += Square of float;;\n'
            'let area = function\n'
            '  | Circle r -> 3.14159 *. r *. r\n'
            '  | Square s -> s *. s\n'
            '  | _ -> 0.0\n'
            'in\n'
            'Printf.printf "%.5f\\n" (area (Circle 1.0));;\n'
        ),
        'expected_output': '3.14159',
    },
    {
        'slug': 'private-types',
        'order': 820,
        'title': 'Private types (smart constructors)',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Read-only abstract types\n\n'
            'A `private` type lets clients see the structure but not '
            'construct it directly — useful for invariants:\n\n'
            '```\nmodule Even : sig\n'
            '  type t = private int\n'
            '  val make : int -> t option\n'
            'end = struct\n'
            '  type t = int\n'
            '  let make n = if n mod 2 = 0 then Some n else None\n'
            'end\n```\n\n'
            '**Task.** Create an `Even` module, build `Even.make 10`, '
            'and print its int.'
        ),
        'starter_code': (
            'module Even : sig\n'
            '  type t = private int\n'
            '  val make : int -> t option\n'
            'end = struct\n'
            '  type t = int\n'
            '  let make n = None\n'
            'end;;\n'
            '(match Even.make 10 with\n'
            ' | Some e -> Printf.printf "%d\\n" (e :> int)\n'
            ' | None -> print_endline "odd");;\n'
        ),
        'solution_code': (
            'module Even : sig\n'
            '  type t = private int\n'
            '  val make : int -> t option\n'
            'end = struct\n'
            '  type t = int\n'
            '  let make n = if n mod 2 = 0 then Some n else None\n'
            'end;;\n'
            '(match Even.make 10 with\n'
            ' | Some e -> Printf.printf "%d\\n" (e :> int)\n'
            ' | None -> print_endline "odd");;\n'
        ),
        'expected_output': '10',
    },
    {
        'slug': 'effect-handlers-mention',
        'order': 900,
        'title': 'Effect handlers (OCaml 5)',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Algebraic effects\n\n'
            'OCaml 5 ships effect handlers — algebraic effects without '
            'the monadic plumbing. The shape:\n\n'
            '```\ntype _ Effect.t += Ask : int Effect.t\n'
            'let _ = Effect.Deep.try_with body () { effc = ... }\n```\n\n'
            'For now just print a marker that you encountered the '
            'topic — running effect handlers needs OCaml ≥ 5.\n\n'
            '**Task.** Print `effects-noted`.'
        ),
        'starter_code': 'print_endline "todo";;\n',
        'solution_code': 'print_endline "effects-noted";;\n',
        'expected_output': 'effects-noted',
    },
    {
        'slug': 'multicore-mention',
        'order': 910,
        'title': 'Multicore (Domain)',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Domains — parallel CPUs\n\n'
            'OCaml 5 introduces `Domain.spawn`, real parallel execution '
            'on multi-core machines:\n\n'
            '```\nlet d = Domain.spawn (fun () -> heavy_compute ()) in\n'
            'let r = Domain.join d\n```\n\n'
            'Like effects, this needs OCaml ≥ 5 to actually run.\n\n'
            '**Task.** Print `multicore-noted`.'
        ),
        'starter_code': 'print_endline "todo";;\n',
        'solution_code': 'print_endline "multicore-noted";;\n',
        'expected_output': 'multicore-noted',
    },
    {
        'slug': 'phantom-types',
        'order': 950,
        'title': 'Phantom types',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Tags that exist only for the typechecker\n\n'
            'A type parameter not used in the runtime representation '
            'is *phantom* — but the compiler still tracks it. Useful '
            'for distinguishing values that share a representation:\n\n'
            '```\ntype _ length = int\n'
            'let mm (n : [`Mm] length) : [`Mm] length = n\n```\n\n'
            'You can\'t accidentally pass `[`Inch] length` where '
            '`[`Mm] length` is expected.\n\n'
            '**Task.** Just print `phantom-ok`.'
        ),
        'starter_code': 'print_endline "todo";;\n',
        'solution_code': 'print_endline "phantom-ok";;\n',
        'expected_output': 'phantom-ok',
    },
    {
        'slug': 'open-recursion',
        'order': 970,
        'title': 'Open recursion via parameters',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Reusing a recursive function\n\n'
            'Take the recursive call as a parameter — like the `fix` '
            'lesson, but the goal is *extension*. You can wrap an '
            'existing implementation by passing in a new "self":\n\n'
            '```\nlet make_eval rec_eval = function\n'
            '  | Add (a, b) -> rec_eval a + rec_eval b\n'
            '  | Num n -> n\n```\n\n'
            'Then `let rec eval x = make_eval eval x` is the closed '
            'form, and you can shim a tracing version that delegates.\n\n'
            '**Task.** Implement `make_eval` and tie the knot. Eval '
            '`Add (Num 19, Num 23)` and print.'
        ),
        'starter_code': (
            'type expr = Num of int | Add of expr * expr;;\n'
            'let make_eval _rec_eval = function _ -> 0 in\n'
            'let rec eval x = make_eval eval x in\n'
            'Printf.printf "%d\\n" (eval (Add (Num 19, Num 23)));;\n'
        ),
        'solution_code': (
            'type expr = Num of int | Add of expr * expr;;\n'
            'let make_eval rec_eval = function\n'
            '  | Num n -> n\n'
            '  | Add (a, b) -> rec_eval a + rec_eval b\n'
            'in\n'
            'let rec eval x = make_eval eval x in\n'
            'Printf.printf "%d\\n" (eval (Add (Num 19, Num 23)));;\n'
        ),
        'expected_output': '42',
    },

    # ─── BASIC: format & I/O conveniences ─────────────────────────
    {
        'slug': 'printf-specifiers',
        'order': 27,
        'title': 'Printf format specifiers',
        'difficulty': 'basic',
        'prompt_md': (
            '## Printf, in more detail\n\n'
            '`%d` int, `%s` string, `%f` float (`%.2f` → 2 decimals), '
            '`%b` bool, `%c` char, `%x` hex int. Format strings are '
            'type-checked at compile time.\n\n'
            '**Task.** Print `42 ham 3.14 true Z 2a` on one line, '
            'space-separated.'
        ),
        'starter_code': 'Printf.printf "%d %s %.2f %b %c %x\\n" 0 "" 0.0 false \' \' 0;;\n',
        'solution_code': 'Printf.printf "%d %s %.2f %b %c %x\\n" 42 "ham" 3.14 true \'Z\' 42;;\n',
        'expected_output': '42 ham 3.14 true Z 2a',
    },
    {
        'slug': 'sprintf',
        'order': 29,
        'title': 'sprintf — Printf into a string',
        'difficulty': 'basic',
        'prompt_md': (
            '## Build strings, do not print them\n\n'
            '`Printf.sprintf` returns a string instead of writing to '
            'stdout. Same format string semantics.\n\n'
            '**Task.** Build the string `"x=42, y=99"` with sprintf '
            'and print it.'
        ),
        'starter_code': 'let s = Printf.sprintf "x=%d, y=%d" 0 0 in\nprint_endline s;;\n',
        'solution_code': 'let s = Printf.sprintf "x=%d, y=%d" 42 99 in\nprint_endline s;;\n',
        'expected_output': 'x=42, y=99',
    },
    {
        'slug': 'read-line-mention',
        'order': 31,
        'title': 'Reading input (read_line)',
        'difficulty': 'basic',
        'prompt_md': (
            '## Reading stdin\n\n'
            '`read_line ()` reads one line of input (without the '
            'trailing newline). `read_int ()` parses it as an int.\n\n'
            'The Camlfornia runner does not pipe stdin, so we will '
            'just *describe* the call rather than execute it.\n\n'
            '**Task.** Print `read_line: skipped`.'
        ),
        'starter_code': 'print_endline "todo";;\n',
        'solution_code': 'print_endline "read_line: skipped";;\n',
        'expected_output': 'read_line: skipped',
    },
    {
        'slug': 'while-loops',
        'order': 33,
        'title': 'While loops',
        'difficulty': 'basic',
        'prompt_md': (
            '## while ... do ... done\n\n'
            'OCaml has imperative loops: `while cond do body done` '
            'and `for i = a to b do body done`. Both return `unit`.\n\n'
            '**Task.** Use a `while` loop with a ref counter to print '
            '`1 2 3 4 5` (space-separated, trailing newline).'
        ),
        'starter_code': (
            'let i = ref 1 in\n'
            'while false do () done;\n'
            'print_endline ""\n;;\n'
        ),
        'solution_code': (
            'let i = ref 1 in\n'
            'while !i <= 5 do\n'
            '  Printf.printf "%d " !i; incr i\n'
            'done;\n'
            'print_endline ""\n;;\n'
        ),
        'expected_output': '1 2 3 4 5 ',
    },
    {
        'slug': 'if-as-expression',
        'order': 35,
        'title': 'if returns a value',
        'difficulty': 'basic',
        'prompt_md': (
            '## if/then/else is an expression\n\n'
            'The whole `if c then a else b` is itself a value — both '
            'branches must have the same type.\n\n'
            '**Task.** Use `if` inline to bind `label = "even"` or '
            '`"odd"` for `n = 7` and print it.'
        ),
        'starter_code': (
            'let n = 7 in\n'
            'let label = "?" in\n'
            'print_endline label;;\n'
        ),
        'solution_code': (
            'let n = 7 in\n'
            'let label = if n mod 2 = 0 then "even" else "odd" in\n'
            'print_endline label;;\n'
        ),
        'expected_output': 'odd',
    },

    # ─── INTERMEDIATE: more list helpers ──────────────────────────
    {
        'slug': 'list-exists-forall',
        'order': 168,
        'title': 'List.exists, List.for_all',
        'difficulty': 'interm',
        'prompt_md': (
            '## ∃ and ∀ over a list\n\n'
            '`List.exists pred xs` returns `true` if any element '
            'satisfies `pred`. `List.for_all pred xs` is the dual.\n\n'
            '**Task.** Print whether `[2;4;6;7]` contains an odd '
            'number — print `has-odd` or `all-even`.'
        ),
        'starter_code': (
            'let xs = [2;4;6;7] in\n'
            'print_endline (if false then "has-odd" else "all-even");;\n'
        ),
        'solution_code': (
            'let xs = [2;4;6;7] in\n'
            'print_endline (if List.exists (fun x -> x mod 2 = 1) xs\n'
            '               then "has-odd" else "all-even");;\n'
        ),
        'expected_output': 'has-odd',
    },
    {
        'slug': 'list-assoc',
        'order': 172,
        'title': 'Association lists',
        'difficulty': 'interm',
        'prompt_md': (
            '## (key, value) lists\n\n'
            '`List.assoc k xs` returns the value paired with `k` (or '
            'raises). `List.assoc_opt` is the safer variant.\n\n'
            '**Task.** Look up `"two"` in `[("one",1);("two",2);("three",3)]` '
            'and print the value.'
        ),
        'starter_code': (
            'let dict = [("one",1);("two",2);("three",3)] in\n'
            'Printf.printf "%d\\n" 0;;\n'
        ),
        'solution_code': (
            'let dict = [("one",1);("two",2);("three",3)] in\n'
            'Printf.printf "%d\\n" (List.assoc "two" dict);;\n'
        ),
        'expected_output': '2',
    },
    {
        'slug': 'list-combine-split',
        'order': 174,
        'title': 'List.combine & List.split',
        'difficulty': 'interm',
        'prompt_md': (
            '## Zip and unzip\n\n'
            '`List.combine [1;2] ["a";"b"]` → `[(1,"a");(2,"b")]`. '
            '`List.split` is the inverse, returning a pair of lists.\n\n'
            '**Task.** Combine `[1;2;3]` with `["a";"b";"c"]`, then '
            'pull out just the strings via `split` and print them.'
        ),
        'starter_code': (
            'let pairs = List.combine [1;2;3] ["a";"b";"c"] in\n'
            'let (_, _strs) = List.split pairs in\n'
            'List.iter print_endline [];;\n'
        ),
        'solution_code': (
            'let pairs = List.combine [1;2;3] ["a";"b";"c"] in\n'
            'let (_, strs) = List.split pairs in\n'
            'List.iter print_endline strs;;\n'
        ),
        'expected_output': 'a\nb\nc',
    },
    {
        'slug': 'list-sort',
        'order': 176,
        'title': 'List.sort',
        'difficulty': 'interm',
        'prompt_md': (
            '## Sorting\n\n'
            '`List.sort cmp xs` returns a new sorted list. `cmp` '
            'returns negative/zero/positive — the polymorphic '
            '`compare` works for most types.\n\n'
            '**Task.** Sort `[3;1;4;1;5;9;2;6]` ascending and print.'
        ),
        'starter_code': (
            'let xs = [3;1;4;1;5;9;2;6] in\n'
            'let sorted = xs in\n'
            'List.iter (Printf.printf "%d ") sorted;\n'
            'print_endline ""\n;;\n'
        ),
        'solution_code': (
            'let xs = [3;1;4;1;5;9;2;6] in\n'
            'let sorted = List.sort compare xs in\n'
            'List.iter (Printf.printf "%d ") sorted;\n'
            'print_endline ""\n;;\n'
        ),
        'expected_output': '1 1 2 3 4 5 6 9 ',
    },
    {
        'slug': 'list-partition',
        'order': 178,
        'title': 'List.partition',
        'difficulty': 'interm',
        'prompt_md': (
            '## Split by predicate\n\n'
            '`List.partition p xs` → `(matches, others)`. One pass.\n\n'
            '**Task.** Partition `[1;2;3;4;5;6]` into evens and odds; '
            'print `evens=[2;4;6] odds=[1;3;5]` (with `Printf.printf` '
            'and `List.iter`).'
        ),
        'starter_code': (
            'let xs = [1;2;3;4;5;6] in\n'
            'let (evens, odds) = ([], []) in\n'
            'Printf.printf "evens=[";\n'
            'List.iter (Printf.printf "%d;") evens;\n'
            'Printf.printf "] odds=[";\n'
            'List.iter (Printf.printf "%d;") odds;\n'
            'Printf.printf "]\\n";;\n'
        ),
        'solution_code': (
            'let xs = [1;2;3;4;5;6] in\n'
            'let (evens, odds) = List.partition (fun x -> x mod 2 = 0) xs in\n'
            'Printf.printf "evens=[";\n'
            'List.iter (Printf.printf "%d;") evens;\n'
            'Printf.printf "] odds=[";\n'
            'List.iter (Printf.printf "%d;") odds;\n'
            'Printf.printf "]\\n";;\n'
        ),
        'expected_output': 'evens=[2;4;6;] odds=[1;3;5;]',
    },

    # ─── INTERMEDIATE: pattern features ───────────────────────────
    {
        'slug': 'when-guards',
        'order': 192,
        'title': 'When guards in matches',
        'difficulty': 'interm',
        'prompt_md': (
            '## Boolean filters on patterns\n\n'
            'Add `when expr` to a pattern arm to require an extra '
            'predicate. Useful when one pattern would otherwise '
            'duplicate too much.\n\n'
            '**Task.** Classify an int as `"big"` (>100), `"medium"` '
            '(>10), or `"small"` (anything else) using `when`. Print '
            'the result for `n = 50`.'
        ),
        'starter_code': (
            'let classify n = "?" in\n'
            'print_endline (classify 50);;\n'
        ),
        'solution_code': (
            'let classify n = match n with\n'
            '  | n when n > 100 -> "big"\n'
            '  | n when n > 10  -> "medium"\n'
            '  | _              -> "small"\n'
            'in\n'
            'print_endline (classify 50);;\n'
        ),
        'expected_output': 'medium',
    },
    {
        'slug': 'as-patterns',
        'order': 194,
        'title': 'As-patterns',
        'difficulty': 'interm',
        'prompt_md': (
            '## Bind a sub-pattern AND its parts\n\n'
            '`x :: rest as whole` matches a non-empty list and binds '
            'both the parts and the whole list to `whole`. Useful when '
            'you need both views.\n\n'
            '**Task.** Match `[1;2;3]` with `(x :: _) as whole` and '
            'print `head=1 length=3`.'
        ),
        'starter_code': (
            'match [1;2;3] with\n'
            '| _ as whole -> Printf.printf "head=%d length=%d\\n" 0 (List.length whole)\n'
            '| _ -> ();;\n'
        ),
        'solution_code': (
            'match [1;2;3] with\n'
            '| (x :: _) as whole -> Printf.printf "head=%d length=%d\\n" x (List.length whole)\n'
            '| _ -> ();;\n'
        ),
        'expected_output': 'head=1 length=3',
    },
    {
        'slug': 'or-patterns',
        'order': 196,
        'title': 'Or-patterns',
        'difficulty': 'interm',
        'prompt_md': (
            '## Multiple patterns, one body\n\n'
            'Combine patterns with `|` inside a single arm:\n\n'
            '```\nmatch c with\n  | \'a\' | \'e\' | \'i\' | \'o\' | \'u\' -> "vowel"\n  | _ -> "consonant"\n```\n\n'
            'All branches in an or-pattern must bind the same '
            'variables.\n\n'
            '**Task.** Classify `\'e\'` as vowel/consonant.'
        ),
        'starter_code': (
            'let kind c = "?" in\n'
            'print_endline (kind \'e\');;\n'
        ),
        'solution_code': (
            'let kind c = match c with\n'
            '  | \'a\' | \'e\' | \'i\' | \'o\' | \'u\' -> "vowel"\n'
            '  | _ -> "consonant"\n'
            'in\n'
            'print_endline (kind \'e\');;\n'
        ),
        'expected_output': 'vowel',
    },
    {
        'slug': 'local-open',
        'order': 198,
        'title': 'Local open (let open M in)',
        'difficulty': 'interm',
        'prompt_md': (
            '## Bring names into scope locally\n\n'
            '`let open List in [1;2;3] |> map ...` brings `List`\'s '
            'names into the body of the expression, leaving the rest '
            'of the file unaffected. Also written `List.([1;2;3] |> map ...)`.\n\n'
            '**Task.** Use `let open List` to map `(*)2` over '
            '`[1;2;3]` and print the sum.'
        ),
        'starter_code': (
            'let xs = [1;2;3] in\n'
            'let total = 0 in\n'
            'Printf.printf "%d\\n" total;;\n'
        ),
        'solution_code': (
            'let xs = [1;2;3] in\n'
            'let total =\n'
            '  let open List in\n'
            '  fold_left (+) 0 (map (fun x -> x * 2) xs)\n'
            'in\n'
            'Printf.printf "%d\\n" total;;\n'
        ),
        'expected_output': '12',
    },

    # ─── INTERMEDIATE: more strings / Bytes / Buffer ──────────────
    {
        'slug': 'string-iter-map',
        'order': 230,
        'title': 'String.iter & String.map',
        'difficulty': 'interm',
        'prompt_md': (
            '## Walking a string\n\n'
            '`String.iter f s` calls `f` on each char. `String.map f s` '
            'returns a new string.\n\n'
            '**Task.** Uppercase the ASCII letters of `"hello"` with '
            '`String.map` and `Char.uppercase_ascii`.'
        ),
        'starter_code': (
            'let s = "hello" in\n'
            'let up = s in\n'
            'print_endline up;;\n'
        ),
        'solution_code': (
            'let s = "hello" in\n'
            'let up = String.map Char.uppercase_ascii s in\n'
            'print_endline up;;\n'
        ),
        'expected_output': 'HELLO',
    },
    {
        'slug': 'buffer',
        'order': 234,
        'title': 'Buffer — efficient string building',
        'difficulty': 'interm',
        'prompt_md': (
            '## Building strings without quadratic blowup\n\n'
            '`Buffer.create 16` allocates a growable buffer. '
            '`Buffer.add_string b s`, `Buffer.add_char`, then '
            '`Buffer.contents` to materialise.\n\n'
            '**Task.** Build `"a-b-c"` by appending to a Buffer and '
            'print the result.'
        ),
        'starter_code': (
            'let b = Buffer.create 16 in\n'
            'print_endline (Buffer.contents b);;\n'
        ),
        'solution_code': (
            'let b = Buffer.create 16 in\n'
            'Buffer.add_string b "a";\n'
            'Buffer.add_char b \'-\';\n'
            'Buffer.add_string b "b";\n'
            'Buffer.add_char b \'-\';\n'
            'Buffer.add_string b "c";\n'
            'print_endline (Buffer.contents b);;\n'
        ),
        'expected_output': 'a-b-c',
    },
    {
        'slug': 'bytes',
        'order': 236,
        'title': 'Bytes — mutable strings',
        'difficulty': 'interm',
        'prompt_md': (
            '## Mutable byte sequences\n\n'
            '`Bytes.t` is a mutable string. Convert with `Bytes.of_string` '
            '/ `Bytes.to_string`. Mutate with `Bytes.set b i c`.\n\n'
            '**Task.** Take `"hello"`, change the first byte to `H`, '
            'and print the result.'
        ),
        'starter_code': (
            'let b = Bytes.of_string "hello" in\n'
            'print_endline (Bytes.to_string b);;\n'
        ),
        'solution_code': (
            'let b = Bytes.of_string "hello" in\n'
            'Bytes.set b 0 \'H\';\n'
            'print_endline (Bytes.to_string b);;\n'
        ),
        'expected_output': 'Hello',
    },

    # ─── INTERMEDIATE: more stdlib + Random ───────────────────────
    {
        'slug': 'option-module',
        'order': 270,
        'title': 'Option module helpers',
        'difficulty': 'interm',
        'prompt_md': (
            '## Stdlib Option functions\n\n'
            '`Option.value o ~default:d` extracts or substitutes. '
            '`Option.map`, `Option.bind` chain on present values. '
            '`Option.is_some`, `Option.is_none` are the predicates.\n\n'
            '**Task.** With `o = Some 41`, use `Option.map (+ 1)` and '
            '`Option.value ~default:0` to print `42`.'
        ),
        'starter_code': (
            'let o = Some 41 in\n'
            'let v = Option.value o ~default:0 in\n'
            'Printf.printf "%d\\n" v;;\n'
        ),
        'solution_code': (
            'let o = Some 41 in\n'
            'let v = Option.value (Option.map (fun x -> x + 1) o) ~default:0 in\n'
            'Printf.printf "%d\\n" v;;\n'
        ),
        'expected_output': '42',
    },
    {
        'slug': 'result-bind',
        'order': 274,
        'title': 'Result.bind chains',
        'difficulty': 'interm',
        'prompt_md': (
            '## Chaining failable steps\n\n'
            '`Result.bind r f` runs `f` on `Ok` values, propagates '
            '`Error` unchanged. Mirrors `Option.bind` for the carry-'
            'an-error case.\n\n'
            '**Task.** Chain two `safe_div` calls so `(100 / 2) / 5` '
            'returns `Ok 10`. Print `got 10`.'
        ),
        'starter_code': (
            'let safe_div a b = if b = 0 then Error "/0" else Ok (a / b) in\n'
            'let r = Result.bind (safe_div 100 2) (fun q -> safe_div q 5) in\n'
            '(match r with\n'
            ' | Ok v -> Printf.printf "got %d\\n" 0\n'
            ' | Error e -> Printf.printf "err: %s\\n" e);;\n'
        ),
        'solution_code': (
            'let safe_div a b = if b = 0 then Error "/0" else Ok (a / b) in\n'
            'let r = Result.bind (safe_div 100 2) (fun q -> safe_div q 5) in\n'
            '(match r with\n'
            ' | Ok v -> Printf.printf "got %d\\n" v\n'
            ' | Error e -> Printf.printf "err: %s\\n" e);;\n'
        ),
        'expected_output': 'got 10',
    },
    {
        'slug': 'random',
        'order': 350,
        'title': 'Random module',
        'difficulty': 'interm',
        'prompt_md': (
            '## Pseudo-random numbers\n\n'
            '`Random.init seed` for reproducibility. `Random.int n` '
            'returns `0..n-1`. With a fixed seed the output is '
            'deterministic.\n\n'
            '**Task.** Seed with 42, then print four `Random.int 100` '
            'values space-separated.'
        ),
        'starter_code': (
            'Random.init 42;\n'
            'Printf.printf "%d %d %d %d\\n" 0 0 0 0;;\n'
        ),
        'solution_code': (
            'Random.init 42;\n'
            'let a = Random.int 100 in\n'
            'let b = Random.int 100 in\n'
            'let c = Random.int 100 in\n'
            'let d = Random.int 100 in\n'
            'Printf.printf "%d %d %d %d\\n" a b c d;;\n'
        ),
        'expected_output': '',  # nondeterministic across OCaml versions
    },
    {
        'slug': 'hashtbl-iter',
        'order': 355,
        'title': 'Iterating a Hashtbl',
        'difficulty': 'interm',
        'prompt_md': (
            '## Walking entries\n\n'
            '`Hashtbl.iter (fun k v -> ...) h` visits every binding. '
            'Order is unspecified.\n\n'
            '**Task.** Build a hashtable with three entries and print '
            'the sum of its values (just print the sum).'
        ),
        'starter_code': (
            'let h = Hashtbl.create 8 in\n'
            'Hashtbl.add h "a" 10;\n'
            'Hashtbl.add h "b" 20;\n'
            'Hashtbl.add h "c" 12;\n'
            'let total = ref 0 in\n'
            'Hashtbl.iter (fun _ _ -> ()) h;\n'
            'Printf.printf "%d\\n" !total;;\n'
        ),
        'solution_code': (
            'let h = Hashtbl.create 8 in\n'
            'Hashtbl.add h "a" 10;\n'
            'Hashtbl.add h "b" 20;\n'
            'Hashtbl.add h "c" 12;\n'
            'let total = ref 0 in\n'
            'Hashtbl.iter (fun _ v -> total := !total + v) h;\n'
            'Printf.printf "%d\\n" !total;;\n'
        ),
        'expected_output': '42',
    },

    # ─── ADVANCED extras ──────────────────────────────────────────
    {
        'slug': 'mergesort',
        'order': 540,
        'title': 'Merge sort',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Divide and conquer\n\n'
            'Split a list in half, sort each, then merge. Each step '
            'is itself pattern-matching:\n\n'
            '```\nlet rec merge xs ys = match xs, ys with\n'
            '  | [], r | r, [] -> r\n'
            '  | x :: xt, y :: yt ->\n'
            '      if x <= y then x :: merge xt ys else y :: merge xs yt\n```\n\n'
            '**Task.** Implement `merge` and `mergesort`, sort '
            '`[3;1;4;1;5;9;2;6;5;3;5]`, and print result.'
        ),
        'starter_code': (
            'let rec merge xs ys = xs @ ys in\n'
            'let rec split = function _ -> ([], []) in\n'
            'let rec mergesort xs = xs in\n'
            'List.iter (Printf.printf "%d ") (mergesort [3;1;4;1;5;9;2;6;5;3;5]);\n'
            'print_endline ""\n;;\n'
        ),
        'solution_code': (
            'let rec merge xs ys = match xs, ys with\n'
            '  | [], r | r, [] -> r\n'
            '  | x :: xt, y :: yt ->\n'
            '      if x <= y then x :: merge xt ys else y :: merge xs yt\n'
            'in\n'
            'let rec split = function\n'
            '  | [] -> [], []\n'
            '  | [x] -> [x], []\n'
            '  | x :: y :: rest -> let l, r = split rest in x :: l, y :: r\n'
            'in\n'
            'let rec mergesort = function\n'
            '  | ([] | [_]) as xs -> xs\n'
            '  | xs -> let l, r = split xs in merge (mergesort l) (mergesort r)\n'
            'in\n'
            'List.iter (Printf.printf "%d ") (mergesort [3;1;4;1;5;9;2;6;5;3;5]);\n'
            'print_endline ""\n;;\n'
        ),
        'expected_output': '1 1 2 3 3 4 5 5 5 6 9 ',
    },
    {
        'slug': 'reader-monad',
        'order': 525,
        'title': 'Reader monad',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Threading a config\n\n'
            'A reader action is `\'env -> \'a`. `bind m f env = f (m env) env`. '
            '`ask env = env`. Useful for plumbing a settings record without '
            'mutation.\n\n'
            '**Task.** Use a reader action to fetch the env (an int) '
            'and add 5. Run it with env=10 and print the result.'
        ),
        'starter_code': (
            'let return a = fun _ -> a in\n'
            'let bind m f = fun env -> f (m env) env in\n'
            'let ask = fun env -> env in\n'
            'let action = bind ask (fun n -> return n) in\n'
            'Printf.printf "%d\\n" (action 10);;\n'
        ),
        'solution_code': (
            'let return a = fun _ -> a in\n'
            'let bind m f = fun env -> f (m env) env in\n'
            'let ask = fun env -> env in\n'
            'let action = bind ask (fun n -> return (n + 5)) in\n'
            'Printf.printf "%d\\n" (action 10);;\n'
        ),
        'expected_output': '15',
    },
    {
        'slug': 'parser-sequence',
        'order': 565,
        'title': 'Parser combinators — sequence',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Sequencing two parsers\n\n'
            'Building on the earlier `digit` parser, define '
            '`( *> ) p q` that runs `p`, discards its result, runs '
            '`q`, returns `q`\'s result.\n\n'
            '**Task.** Parse a digit then another digit at offset 0 '
            'of `"42x"`. Print the second digit.'
        ),
        'starter_code': (
            'let digit s i =\n'
            '  if i < String.length s && s.[i] >= \'0\' && s.[i] <= \'9\'\n'
            '  then Some (Char.code s.[i] - Char.code \'0\', i + 1)\n'
            '  else None\n'
            'in\n'
            'let ( *> ) p q s i =\n'
            '  match p s i with\n'
            '  | Some (_, j) -> None  (* TODO *)\n'
            '  | None -> None\n'
            'in\n'
            '(match (digit *> digit) "42x" 0 with\n'
            ' | Some (n, _) -> Printf.printf "%d\\n" n\n'
            ' | None -> print_endline "fail");;\n'
        ),
        'solution_code': (
            'let digit s i =\n'
            '  if i < String.length s && s.[i] >= \'0\' && s.[i] <= \'9\'\n'
            '  then Some (Char.code s.[i] - Char.code \'0\', i + 1)\n'
            '  else None\n'
            'in\n'
            'let ( *> ) p q s i =\n'
            '  match p s i with\n'
            '  | Some (_, j) -> q s j\n'
            '  | None -> None\n'
            'in\n'
            '(match (digit *> digit) "42x" 0 with\n'
            ' | Some (n, _) -> Printf.printf "%d\\n" n\n'
            ' | None -> print_endline "fail");;\n'
        ),
        'expected_output': '2',
    },
    {
        'slug': 'parser-alt',
        'order': 568,
        'title': 'Parser combinators — alternation',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Either / or\n\n'
            'Define `( <|> ) p q` that tries `p`; if it fails, tries '
            '`q` on the original offset.\n\n'
            '**Task.** With a `letter` and a `digit` parser, build '
            '`token = letter <|> digit`, run on `"7"` and print.'
        ),
        'starter_code': (
            'let digit s i =\n'
            '  if i < String.length s && s.[i] >= \'0\' && s.[i] <= \'9\'\n'
            '  then Some (Char.code s.[i] - Char.code \'0\', i + 1)\n'
            '  else None\n'
            'in\n'
            'let letter s i =\n'
            '  if i < String.length s && s.[i] >= \'a\' && s.[i] <= \'z\'\n'
            '  then Some (Char.code s.[i], i + 1)\n'
            '  else None\n'
            'in\n'
            'let ( <|> ) p q s i = p s i in\n'
            '(match (letter <|> digit) "7" 0 with\n'
            ' | Some (n, _) -> Printf.printf "%d\\n" n\n'
            ' | None -> print_endline "fail");;\n'
        ),
        'solution_code': (
            'let digit s i =\n'
            '  if i < String.length s && s.[i] >= \'0\' && s.[i] <= \'9\'\n'
            '  then Some (Char.code s.[i] - Char.code \'0\', i + 1)\n'
            '  else None\n'
            'in\n'
            'let letter s i =\n'
            '  if i < String.length s && s.[i] >= \'a\' && s.[i] <= \'z\'\n'
            '  then Some (Char.code s.[i], i + 1)\n'
            '  else None\n'
            'in\n'
            'let ( <|> ) p q s i =\n'
            '  match p s i with\n'
            '  | Some _ as ok -> ok\n'
            '  | None -> q s i\n'
            'in\n'
            '(match (letter <|> digit) "7" 0 with\n'
            ' | Some (n, _) -> Printf.printf "%d\\n" n\n'
            ' | None -> print_endline "fail");;\n'
        ),
        'expected_output': '7',
    },
    {
        'slug': 'typechecker-mention',
        'order': 850,
        'title': 'Hindley-Milner — a sketch',
        'difficulty': 'advanced',
        'prompt_md': (
            '## Where types come from\n\n'
            'OCaml infers types via Hindley-Milner: walk the AST, '
            'generate constraints (`τ₁ = τ₂`), then unify them '
            'left-to-right. Polymorphism is introduced at `let`.\n\n'
            'A real implementation is hundreds of lines; the core '
            'unification routine is small. We just note it here so '
            'the curriculum has a name to point at.\n\n'
            '**Task.** Print `hm-noted`.'
        ),
        'starter_code': 'print_endline "todo";;\n',
        'solution_code': 'print_endline "hm-noted";;\n',
        'expected_output': 'hm-noted',
    },
    {
        'slug': 'json-mention',
        'order': 870,
        'title': 'JSON — a quick mention',
        'difficulty': 'advanced',
        'prompt_md': (
            '## JSON in OCaml\n\n'
            'No JSON in the stdlib. The community choice is `yojson` '
            '(or `jsonm` for streaming). A Yojson value is just a '
            'recursive variant; pattern-match to project.\n\n'
            'No external lib here, so we just print a marker.\n\n'
            '**Task.** Print `json-noted`.'
        ),
        'starter_code': 'print_endline "todo";;\n',
        'solution_code': 'print_endline "json-noted";;\n',
        'expected_output': 'json-noted',
    },
    {
        'slug': 'curriculum-end',
        'order': 999,
        'title': 'You have reached the end',
        'difficulty': 'advanced',
        'prompt_md': (
            '## 100 lessons in\n\n'
            'You have walked from `print_endline "Hello, world!"` '
            'through pattern-matching, modules, functors, GADTs, '
            'first-class modules, Church encodings, parser '
            'combinators, and a tiny interpreter built from a 6-line '
            'recursive type.\n\n'
            'There is more — effects, multicore, ppx, the full '
            'object system, monad transformers — but you have the '
            'shape of the language now.\n\n'
            '**Task.** Print `done`.'
        ),
        'starter_code': 'print_endline "todo";;\n',
        'solution_code': 'print_endline "done";;\n',
        'expected_output': 'done',
    },
]
