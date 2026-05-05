# Phase 4a PoC results — 20 routes

**shipped:** 2/20 (10%) at default threshold conf ≥ 0.6

## Stage funnel

| stage | passed | %n |
|---|---:|---:|
| contour ≥ 10 px        | 20/20 | 100% |
| OCR ≥ 1 street         | 10/20     | 50% |
| crossref cluster       | 9/20   | 45% |
| georef fit (≥3 GCPs)   | 9/20  | 45% |
| map-match snapped      | 9/20     | 45% |
| **shipped (conf ≥ 0.6)** | **2/20** | **10%** |

## Failure modes

| mode | count |
|---|---:|
| ocr_no_street_candidates | 10 |
| confidence_under_threshold | 7 |
| shipped | 2 |
| crossref_no_cluster | 1 |

## Per-route detail

| id | flag | conf | candidates | GCPs | RMSE m | fidelity | title | failure |
|---:|:--|---:|---:|---:|---:|---:|---|---|
| 5 | FAIL | 0.00 | 0 | 0 | — | — | MANCHESTER DOG | ocr: no street candidates |
| 30 | FAIL | 0.00 | 0 | 0 | — | — | THE ONE WITH THE DOGGO IN VIENNA 🐶❤️ | ocr: no street candidates |
| 36 | FAIL | 0.00 | 0 | 0 | — | — | 100k GPS ART TOUR OF WEST DEVON. WOOF! | ocr: no street candidates |
| 53 | FAIL | 0.58 | 12 | 6 | 12.7 | 0.36 | REGENT’S PARK, GREAT DAY FOR DOGGIN | confidence: 0.58 < 0.60 |
| 60 | FAIL | 0.28 | 7 | 5 | 0.0 | 0.15 | DOGGIN’ MY WAY THROUGH HAMPSTEAD HEATH | confidence: 0.28 < 0.60 |
| 208 | FAIL | 0.00 | 0 | 0 | — | — | BERLIN MUTT | ocr: no street candidates |
| 248 | FAIL | 0.00 | 0 | 0 | — | — | 1st BERLIN DRAWING. HUAWEI ❌ ADIDAS /// 🦅🥳🙌🏻 | ocr: no street candidates |
| 577 | FAIL | 0.37 | 10 | 3 | 0.0 | 0.48 | DUMBO VISITS CAMBRIDGE | confidence: 0.37 < 0.60 |
| 584 | FAIL | 0.50 | 15 | 5 | 2.5 | 0.19 | TRAVELLING ELEPHANT, UK 🐘🇬🇧 | confidence: 0.50 < 0.60 |
| 799 | FAIL | 0.00 | 0 | 0 | — | — | BULLFIGHT IN MUNICH | ocr: no street candidates |
| 800 | FAIL | 0.00 | 0 | 0 | — | — | MUNICH LION | ocr: no street candidates |
| 910 | SHIP | 0.60 | 12 | 5 | 5.5 | 0.40 | THE LONDON MARATHON. THIS IS MY RACE, THIS IS MY CITY, LONDO |  |
| 921 | SHIP | 0.62 | 13 | 6 | 5.4 | 0.46 | THE HACKNEY HORSE 🐎 |  |
| 942 | FAIL | 0.31 | 13 | 5 | 0.0 | 0.19 | THE ONE WITH THE LONDON BEAR HALF MARATHON 🐻 | confidence: 0.31 < 0.60 |
| 1135 | FAIL | 0.00 | 0 | 0 | — | — | ROTTERDAM HAS ADDED TWO TURTLES 🐢🐢 😇 | ocr: no street candidates |
| 1272 | FAIL | 0.29 | 4 | 4 | 0.0 | 0.14 | THE ST ALBANS SHARK 🦈 | confidence: 0.29 < 0.60 |
| 1294 | FAIL | 0.24 | 5 | 3 | 0.0 | 0.09 | A WHALE IN WALES | confidence: 0.24 < 0.60 |
| 1333 | FAIL | 0.00 | 1 | 0 | — | — | YESSSS 🦈🦈🦈 50km DE GPS DRAWING DANS PARIS! | crossref: no consensus cluster |
| 1359 | FAIL | 0.00 | 0 | 0 | — | — | AMSTERDAM IS AJAX - AJAX IS AMSTERDAM | ocr: no street candidates |
| 1565 | FAIL | 0.00 | 0 | 0 | — | — | STRAVA LOGO IN HAMBURG | ocr: no street candidates |
