# Reproducibility report: starter

- Seed: `20261022`  |  Result: **PASS**
- Command: `python generator/generate.py --seed 20261022 --scale starter` (run twice)
- Files compared: 31, identical: 31
- Dataset fingerprint run 1: `2806a4c142016a8ecd51bb1d01fc267bad9c4f8a52d2b7d28a493be5ffdba623`
- Dataset fingerprint run 2: `2806a4c142016a8ecd51bb1d01fc267bad9c4f8a52d2b7d28a493be5ffdba623`
- Control (seed 20261023): 31 of 31 files differ

## Checks

| Check | Result |
|---|---|
| row counts identical across runs | PASS |
| every file checksum identical across runs | PASS |
| manifest.json identical across runs | PASS |
| dataset fingerprint identical | PASS |
| control run with another seed differs (so the comparison is meaningful) | PASS |

## Row counts

| Table | Run 1 | Run 2 | Match |
|---|---:|---:|---|
| appeal | 23 | 23 | yes |
| assignment | 50 | 50 | yes |
| course | 20 | 20 | yes |
| enrollment | 506 | 506 | yes |
| feedback | 2,120 | 2,120 | yes |
| grade | 800 | 800 | yes |
| grade_criterion_score | 3,214 | 3,214 | yes |
| grade_event | 877 | 877 | yes |
| learner | 300 | 300 | yes |
| resubmission | 86 | 86 | yes |
| rubric | 50 | 50 | yes |
| rubric_criterion | 200 | 200 | yes |
| submission | 800 | 800 | yes |
| submission_artifact | 1,282 | 1,282 | yes |

## File checksums (SHA-256, first 16 characters)

| File | Run 1 | Run 2 | Match |
|---|---|---|---|
| csv/appeal.csv | `8212d9913d23bc12` | `8212d9913d23bc12` | yes |
| csv/assignment.csv | `082694b61c9e7c28` | `082694b61c9e7c28` | yes |
| csv/course.csv | `d506fed8e25c6296` | `d506fed8e25c6296` | yes |
| csv/enrollment.csv | `3b9e867c44ec9528` | `3b9e867c44ec9528` | yes |
| csv/feedback.csv | `d4301769d25c6607` | `d4301769d25c6607` | yes |
| csv/grade.csv | `1a9c6f1dd1f82cd3` | `1a9c6f1dd1f82cd3` | yes |
| csv/grade_criterion_score.csv | `f4177af538d78c70` | `f4177af538d78c70` | yes |
| csv/grade_event.csv | `77f4838723bb93ce` | `77f4838723bb93ce` | yes |
| csv/learner.csv | `4a3f2820591bdbee` | `4a3f2820591bdbee` | yes |
| csv/resubmission.csv | `13df99cd5a0fbd5f` | `13df99cd5a0fbd5f` | yes |
| csv/rubric.csv | `66753ac947c4f77c` | `66753ac947c4f77c` | yes |
| csv/rubric_criterion.csv | `32b5f984cb129561` | `32b5f984cb129561` | yes |
| csv/submission.csv | `8a6c5a48ecda8da6` | `8a6c5a48ecda8da6` | yes |
| csv/submission_artifact.csv | `ff39a9233f71405f` | `ff39a9233f71405f` | yes |
| ground_truth.csv | `098a4fb1d13aa0b9` | `098a4fb1d13aa0b9` | yes |
| ground_truth.json | `9e122c566f3478c8` | `9e122c566f3478c8` | yes |
| json/appeal.json | `31e1137879209a99` | `31e1137879209a99` | yes |
| json/assignment.json | `e7d5ae4b38fa6b91` | `e7d5ae4b38fa6b91` | yes |
| json/course.json | `d78bcea10c5dad29` | `d78bcea10c5dad29` | yes |
| json/enrollment.json | `59500e62e50df498` | `59500e62e50df498` | yes |
| json/feedback.json | `d1adf4a53fd94796` | `d1adf4a53fd94796` | yes |
| json/grade.json | `3293f2996f3b54d0` | `3293f2996f3b54d0` | yes |
| json/grade_criterion_score.json | `4b88ab9367cbec84` | `4b88ab9367cbec84` | yes |
| json/grade_event.json | `944a43049697f4b2` | `944a43049697f4b2` | yes |
| json/learner.json | `ccf689d4b89dc443` | `ccf689d4b89dc443` | yes |
| json/resubmission.json | `316696e3393b2f61` | `316696e3393b2f61` | yes |
| json/rubric.json | `50b5462d69a094ab` | `50b5462d69a094ab` | yes |
| json/rubric_criterion.json | `c23e185e4bbf8a61` | `c23e185e4bbf8a61` | yes |
| json/submission.json | `929de78b47859e44` | `929de78b47859e44` | yes |
| json/submission_artifact.json | `4893580d231f8dc0` | `4893580d231f8dc0` | yes |
| sql/seed.sql | `45bfeab79688199c` | `45bfeab79688199c` | yes |
