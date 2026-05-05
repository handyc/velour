# wnnr

A Win95-style window in your terminal. ~1 KB of C, no curses, no
SLURM, no third-party libraries. Smaller than the bash original.

```
   wnnr - window         _ [] X       ← royal blue title bar
   File  Edit  View  Help             ← grey menu bar
                                      ← grey content
                                          (8 rows of empty space)
```

## Build & run

```sh
make
./wnnr
```

Arrow keys move the window. `q` quits. That's it.

## Source size

```sh
$ wc -c wnnr.c
998 wnnr.c
```
