| Metric | Slice | n | Coin | IJF WRL | Elo | Glicko-2 | Ours |
|---|---|---:|---:|---:|---:|---:|---:|
| log loss | All | 24503 | 0.6931 | 0.6445 | 0.6131 | **0.5802** | 0.5837 |
| Brier | All | 24503 | 0.2500 | 0.2259 | 0.2129 | **0.1992** | 0.2008 |
| accuracy | All | 24503 | 0.5000 | 0.6432 | 0.6594 | **0.6874** | 0.6810 |
| log loss | Strength gap: close (ours < 60%) | 6717 | 0.6931 | 0.6935 | 0.7024 | **0.6845** | 0.6897 |
| Brier | Strength gap: close (ours < 60%) | 6717 | 0.2500 | 0.2487 | 0.2543 | **0.2457** | 0.2483 |
| accuracy | Strength gap: close (ours < 60%) | 6717 | 0.5000 | **0.5606** | 0.5115 | 0.5581 | 0.5353 |
| log loss | Strength gap: middle (60–75%) | 9015 | 0.6931 | 0.6756 | 0.6689 | **0.6446** | 0.6489 |
| Brier | Strength gap: middle (60–75%) | 9015 | 0.2500 | 0.2401 | 0.2378 | **0.2263** | 0.2282 |
| accuracy | Strength gap: middle (60–75%) | 9015 | 0.5000 | 0.5958 | 0.6113 | **0.6449** | 0.6447 |
| log loss | Strength gap: clear (75%+) | 8771 | 0.6931 | 0.5749 | 0.4875 | **0.4342** | 0.4355 |
| Brier | Strength gap: clear (75%+) | 8771 | 0.2500 | 0.1939 | 0.1556 | **0.1358** | 0.1362 |
| accuracy | Strength gap: clear (75%+) | 8771 | 0.5000 | 0.7550 | 0.8221 | **0.8300** | **0.8300** |
| log loss | Level: Olympics, Worlds, Masters | 660 | 0.6931 | 0.6437 | 0.5334 | 0.4960 | **0.4956** |
| Brier | Level: Olympics, Worlds, Masters | 660 | 0.2500 | 0.2258 | 0.1795 | 0.1658 | **0.1655** |
| accuracy | Level: Olympics, Worlds, Masters | 660 | 0.5000 | 0.6985 | 0.7379 | **0.7500** | 0.7455 |
| log loss | Level: Grand Slam | 4959 | 0.6931 | 0.6445 | 0.5897 | **0.5556** | 0.5558 |
| Brier | Level: Grand Slam | 4959 | 0.2500 | 0.2259 | 0.2025 | **0.1888** | 0.1890 |
| accuracy | Level: Grand Slam | 4959 | 0.5000 | 0.6477 | 0.6821 | **0.7101** | 0.7097 |
| log loss | Level: Grand Prix | 2624 | 0.6931 | 0.6575 | 0.5920 | 0.5629 | **0.5629** |
| Brier | Level: Grand Prix | 2624 | 0.2500 | 0.2306 | 0.2028 | 0.1908 | **0.1908** |
| accuracy | Level: Grand Prix | 2624 | 0.5000 | 0.6473 | 0.6873 | **0.7022** | 0.7014 |
| log loss | Level: Continental championships | 2542 | 0.6931 | 0.6000 | 0.5889 | **0.5430** | 0.5481 |
| Brier | Level: Continental championships | 2542 | 0.2500 | 0.2060 | 0.2024 | **0.1840** | 0.1861 |
| accuracy | Level: Continental championships | 2542 | 0.5000 | 0.6963 | 0.6847 | **0.7209** | 0.7154 |
| log loss | Level: Opens and cups | 13718 | 0.6931 | 0.6503 | 0.6340 | **0.6034** | 0.6086 |
| Brier | Level: Opens and cups | 13718 | 0.2500 | 0.2288 | 0.2221 | **0.2090** | 0.2114 |
| accuracy | Level: Opens and cups | 13718 | 0.5000 | 0.6282 | 0.6374 | **0.6671** | 0.6573 |
| log loss | Medal rounds of majors (OG, Worlds, Masters, GS) | 901 | 0.6931 | 0.6858 | 0.6335 | 0.6056 | **0.6050** |
| Brier | Medal rounds of majors (OG, Worlds, Masters, GS) | 901 | 0.2500 | 0.2446 | 0.2222 | 0.2104 | **0.2101** |
| accuracy | Medal rounds of majors (OG, Worlds, Masters, GS) | 901 | 0.5000 | 0.6077 | 0.6482 | **0.6548** | **0.6548** |
| log loss | Experience: one side < 10 contests | 10402 | 0.6931 | 0.6238 | 0.6399 | **0.6029** | 0.6103 |
| Brier | Experience: one side < 10 contests | 10402 | 0.2500 | 0.2167 | 0.2248 | **0.2086** | 0.2119 |
| accuracy | Experience: one side < 10 contests | 10402 | 0.5000 | 0.6546 | 0.6295 | **0.6653** | 0.6564 |
| log loss | Experience: both 10+ | 14101 | 0.6931 | 0.6598 | 0.5934 | **0.5634** | 0.5641 |
| Brier | Experience: both 10+ | 14101 | 0.2500 | 0.2328 | 0.2041 | **0.1922** | 0.1926 |
| accuracy | Experience: both 10+ | 14101 | 0.5000 | 0.6347 | 0.6814 | **0.7036** | 0.6992 |
| log loss | No WRL points: one side has 0 | 6926 | 0.6931 | 0.6515 | 0.6428 | **0.6153** | 0.6253 |
| Brier | No WRL points: one side has 0 | 6926 | 0.2500 | 0.2278 | 0.2263 | **0.2144** | 0.2188 |
| accuracy | No WRL points: one side has 0 | 6926 | 0.5000 | 0.6406 | 0.6141 | **0.6489** | 0.6362 |
| log loss | After a change of weight (first 5 in the new one) | 2553 | 0.6931 | 0.6954 | 0.6189 | **0.5796** | 0.5859 |
| Brier | After a change of weight (first 5 in the new one) | 2553 | 0.2500 | 0.2479 | 0.2154 | **0.1983** | 0.2015 |
| accuracy | After a change of weight (first 5 in the new one) | 2553 | 0.5000 | 0.5879 | 0.6582 | **0.6958** | 0.6864 |

| Ours minus | Slice | Δ log loss ×1000 | 95% interval |
|---|---|---:|---|
| IJF WRL | All | -60.8 | [-72.1, -48.7] |
| Elo | All | -29.4 | [-34.1, -25.0] |
| Glicko-2 | All | +3.5 | [+2.5, +4.6] |
| IJF WRL | Medal rounds of majors (OG, Worlds, Masters, GS) | -80.8 | [-110.6, -50.8] |
| Elo | Medal rounds of majors (OG, Worlds, Masters, GS) | -28.5 | [-42.2, -15.1] |
| Glicko-2 | Medal rounds of majors (OG, Worlds, Masters, GS) | -0.6 | [-2.2, +1.2] |
| IJF WRL | Experience: one side < 10 contests | -13.5 | [-29.8, +3.2] |
| Elo | Experience: one side < 10 contests | -29.6 | [-37.8, -21.5] |
| Glicko-2 | Experience: one side < 10 contests | +7.4 | [+5.9, +9.1] |

| Favourite's chance | IJF WRL | Elo | Glicko-2 | Ours |
|---|---|---|---|---|
| 50–60% | 54.8% → won 58.8% (n=10948) | 54.6% → won 56.6% (n=11846) | 55.0% → won 55.2% (n=6379) | 55.0% → won 53.7% (n=6466) |
| 60–70% | 64.5% → won 67.9% (n=6128) | 64.5% → won 68.9% (n=6819) | 64.9% → won 62.2% (n=6159) | 64.9% → won 62.5% (n=6211) |
| 70–80% | 74.8% → won 71.8% (n=4103) | 74.5% → won 79.2% (n=3411) | 74.8% → won 72.2% (n=5245) | 74.8% → won 71.6% (n=5229) |
| 80–90% | 83.4% → won 75.1% (n=2185) | 84.3% → won 87.1% (n=1693) | 84.7% → won 82.6% (n=4159) | 84.7% → won 82.6% (n=4167) |
| 90–100% | – | 93.1% → won 93.8% (n=483) | 93.9% → won 92.9% (n=2310) | 93.8% → won 93.1% (n=2179) |

Disagreements with the WRL: 7441 contests; ours right in 4140 (55.6%), the WRL in 3301; exact McNemar p = 2.4e-22.

| Metric | Coin | IJF WRL | Elo | Glicko-2 | Ours |
|---|---:|---:|---:|---:|---:|
| log loss | 0.6931 | 0.7551 | 0.6825 | 0.6843 | 0.6891 |
| accuracy | 0.5000 | 0.4436 | 0.5511 | 0.5701 | 0.5564 |

IJF WRL: k = 0.25 fitted on 5150 contests (2025-03-17 to 2025-07-01); with k = 1 (chances proportional to points) the test's log loss is 0.9107, accuracy 0.6432.
