# Benchmark: our rating against the IJF World Ranking List

Which rating predicts the winner of a judo contest better: ours, the IJF World Ranking
List, or the classic baselines. Every model gives each contest's blue side a chance
before it is fought; they are scored on the same contests.

The numbers: [RESULTS.md](RESULTS.md) (and `results.json`). Taken on 2026-11-11 from a
copy of production with the contests up to 2026-11-08.

## Models

| Model | Chance of the blue side | Updates |
|---|---|---|
| Coin | 0.5 | — |
| IJF WRL | `sigmoid(k · (log(pts_blue + 1) − log(pts_white + 1)))`, the points in the contest's weight in the latest weekly list published on or before the tournament's first day | weekly, as the IJF publishes it |
| Elo | 1500 at the start, K = 32 | after every contest |
| Glicko-2 | as in the paper (Glickman, 2013): the contests of a calendar month rated together from the ratings at its start; the uncertainty grows only through the volatility (`φ² + σ²` a period); the chance from both sides' uncertainty (Glicko, 1999); 1500 / 350 / 0.06, τ 0.5 | once a month |
| Ours | the engine as on the site (`ajr/rating`): Glicko-2 updated after every contest, the uncertainty growing every day without one, a handicap on a change of weight (5% of the rating: a minus up, a plus down); the chance from each side's rating, **skill − 1·RD**, and both RDs | after every contest |

Elo and ours learn within a tournament, as they are used; the paper's Glicko-2 within a
month and the WRL within a week do not, as they are defined.

Our rating's shift (skill − n·RD) was measured on this test with n = 0, 1, 2, 3: log
loss 0.5837, **0.5736**, 0.5798, 0.5989. 1 is the best; 3 (the tables' rating before)
is overconfident.

The WRL: a list `YYYY_N` is the one of the Monday of ISO week N, with the results up to
the Sunday before (checked: Abu Dhabi Grand Slam, 29–31 Oct 2026, is in 2026_45). `k` is
fitted on the calibration window; `k = 1` (chances in proportion to the points) is
reported too.

## Windows

| | From | To | |
|---|---|---|---|
| Warm-up | 1956 | 2025-03-16 | ratings only |
| Calibration | 2025-03-17 (the archive's first list) | 2025-06-30 | the WRL's `k` |
| Test | 2025-07-01 | 2026-11-08 | every metric |

Judged contests: real fights as the rating takes them (individual seniors' events, the
14 weights, no walkovers), without byes and 0:00 contests; the same for every model.

## Metrics and slices

Log loss (the main one), Brier score, accuracy (a 50/50 chance counts as half right),
calibration by the favourite's chance; on the contests where ours and the WRL name
different favourites, who is right, with an exact McNemar test. Differences in log loss
come with 95% intervals from resampling whole tournaments (contests of one tournament
are not independent). Slices: the strength gap (by our own chance: it slightly favours
ours), the tournament's level, medal rounds of the majors, experience (fewer than 10
contests before), no WRL points, the first 5 contests after a change of weight.

## Files

| File | What | In git |
|---|---|---|
| `ijf_benchmark.py` | the benchmark | yes |
| `fetch_wrl_history.py` | downloads the WRL history from judobase (`competitor.wrl_history`, every athlete in `ajr.athlete`) | yes |
| `data/contests.csv.gz` | the snapshot of our contests in the rating's order (226 776), with the facts the slices use | yes |
| `data/predictions.csv.gz` | every judged contest of the calibration and the test with each model's chance, the WRL points and the slices | yes |
| `data/tables.csv.gz` | today's listed athletes with their skill and RD (the slider's tables) | yes |
| `data/rd_shift.json` | the methodology's slider "rating = skill − n·RD", n = 0 … 5 by 0.5: the test's metrics (all, newcomers, medal rounds), calibration and the share right against the IJF for each n, and each weight's top 10 | yes |
| `data/wrl_history.csv.gz` | the IJF's weekly lists as judobase gave them on 2026-11-11, 2025 week 12 to 2026 week 45, seniors, juniors and cadets (586 685 rows): kept, as judobase keeps only the last year and a half and may change them | yes |

## Run it again

```sh
cd benchmark
DATABASE_URL=postgresql+psycopg://… uv run python fetch_wrl_history.py   # the WRL lists (~5 min)
uv run python ijf_benchmark.py                                          # from the snapshot
DATABASE_URL=postgresql+psycopg://… uv run python ijf_benchmark.py --snapshot  # a new snapshot first
```

judobase keeps about the last year and a half of the lists: a later fetch starts later,
so the archive here is the one the results were computed from; fetch again only to
extend it.
