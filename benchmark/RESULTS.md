| Metric | Slice | n | Coin | IJF WRL | Elo | Glicko-2 | Ours | Ours, skill − 1·RD | Ours, skill − 2·RD | Ours, skill − 3·RD |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| log loss | All | 24503 | 0.6931 | 0.6445 | 0.6131 | 0.6117 | 0.5837 | **0.5736** | 0.5798 | 0.5989 |
| Brier | All | 24503 | 0.2500 | 0.2259 | 0.2129 | 0.2128 | 0.2008 | **0.1960** | 0.1972 | 0.2020 |
| accuracy | All | 24503 | 0.5000 | 0.6432 | 0.6594 | 0.6562 | 0.6810 | **0.6944** | 0.6931 | 0.6911 |
| log loss | Strength gap: close (ours < 60%) | 6717 | 0.6931 | 0.6935 | 0.7024 | 0.7217 | 0.6897 | **0.6736** | 0.6790 | 0.7010 |
| Brier | Strength gap: close (ours < 60%) | 6717 | 0.2500 | 0.2487 | 0.2543 | 0.2631 | 0.2483 | **0.2404** | 0.2423 | 0.2492 |
| accuracy | Strength gap: close (ours < 60%) | 6717 | 0.5000 | 0.5606 | 0.5115 | 0.4996 | 0.5353 | **0.5751** | 0.5680 | 0.5683 |
| log loss | Strength gap: middle (60–75%) | 9015 | 0.6931 | 0.6756 | 0.6689 | 0.6792 | 0.6489 | **0.6360** | 0.6420 | 0.6634 |
| Brier | Strength gap: middle (60–75%) | 9015 | 0.2500 | 0.2401 | 0.2378 | 0.2415 | 0.2282 | **0.2223** | 0.2239 | 0.2300 |
| accuracy | Strength gap: middle (60–75%) | 9015 | 0.5000 | 0.5958 | 0.6113 | 0.6119 | 0.6447 | 0.6514 | **0.6537** | 0.6485 |
| log loss | Strength gap: clear (75%+) | 8771 | 0.6931 | 0.5749 | 0.4875 | 0.4580 | 0.4355 | **0.4329** | 0.4399 | 0.4544 |
| Brier | Strength gap: clear (75%+) | 8771 | 0.2500 | 0.1939 | 0.1556 | 0.1446 | 0.1362 | **0.1348** | 0.1353 | 0.1372 |
| accuracy | Strength gap: clear (75%+) | 8771 | 0.5000 | 0.7550 | 0.8221 | 0.8217 | **0.8300** | **0.8300** | 0.8296 | 0.8291 |
| log loss | Level: Olympics, Worlds, Masters | 660 | 0.6931 | 0.6437 | 0.5334 | 0.5123 | **0.4956** | 0.4965 | 0.4993 | 0.5040 |
| Brier | Level: Olympics, Worlds, Masters | 660 | 0.2500 | 0.2258 | 0.1795 | 0.1712 | **0.1655** | 0.1657 | 0.1664 | 0.1677 |
| accuracy | Level: Olympics, Worlds, Masters | 660 | 0.5000 | 0.6985 | 0.7379 | **0.7515** | 0.7455 | 0.7470 | 0.7470 | 0.7470 |
| log loss | Level: Grand Slam | 4959 | 0.6931 | 0.6445 | 0.5897 | 0.5644 | **0.5558** | 0.5611 | 0.5740 | 0.5926 |
| Brier | Level: Grand Slam | 4959 | 0.2500 | 0.2259 | 0.2025 | 0.1923 | **0.1890** | 0.1905 | 0.1939 | 0.1981 |
| accuracy | Level: Grand Slam | 4959 | 0.5000 | 0.6477 | 0.6821 | 0.7010 | **0.7097** | 0.7073 | 0.7037 | 0.7006 |
| log loss | Level: Grand Prix | 2624 | 0.6931 | 0.6575 | 0.5920 | 0.5707 | **0.5629** | 0.5743 | 0.5959 | 0.6251 |
| Brier | Level: Grand Prix | 2624 | 0.2500 | 0.2306 | 0.2028 | 0.1941 | **0.1908** | 0.1944 | 0.2001 | 0.2063 |
| accuracy | Level: Grand Prix | 2624 | 0.5000 | 0.6473 | 0.6873 | **0.7018** | 0.7014 | 0.7010 | 0.6976 | 0.6946 |
| log loss | Level: Continental championships | 2542 | 0.6931 | 0.6000 | 0.5889 | 0.6025 | 0.5481 | 0.5262 | **0.5182** | 0.5214 |
| Brier | Level: Continental championships | 2542 | 0.2500 | 0.2060 | 0.2024 | 0.2088 | 0.1861 | 0.1769 | **0.1732** | 0.1733 |
| accuracy | Level: Continental championships | 2542 | 0.5000 | 0.6963 | 0.6847 | 0.6719 | 0.7154 | 0.7311 | 0.7358 | **0.7402** |
| log loss | Level: Opens and cups | 13718 | 0.6931 | 0.6503 | 0.6340 | 0.6431 | 0.6086 | **0.5906** | 0.5941 | 0.6151 |
| Brier | Level: Opens and cups | 13718 | 0.2500 | 0.2288 | 0.2221 | 0.2265 | 0.2114 | **0.2033** | 0.2038 | 0.2096 |
| accuracy | Level: Opens and cups | 13718 | 0.5000 | 0.6282 | 0.6374 | 0.6237 | 0.6573 | **0.6791** | 0.6780 | 0.6753 |
| log loss | Medal rounds of majors (OG, Worlds, Masters, GS) | 901 | 0.6931 | 0.6858 | 0.6335 | 0.6152 | **0.6050** | 0.6053 | 0.6087 | 0.6153 |
| Brier | Medal rounds of majors (OG, Worlds, Masters, GS) | 901 | 0.2500 | 0.2446 | 0.2222 | 0.2134 | **0.2101** | 0.2104 | 0.2118 | 0.2142 |
| accuracy | Medal rounds of majors (OG, Worlds, Masters, GS) | 901 | 0.5000 | 0.6077 | 0.6482 | **0.6626** | 0.6548 | **0.6626** | 0.6570 | 0.6593 |
| log loss | Experience: one side < 10 contests | 10402 | 0.6931 | 0.6238 | 0.6399 | 0.6683 | 0.6103 | **0.5862** | 0.5967 | 0.6343 |
| Brier | Experience: one side < 10 contests | 10402 | 0.2500 | 0.2167 | 0.2248 | 0.2374 | 0.2119 | **0.2006** | 0.2021 | 0.2109 |
| accuracy | Experience: one side < 10 contests | 10402 | 0.5000 | 0.6546 | 0.6295 | 0.5974 | 0.6564 | 0.6866 | **0.6880** | 0.6848 |
| log loss | Experience: both 10+ | 14101 | 0.6931 | 0.6598 | 0.5934 | 0.5699 | **0.5641** | 0.5643 | 0.5673 | 0.5728 |
| Brier | Experience: both 10+ | 14101 | 0.2500 | 0.2328 | 0.2041 | 0.1946 | **0.1926** | 0.1926 | 0.1936 | 0.1955 |
| accuracy | Experience: both 10+ | 14101 | 0.5000 | 0.6347 | 0.6814 | 0.6995 | 0.6992 | **0.7002** | 0.6969 | 0.6958 |
| log loss | No WRL points: one side has 0 | 6926 | 0.6931 | 0.6515 | 0.6428 | 0.6955 | 0.6253 | 0.5836 | **0.5808** | 0.6081 |
| Brier | No WRL points: one side has 0 | 6926 | 0.2500 | 0.2278 | 0.2263 | 0.2499 | 0.2188 | 0.2003 | **0.1974** | 0.2033 |
| accuracy | No WRL points: one side has 0 | 6926 | 0.5000 | 0.6406 | 0.6141 | 0.5617 | 0.6362 | 0.6803 | 0.6887 | **0.6925** |
| log loss | After a change of weight (first 5 in the new one) | 2553 | 0.6931 | 0.6954 | 0.6189 | 0.6096 | 0.5859 | **0.5766** | 0.5860 | 0.6107 |
| Brier | After a change of weight (first 5 in the new one) | 2553 | 0.2500 | 0.2479 | 0.2154 | 0.2114 | 0.2015 | **0.1968** | 0.1988 | 0.2049 |
| accuracy | After a change of weight (first 5 in the new one) | 2553 | 0.5000 | 0.5879 | 0.6582 | 0.6567 | 0.6864 | **0.6937** | 0.6882 | 0.6898 |

| Ours minus | Slice | Δ log loss ×1000 | 95% interval |
|---|---|---:|---|
| IJF WRL | All | -60.8 | [-72.1, -48.7] |
| Elo | All | -29.4 | [-34.1, -25.0] |
| Glicko-2 | All | -28.0 | [-34.3, -22.4] |
| Ours, skill − 1·RD | All | +10.1 | [+6.2, +14.8] |
| Ours, skill − 2·RD | All | +3.9 | [-3.1, +11.9] |
| Ours, skill − 3·RD | All | -15.2 | [-25.0, -4.8] |
| IJF WRL | Medal rounds of majors (OG, Worlds, Masters, GS) | -80.8 | [-110.6, -50.8] |
| Elo | Medal rounds of majors (OG, Worlds, Masters, GS) | -28.5 | [-42.2, -15.1] |
| Glicko-2 | Medal rounds of majors (OG, Worlds, Masters, GS) | -10.2 | [-20.8, -0.3] |
| Ours, skill − 1·RD | Medal rounds of majors (OG, Worlds, Masters, GS) | -0.2 | [-3.2, +3.1] |
| Ours, skill − 2·RD | Medal rounds of majors (OG, Worlds, Masters, GS) | -3.7 | [-10.1, +3.3] |
| Ours, skill − 3·RD | Medal rounds of majors (OG, Worlds, Masters, GS) | -10.3 | [-20.5, +0.8] |
| IJF WRL | Experience: one side < 10 contests | -13.5 | [-29.8, +3.2] |
| Elo | Experience: one side < 10 contests | -29.6 | [-37.8, -21.5] |
| Glicko-2 | Experience: one side < 10 contests | -57.9 | [-68.7, -48.9] |
| Ours, skill − 1·RD | Experience: one side < 10 contests | +24.1 | [+16.4, +32.2] |
| Ours, skill − 2·RD | Experience: one side < 10 contests | +13.6 | [-2.3, +29.6] |
| Ours, skill − 3·RD | Experience: one side < 10 contests | -23.9 | [-48.0, -0.2] |

| Favourite's chance | IJF WRL | Elo | Glicko-2 | Ours | Ours, skill − 1·RD | Ours, skill − 2·RD | Ours, skill − 3·RD |
|---|---|---|---|---|---|---|---|
| 50–60% | 54.8% → won 58.8% (n=10948) | 54.6% → won 56.6% (n=11846) | 55.1% → won 53.8% (n=6939) | 55.0% → won 53.7% (n=6466) | 55.0% → won 54.2% (n=6008) | 54.9% → won 52.3% (n=5460) | 54.9% → won 52.9% (n=4897) |
| 60–70% | 64.5% → won 67.9% (n=6128) | 64.5% → won 68.9% (n=6819) | 65.0% → won 60.9% (n=6566) | 64.9% → won 62.5% (n=6211) | 65.0% → won 63.4% (n=5780) | 65.0% → won 62.2% (n=5106) | 64.9% → won 60.7% (n=4683) |
| 70–80% | 74.8% → won 71.8% (n=4103) | 74.5% → won 79.2% (n=3411) | 74.8% → won 70.1% (n=5510) | 74.8% → won 71.6% (n=5229) | 74.9% → won 71.3% (n=5157) | 74.9% → won 70.6% (n=5003) | 75.0% → won 68.1% (n=4720) |
| 80–90% | 83.4% → won 75.1% (n=2185) | 84.3% → won 87.1% (n=1693) | 84.5% → won 81.4% (n=3673) | 84.7% → won 82.6% (n=4167) | 84.8% → won 82.5% (n=4433) | 84.9% → won 79.3% (n=4777) | 85.1% → won 77.1% (n=4773) |
| 90–100% | – | 93.1% → won 93.8% (n=483) | 93.3% → won 93.1% (n=1364) | 93.8% → won 93.1% (n=2179) | 94.0% → won 91.7% (n=2877) | 94.3% → won 89.7% (n=3909) | 94.8% → won 86.6% (n=5182) |

Disagreements with the WRL: 7441 contests; ours right in 4140 (55.6%), the WRL in 3301; exact McNemar p = 2.4e-22.

| Metric | Coin | IJF WRL | Elo | Glicko-2 | Ours | Ours, skill − 1·RD | Ours, skill − 2·RD | Ours, skill − 3·RD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| log loss | 0.6931 | 0.7551 | 0.6825 | 0.7138 | 0.6891 | 0.6641 | 0.6615 | 0.6793 |
| accuracy | 0.5000 | 0.4436 | 0.5511 | 0.5607 | 0.5564 | 0.5990 | 0.5986 | 0.5955 |

IJF WRL: k = 0.25 fitted on 5150 contests (2025-03-17 to 2025-07-01); with k = 1 (chances proportional to points) the test's log loss is 0.9107, accuracy 0.6432.
