# Phase 4a PoC results — 20 routes

**shipped:** 0/20 (0%) at default threshold conf ≥ 0.6

## Stage funnel

| stage | passed | %n |
|---|---:|---:|
| contour ≥ 10 px        | 20/20 | 100% |
| OCR ≥ 1 street         | 10/20     | 50% |
| crossref cluster       | 9/20   | 45% |
| georef fit (≥3 GCPs)   | 7/20  | 35% |
| map-match snapped      | 0/20     | 0% |
| **shipped (conf ≥ 0.6)** | **0/20** | **0%** |

## Failure modes

| mode | count |
|---|---:|
| ocr_no_street_candidates | 10 |
| mapmatch | 7 |
| georef_too_few_gcps | 2 |
| crossref_no_cluster | 1 |

## Per-route detail

| id | flag | conf | candidates | GCPs | RMSE m | fidelity | title | failure |
|---:|:--|---:|---:|---:|---:|---:|---|---|
| 5 | FAIL | 0.00 | 0 | 0 | — | — | MANCHESTER DOG | ocr: no street candidates |
| 30 | FAIL | 0.00 | 0 | 0 | — | — | THE ONE WITH THE DOGGO IN VIENNA 🐶❤️ | ocr: no street candidates |
| 36 | FAIL | 0.00 | 0 | 0 | — | — | 100k GPS ART TOUR OF WEST DEVON. WOOF! | ocr: no street candidates |
| 53 | FAIL | 0.00 | 12 | 6 | 12.7 | — | REGENT’S PARK, GREAT DAY FOR DOGGIN | mapmatch: graph load: SSLError(MaxRetryError("HTTPSConnectionPool(host='overpass-api.de', port=443): Max retries exceeded with url: /api/interpreter (Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate in certificate chain (_ssl.c:1000)')))")) |
| 60 | FAIL | 0.00 | 7 | 5 | 0.0 | — | DOGGIN’ MY WAY THROUGH HAMPSTEAD HEATH | mapmatch: graph load: SSLError(MaxRetryError("HTTPSConnectionPool(host='overpass-api.de', port=443): Max retries exceeded with url: /api/interpreter (Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate in certificate chain (_ssl.c:1000)')))")) |
| 208 | FAIL | 0.00 | 0 | 0 | — | — | BERLIN MUTT | ocr: no street candidates |
| 248 | FAIL | 0.00 | 0 | 0 | — | — | 1st BERLIN DRAWING. HUAWEI ❌ ADIDAS /// 🦅🥳🙌🏻 | ocr: no street candidates |
| 577 | FAIL | 0.00 | 10 | 3 | 0.0 | — | DUMBO VISITS CAMBRIDGE | mapmatch: graph load: SSLError(MaxRetryError("HTTPSConnectionPool(host='overpass-api.de', port=443): Max retries exceeded with url: /api/interpreter (Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate in certificate chain (_ssl.c:1000)')))")) |
| 584 | FAIL | 0.00 | 15 | 5 | 2.5 | — | TRAVELLING ELEPHANT, UK 🐘🇬🇧 | mapmatch: graph load: SSLError(MaxRetryError("HTTPSConnectionPool(host='overpass-api.de', port=443): Max retries exceeded with url: /api/interpreter (Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate in certificate chain (_ssl.c:1000)')))")) |
| 799 | FAIL | 0.00 | 0 | 0 | — | — | BULLFIGHT IN MUNICH | ocr: no street candidates |
| 800 | FAIL | 0.00 | 0 | 0 | — | — | MUNICH LION | ocr: no street candidates |
| 910 | FAIL | 0.00 | 12 | 5 | 5.5 | — | THE LONDON MARATHON. THIS IS MY RACE, THIS IS MY CITY, LONDO | mapmatch: graph load: SSLError(MaxRetryError("HTTPSConnectionPool(host='overpass-api.de', port=443): Max retries exceeded with url: /api/interpreter (Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate in certificate chain (_ssl.c:1000)')))")) |
| 921 | FAIL | 0.00 | 13 | 6 | 5.4 | — | THE HACKNEY HORSE 🐎 | mapmatch: graph load: SSLError(MaxRetryError("HTTPSConnectionPool(host='overpass-api.de', port=443): Max retries exceeded with url: /api/interpreter (Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate in certificate chain (_ssl.c:1000)')))")) |
| 942 | FAIL | 0.00 | 13 | 5 | 0.0 | — | THE ONE WITH THE LONDON BEAR HALF MARATHON 🐻 | mapmatch: graph load: SSLError(MaxRetryError("HTTPSConnectionPool(host='overpass-api.de', port=443): Max retries exceeded with url: /api/interpreter (Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate in certificate chain (_ssl.c:1000)')))")) |
| 1135 | FAIL | 0.00 | 0 | 0 | — | — | ROTTERDAM HAS ADDED TWO TURTLES 🐢🐢 😇 | ocr: no street candidates |
| 1272 | FAIL | 0.00 | 4 | 2 | — | — | THE ST ALBANS SHARK 🦈 | georef: only 2 GCPs (need ≥3) |
| 1294 | FAIL | 0.00 | 5 | 2 | — | — | A WHALE IN WALES | georef: only 2 GCPs (need ≥3) |
| 1333 | FAIL | 0.00 | 1 | 0 | — | — | YESSSS 🦈🦈🦈 50km DE GPS DRAWING DANS PARIS! | crossref: no consensus cluster |
| 1359 | FAIL | 0.00 | 0 | 0 | — | — | AMSTERDAM IS AJAX - AJAX IS AMSTERDAM | ocr: no street candidates |
| 1565 | FAIL | 0.00 | 0 | 0 | — | — | STRAVA LOGO IN HAMBURG | ocr: no street candidates |
