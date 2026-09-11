# Analysis scripts

Run from the repo root with `PYTHONPATH=. python3 analysis/<script>.py <csv>...`

- `reality.py`  — reward:risk, runner distribution, how much of each move is
  captured, buy-and-hold benchmark, in/out-of-sample split, cost sensitivity.
  This is the one that decides whether an edge exists.
- `runners.py`  — does a slower Safety Line let winners run? (It does not.)
- `bytouch.py`  — 2-touch vs 3-touch performance on genuine breaks only.
- `matrix.py`   — always-in vs flat across timeframes.
- `touches.py`  — how sensitive the touch count is to detection tolerance.
