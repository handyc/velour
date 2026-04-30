"""helix.hexhunt — hex cellular automata applied to organic DNA.

Same K=4, 7-cell-positional rule format as automaton/s3lab (one
canonical 4 KB rule blob across all of Velour). What's different here
is the *corpus*: tournaments evolve rules against windows of real
DNA / RNA from SequenceRecord, never random seeds, so a "good rule"
in this app means one that produces rich behaviour when fed organic
input — a candidate motif detector for the genome scan use case.
"""
