"""Seed a beginner OCaml curriculum for Camlfornia.

Each lesson is a short prompt + starter + solution + expected stdout.
Order is the canonical learning order; difficulty is mostly cosmetic.
"""

from django.core.management.base import BaseCommand

from camlfornia.models import Lesson


LESSONS = [
    {
        'slug':  'hello-world',
        'order': 10,
        'title': 'Hello, world',
        'difficulty': 'intro',
        'prompt_md': (
            '## Hello, OCaml\n\n'
            'OCaml ships with `print_endline` — it prints a string and then a '
            'newline. Every top-level expression ends with `;;` when typed into '
            'the toplevel (the `ocaml` REPL).\n\n'
            '**Task.** Print exactly `Hello, world!` (with the comma, and '
            'exclamation mark).'
        ),
        'starter_code': 'print_endline "Hello, OCaml!";;\n',
        'solution_code': 'print_endline "Hello, world!";;\n',
        'expected_output': 'Hello, world!',
    },
    {
        'slug':  'let-bindings',
        'order': 20,
        'title': 'Let bindings',
        'difficulty': 'intro',
        'prompt_md': (
            '## Values have names\n\n'
            '`let name = expr` binds a value to a name. OCaml infers the type; '
            'you rarely need to annotate.\n\n'
            'Use `Printf.printf "%d\\n" n` to print an integer.\n\n'
            '**Task.** Bind `x = 21` and `y = 2`, and print `x * y`.'
        ),
        'starter_code': (
            'let x = (* your value *) 0 in\n'
            'let y = (* your value *) 0 in\n'
            'Printf.printf "%d\\n" (x * y);;\n'
        ),
        'solution_code': (
            'let x = 21 in\n'
            'let y = 2 in\n'
            'Printf.printf "%d\\n" (x * y);;\n'
        ),
        'expected_output': '42',
    },
    {
        'slug':  'functions',
        'order': 30,
        'title': 'Functions',
        'difficulty': 'intro',
        'prompt_md': (
            '## Functions are values\n\n'
            'A function is just a `let` with parameters:\n\n'
            '```\nlet add a b = a + b\n```\n\n'
            'OCaml functions are curried — `add 3` is itself a function waiting '
            'for one more argument.\n\n'
            '**Task.** Define `square : int -> int` and print `square 7`.'
        ),
        'starter_code': (
            'let square x = (* ... *) 0;;\n\n'
            'Printf.printf "%d\\n" (square 7);;\n'
        ),
        'solution_code': (
            'let square x = x * x;;\n\n'
            'Printf.printf "%d\\n" (square 7);;\n'
        ),
        'expected_output': '49',
    },
    {
        'slug':  'if-then-else',
        'order': 40,
        'title': 'If / then / else',
        'difficulty': 'intro',
        'prompt_md': (
            '## Conditionals are expressions\n\n'
            '`if cond then a else b` returns a value — both branches must have '
            'the same type.\n\n'
            '**Task.** Write `sign n` returning the string `"neg"`, `"zero"`, '
            'or `"pos"`. Print `sign (-3)`, `sign 0`, and `sign 5`, one per '
            'line.'
        ),
        'starter_code': (
            'let sign n =\n'
            '  (* fill me in *)\n'
            '  "?";;\n\n'
            'print_endline (sign (-3));;\n'
            'print_endline (sign 0);;\n'
            'print_endline (sign 5);;\n'
        ),
        'solution_code': (
            'let sign n =\n'
            '  if n < 0 then "neg"\n'
            '  else if n = 0 then "zero"\n'
            '  else "pos";;\n\n'
            'print_endline (sign (-3));;\n'
            'print_endline (sign 0);;\n'
            'print_endline (sign 5);;\n'
        ),
        'expected_output': 'neg\nzero\npos',
    },
    {
        'slug':  'pattern-matching',
        'order': 50,
        'title': 'Pattern matching',
        'difficulty': 'basic',
        'prompt_md': (
            '## match ... with\n\n'
            'Pattern matching is OCaml\'s answer to big `if/else` ladders. '
            'Underscore `_` is the default case.\n\n'
            '```\nmatch x with\n| 0 -> "zero"\n| 1 -> "one"\n| _ -> "many"\n```\n\n'
            '**Task.** Write `day_name d` mapping 1..7 to Mon..Sun and anything '
            'else to `"?"`. Print the names for 3 and 8.'
        ),
        'starter_code': (
            'let day_name d = "?";;\n\n'
            'print_endline (day_name 3);;\n'
            'print_endline (day_name 8);;\n'
        ),
        'solution_code': (
            'let day_name d =\n'
            '  match d with\n'
            '  | 1 -> "Mon"\n'
            '  | 2 -> "Tue"\n'
            '  | 3 -> "Wed"\n'
            '  | 4 -> "Thu"\n'
            '  | 5 -> "Fri"\n'
            '  | 6 -> "Sat"\n'
            '  | 7 -> "Sun"\n'
            '  | _ -> "?";;\n\n'
            'print_endline (day_name 3);;\n'
            'print_endline (day_name 8);;\n'
        ),
        'expected_output': 'Wed\n?',
    },
    {
        'slug':  'lists',
        'order': 60,
        'title': 'Lists',
        'difficulty': 'basic',
        'prompt_md': (
            '## Linked lists\n\n'
            'OCaml lists are singly-linked, homogeneous: `[1; 2; 3]` or '
            '`1 :: 2 :: 3 :: []`. The empty list is `[]`; `::` is cons.\n\n'
            '`List.length`, `List.map`, `List.iter` live in the `List` module.\n\n'
            '**Task.** Build `[10; 20; 30; 40]` and print its sum on one line '
            'using `List.fold_left`.'
        ),
        'starter_code': (
            'let xs = [ (* ... *) ] in\n'
            'let total = List.fold_left (+) 0 xs in\n'
            'Printf.printf "%d\\n" total;;\n'
        ),
        'solution_code': (
            'let xs = [10; 20; 30; 40] in\n'
            'let total = List.fold_left (+) 0 xs in\n'
            'Printf.printf "%d\\n" total;;\n'
        ),
        'expected_output': '100',
    },
    {
        'slug':  'recursion',
        'order': 70,
        'title': 'Recursion (factorial)',
        'difficulty': 'basic',
        'prompt_md': (
            '## rec\n\n'
            'A function that calls itself must be introduced with `let rec`.\n\n'
            '**Task.** Define `fact : int -> int` (factorial). Print '
            '`fact 0`, `fact 5`, `fact 10` one per line.'
        ),
        'starter_code': (
            'let rec fact n =\n'
            '  (* base + step *) 0;;\n\n'
            'Printf.printf "%d\\n" (fact 0);;\n'
            'Printf.printf "%d\\n" (fact 5);;\n'
            'Printf.printf "%d\\n" (fact 10);;\n'
        ),
        'solution_code': (
            'let rec fact n =\n'
            '  if n <= 1 then 1\n'
            '  else n * fact (n - 1);;\n\n'
            'Printf.printf "%d\\n" (fact 0);;\n'
            'Printf.printf "%d\\n" (fact 5);;\n'
            'Printf.printf "%d\\n" (fact 10);;\n'
        ),
        'expected_output': '1\n120\n3628800',
    },
    {
        'slug':  'tuples-and-records',
        'order': 80,
        'title': 'Tuples and records',
        'difficulty': 'basic',
        'prompt_md': (
            '## Product types\n\n'
            'Tuples: `(1, "a")` of type `int * string`. Records are named '
            'tuples:\n\n'
            '```\ntype point = { x : int; y : int }\nlet p = { x = 3; y = 4 }\n```\n\n'
            '**Task.** Define `point`, make `{ x = 3; y = 4 }`, and print '
            '`x^2 + y^2` — the squared Euclidean distance from the origin.'
        ),
        'starter_code': (
            'type point = { x : int; y : int };;\n\n'
            'let p = (* ... *) { x = 0; y = 0 } in\n'
            'Printf.printf "%d\\n" (p.x * p.x + p.y * p.y);;\n'
        ),
        'solution_code': (
            'type point = { x : int; y : int };;\n\n'
            'let p = { x = 3; y = 4 } in\n'
            'Printf.printf "%d\\n" (p.x * p.x + p.y * p.y);;\n'
        ),
        'expected_output': '25',
    },
    {
        'slug':  'variants',
        'order': 90,
        'title': 'Variants (algebraic data types)',
        'difficulty': 'interm',
        'prompt_md': (
            '## Sum types\n\n'
            '`type shape = Circle of float | Square of float | Rect of float * float` '
            'defines a sum. Pattern-match on the constructor.\n\n'
            '**Task.** Define `area : shape -> float`. Print the areas of '
            '`Circle 1.0`, `Square 2.0`, and `Rect (3.0, 4.0)` with '
            '`Printf.printf "%.4f\\n"`. Use `4. *. atan 1.` for π.'
        ),
        'starter_code': (
            'type shape = Circle of float | Square of float '
            '| Rect of float * float;;\n\n'
            'let area s = (* ... *) 0.0;;\n\n'
            'Printf.printf "%.4f\\n" (area (Circle 1.0));;\n'
            'Printf.printf "%.4f\\n" (area (Square 2.0));;\n'
            'Printf.printf "%.4f\\n" (area (Rect (3.0, 4.0)));;\n'
        ),
        'solution_code': (
            'type shape = Circle of float | Square of float '
            '| Rect of float * float;;\n\n'
            'let pi = 4. *. atan 1.;;\n\n'
            'let area s =\n'
            '  match s with\n'
            '  | Circle r -> pi *. r *. r\n'
            '  | Square s -> s *. s\n'
            '  | Rect (w, h) -> w *. h;;\n\n'
            'Printf.printf "%.4f\\n" (area (Circle 1.0));;\n'
            'Printf.printf "%.4f\\n" (area (Square 2.0));;\n'
            'Printf.printf "%.4f\\n" (area (Rect (3.0, 4.0)));;\n'
        ),
        'expected_output': '3.1416\n4.0000\n12.0000',
    },
    {
        'slug':  'option-type',
        'order': 100,
        'title': 'The option type',
        'difficulty': 'interm',
        'prompt_md': (
            '## `\'a option`\n\n'
            'OCaml has no null. The builtin `option` type is '
            '`None | Some of \'a`. Use it for partial functions.\n\n'
            '**Task.** Write `safe_div a b : int option` returning `None` when '
            '`b = 0`. Print `safe 10 2` and `safe 10 0` as either the integer '
            'or the string `none`, one per line.'
        ),
        'starter_code': (
            'let safe_div a b =\n'
            '  (* Some quotient, or None *)\n'
            '  None;;\n\n'
            'let show o =\n'
            '  match o with\n'
            '  | Some n -> string_of_int n\n'
            '  | None   -> "none";;\n\n'
            'print_endline (show (safe_div 10 2));;\n'
            'print_endline (show (safe_div 10 0));;\n'
        ),
        'solution_code': (
            'let safe_div a b =\n'
            '  if b = 0 then None else Some (a / b);;\n\n'
            'let show o =\n'
            '  match o with\n'
            '  | Some n -> string_of_int n\n'
            '  | None   -> "none";;\n\n'
            'print_endline (show (safe_div 10 2));;\n'
            'print_endline (show (safe_div 10 0));;\n'
        ),
        'expected_output': '5\nnone',
    },
    {
        'slug':  'higher-order',
        'order': 110,
        'title': 'Higher-order functions',
        'difficulty': 'interm',
        'prompt_md': (
            '## Functions that take functions\n\n'
            'Every function in OCaml is a value. You can pass functions, '
            'return them, and partially apply them.\n\n'
            '**Task.** Using `List.map` and `List.filter`, from `[1;2;3;4;5;6]` '
            'print the sum of the squares of the even numbers. Hint: '
            '`List.fold_left (+) 0`.'
        ),
        'starter_code': (
            'let xs = [1;2;3;4;5;6] in\n'
            'let result =\n'
            '  xs\n'
            '  |> List.filter (fun _ -> true)\n'
            '  |> List.map (fun x -> x)\n'
            '  |> List.fold_left (+) 0 in\n'
            'Printf.printf "%d\\n" result;;\n'
        ),
        'solution_code': (
            'let xs = [1;2;3;4;5;6] in\n'
            'let result =\n'
            '  xs\n'
            '  |> List.filter (fun x -> x mod 2 = 0)\n'
            '  |> List.map (fun x -> x * x)\n'
            '  |> List.fold_left (+) 0 in\n'
            'Printf.printf "%d\\n" result;;\n'
        ),
        'expected_output': '56',
    },
]


class Command(BaseCommand):
    help = 'Seed the Camlfornia beginner curriculum (idempotent).'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Delete existing lessons first.')

    def handle(self, *args, **opts):
        if opts['reset']:
            n = Lesson.objects.count()
            Lesson.objects.all().delete()
            self.stdout.write(f'Deleted {n} existing lessons.')

        created = updated = 0
        for spec in LESSONS:
            obj, was_created = Lesson.objects.update_or_create(
                slug=spec['slug'],
                defaults={k: v for k, v in spec.items() if k != 'slug'},
            )
            if was_created:
                created += 1
            else:
                updated += 1
        self.stdout.write(self.style.SUCCESS(
            f'Camlfornia: created {created}, updated {updated}. '
            f'Total now {Lesson.objects.count()}.'))
