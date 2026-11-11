| Metric | Slice | n | Coin | IJF WRL | Elo | Glicko-2 | Ours |
|---|---|---:|---:|---:|---:|---:|---:|
| log loss | All | 24503 | 0.6931 | 0.6445 | 0.6131 | 0.6119 | **0.5736** |
| Brier | All | 24503 | 0.2500 | 0.2259 | 0.2129 | 0.2129 | **0.1960** |
| accuracy | All | 24503 | 0.5000 | 0.6432 | 0.6594 | 0.6562 | **0.6944** |
| log loss | Strength gap: close (ours < 60%) | 6256 | 0.6931 | 0.7109 | 0.7071 | 0.7270 | **0.6881** |
| Brier | Strength gap: close (ours < 60%) | 6256 | 0.2500 | 0.2567 | 0.2566 | 0.2649 | **0.2475** |
| accuracy | Strength gap: close (ours < 60%) | 6256 | 0.5000 | 0.5380 | 0.4977 | 0.5136 | **0.5403** |
| log loss | Strength gap: middle (60–75%) | 8426 | 0.6931 | 0.6905 | 0.6764 | 0.6890 | **0.6468** |
| Brier | Strength gap: middle (60–75%) | 8426 | 0.2500 | 0.2470 | 0.2414 | 0.2461 | **0.2271** |
| accuracy | Strength gap: middle (60–75%) | 8426 | 0.5000 | 0.5767 | 0.5962 | 0.5926 | **0.6502** |
| log loss | Strength gap: clear (75%+) | 9821 | 0.6931 | 0.5627 | 0.4990 | 0.4723 | **0.4380** |
| Brier | Strength gap: clear (75%+) | 9821 | 0.2500 | 0.1883 | 0.1605 | 0.1512 | **0.1364** |
| accuracy | Strength gap: clear (75%+) | 9821 | 0.5000 | 0.7671 | 0.8166 | 0.8016 | **0.8305** |
| log loss | Level: Olympics, Worlds, Masters | 660 | 0.6931 | 0.6437 | 0.5334 | 0.5123 | **0.4965** |
| Brier | Level: Olympics, Worlds, Masters | 660 | 0.2500 | 0.2258 | 0.1795 | 0.1712 | **0.1657** |
| accuracy | Level: Olympics, Worlds, Masters | 660 | 0.5000 | 0.6985 | 0.7379 | **0.7485** | 0.7470 |
| log loss | Level: Grand Slam | 4959 | 0.6931 | 0.6445 | 0.5897 | 0.5652 | **0.5611** |
| Brier | Level: Grand Slam | 4959 | 0.2500 | 0.2259 | 0.2025 | 0.1926 | **0.1905** |
| accuracy | Level: Grand Slam | 4959 | 0.5000 | 0.6477 | 0.6821 | 0.7008 | **0.7073** |
| log loss | Level: Grand Prix | 2624 | 0.6931 | 0.6575 | 0.5920 | **0.5710** | 0.5743 |
| Brier | Level: Grand Prix | 2624 | 0.2500 | 0.2306 | 0.2028 | **0.1942** | 0.1944 |
| accuracy | Level: Grand Prix | 2624 | 0.5000 | 0.6473 | 0.6873 | **0.7010** | **0.7010** |
| log loss | Level: Continental championships | 2542 | 0.6931 | 0.6000 | 0.5889 | 0.6025 | **0.5262** |
| Brier | Level: Continental championships | 2542 | 0.2500 | 0.2060 | 0.2024 | 0.2088 | **0.1769** |
| accuracy | Level: Continental championships | 2542 | 0.5000 | 0.6963 | 0.6847 | 0.6731 | **0.7311** |
| log loss | Level: Opens and cups | 13718 | 0.6931 | 0.6503 | 0.6340 | 0.6431 | **0.5906** |
| Brier | Level: Opens and cups | 13718 | 0.2500 | 0.2288 | 0.2221 | 0.2265 | **0.2033** |
| accuracy | Level: Opens and cups | 13718 | 0.5000 | 0.6282 | 0.6374 | 0.6239 | **0.6791** |
| log loss | Medal rounds of majors (OG, Worlds, Masters, GS) | 901 | 0.6931 | 0.6858 | 0.6335 | 0.6153 | **0.6053** |
| Brier | Medal rounds of majors (OG, Worlds, Masters, GS) | 901 | 0.2500 | 0.2446 | 0.2222 | 0.2134 | **0.2104** |
| accuracy | Medal rounds of majors (OG, Worlds, Masters, GS) | 901 | 0.5000 | 0.6077 | 0.6482 | **0.6626** | **0.6626** |
| log loss | Experience: one side < 10 contests | 10402 | 0.6931 | 0.6238 | 0.6399 | 0.6685 | **0.5862** |
| Brier | Experience: one side < 10 contests | 10402 | 0.2500 | 0.2167 | 0.2248 | 0.2375 | **0.2006** |
| accuracy | Experience: one side < 10 contests | 10402 | 0.5000 | 0.6546 | 0.6295 | 0.5977 | **0.6866** |
| log loss | Experience: both 10+ | 14101 | 0.6931 | 0.6598 | 0.5934 | 0.5701 | **0.5643** |
| Brier | Experience: both 10+ | 14101 | 0.2500 | 0.2328 | 0.2041 | 0.1947 | **0.1926** |
| accuracy | Experience: both 10+ | 14101 | 0.5000 | 0.6347 | 0.6814 | 0.6993 | **0.7002** |
| log loss | No WRL points: one side has 0 | 6926 | 0.6931 | 0.6515 | 0.6428 | 0.6955 | **0.5836** |
| Brier | No WRL points: one side has 0 | 6926 | 0.2500 | 0.2278 | 0.2263 | 0.2499 | **0.2003** |
| accuracy | No WRL points: one side has 0 | 6926 | 0.5000 | 0.6406 | 0.6141 | 0.5622 | **0.6803** |
| log loss | After a change of weight (first 5 in the new one) | 2553 | 0.6931 | 0.6954 | 0.6189 | 0.6095 | **0.5766** |
| Brier | After a change of weight (first 5 in the new one) | 2553 | 0.2500 | 0.2479 | 0.2154 | 0.2113 | **0.1968** |
| accuracy | After a change of weight (first 5 in the new one) | 2553 | 0.5000 | 0.5879 | 0.6582 | 0.6563 | **0.6937** |

| Ours minus | Slice | Δ log loss ×1000 | 95% interval |
|---|---|---:|---|
| IJF WRL | All | -70.9 | [-80.6, -61.8] |
| Elo | All | -39.5 | [-46.1, -33.9] |
| Glicko-2 | All | -38.2 | [-48.3, -29.1] |
| IJF WRL | Medal rounds of majors (OG, Worlds, Masters, GS) | -80.6 | [-108.7, -52.6] |
| Elo | Medal rounds of majors (OG, Worlds, Masters, GS) | -28.2 | [-40.4, -17.2] |
| Glicko-2 | Medal rounds of majors (OG, Worlds, Masters, GS) | -10.0 | [-21.1, +1.2] |
| IJF WRL | Experience: one side < 10 contests | -37.6 | [-50.5, -24.6] |
| Elo | Experience: one side < 10 contests | -53.7 | [-65.3, -43.3] |
| Glicko-2 | Experience: one side < 10 contests | -82.3 | [-98.5, -66.9] |

| Favourite's chance | IJF WRL | Elo | Glicko-2 | Ours |
|---|---|---|---|---|
| 50–60% | 54.8% → won 58.8% (n=10948) | 54.6% → won 56.6% (n=11846) | 55.1% → won 53.9% (n=6931) | 55.0% → won 54.2% (n=6008) |
| 60–70% | 64.5% → won 67.9% (n=6128) | 64.5% → won 68.9% (n=6819) | 65.0% → won 60.9% (n=6568) | 65.0% → won 63.4% (n=5780) |
| 70–80% | 74.8% → won 71.8% (n=4103) | 74.5% → won 79.2% (n=3411) | 74.8% → won 69.9% (n=5508) | 74.9% → won 71.3% (n=5157) |
| 80–90% | 83.4% → won 75.1% (n=2185) | 84.3% → won 87.1% (n=1693) | 84.5% → won 81.5% (n=3679) | 84.8% → won 82.5% (n=4433) |
| 90–100% | – | 93.1% → won 93.8% (n=483) | 93.3% → won 93.0% (n=1366) | 94.0% → won 91.7% (n=2877) |

Disagreements with the WRL: 6317 contests; ours right in 3733 (59.1%), the WRL in 2584; exact McNemar p = 1.5e-47.

| Metric | Coin | IJF WRL | Elo | Glicko-2 | Ours |
|---|---:|---:|---:|---:|---:|
| log loss | 0.6931 | 0.7719 | 0.6755 | 0.6949 | 0.6665 |
| accuracy | 0.5000 | 0.4091 | 0.5698 | 0.5921 | 0.5909 |

IJF WRL: k = 0.25 fitted on 5150 contests (2025-03-17 to 2025-07-01); with k = 1 (chances proportional to points) the test's log loss is 0.9107, accuracy 0.6432.
