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
| Glicko-2 | our engine without our additions (no handicap on a change of weight) | after every contest |
| Ours | the engine as on the site (`ajr/rating`) | after every contest |

The models that can learn within a tournament do, as they are used; the WRL is what the
IJF publishes. A list `YYYY_N` is the one of the Monday of ISO week N, with the results
up to the Sunday before (checked: Abu Dhabi Grand Slam, 29–31 Oct 2026, is in 2026_45).
`k` is fitted on the calibration window; `k = 1` (chances in proportion to the points)
is reported too.

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
are not independent). Slices: the strength gap (by our chance), the tournament's level,
medal rounds of the majors, experience (fewer than 10 contests before), no WRL points,
the first 5 contests after a change of weight.

## Files

| File | What | In git |
|---|---|---|
| `ijf_benchmark.py` | the benchmark | yes |
| `fetch_wrl_history.py` | downloads the WRL history from judobase (`competitor.wrl_history`, every athlete in `ajr.athlete`) | yes |
| `data/contests.csv.gz` | the snapshot of our contests in the rating's order (226 776), with the facts the slices use | yes |
| `data/predictions.csv.gz` | every judged contest of the calibration and the test with each model's chance, the WRL points and the slices | yes |
| `data/wrl_history.csv.gz` | the IJF's weekly lists, 2025 week 12 to 2026 week 45, seniors, juniors and cadets (586 685 rows) | no: the IJF's data |

## Run it again

```sh
cd benchmark
DATABASE_URL=postgresql+psycopg://… uv run python fetch_wrl_history.py   # the WRL lists (~5 min)
uv run python ijf_benchmark.py                                          # from the snapshot
DATABASE_URL=postgresql+psycopg://… uv run python ijf_benchmark.py --snapshot  # a new snapshot first
```

judobase keeps about the last year and a half of the lists: a later fetch starts later,
so a rerun on a new snapshot moves the windows.
