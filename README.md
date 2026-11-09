# EvidenceLens

EvidenceLens answers a question about one recorded CCTV clip from an evidence file, not from the video. A detector, a tracker, and rules write that file. The language model may only copy timestamps the code already computed, and a validator checks every citation before it is shown. If the evidence cannot answer, the system abstains. Every answer is for human review, not proof.

This is a CS3235 course project at RV University. Condition B is the path that is built: the question plus `evidence.json`. Conditions A and C are not built.

## Setup

Python 3.10.11. From the project folder:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

On macOS or Linux, activate with `source .venv/bin/activate`.

Create a file named `.env` in this folder. Set the variable `GEMINI_API_KEY` there. `ask.py` loads that file with python-dotenv. Do not commit `.env`. Ask stays off in the app until the variable is set.

The first detection run downloads the YOLO11s weights. Those weights (`*.pt`) are not in this repository.

## Run the app

```bash
streamlit run app.py
```

The app opens the Home, Library, Investigate, Report, and Analyse pages. Investigate asks through the same answer cache as `ask.py` and calls the model only when that question is not already cached.

A single question can also be run from the command line:

```bash
python ask.py <clip_id> "Did anyone enter the restricted zone?"
```

`--dry-run` prints the prompt and does not call the model.

## Tests

These scripts do not need a camera, a GPU, or an API key:

```bash
python test_rules.py
python test_llm_cache.py
python test_record_clip.py
python test_live_monitor.py
python ui/test_eval_summary.py
python eval/test_validator_stress.py
python eval/test_validate_hardening.py
python eval/test_abstention_scoring.py
```

Each script prints its own pass count.

## eval/

| File | What it does |
|---|---|
| `validator_stress.py` | Runs the real `validate()` on 20 bad replies and 6 good replies. No model call. |
| `test_validator_stress.py` | Checks that the stress script runs and that the good replies are accepted. |
| `test_validate_hardening.py` | Checks the extra validator rejections. No model call. |
| `run_abstention.py` | Asks the questions in `abstention_questions.csv` through the app's cache. |
| `test_abstention_scoring.py` | Scores synthetic abstention rows. No model call. |
| `citation_report.py` | Counts cached answers. No model call. |
| `results_validator.csv` | The validator stress result. |
| `results_validator_before.csv` | The stress result from before the validator hardening. |
| `results_abstention.csv` | The abstention-sheet result. |
| `results_citations.csv` | The citation-count result. |
| `labels_A.csv`, `labels_B.csv`, `LABELLING_GUIDE.md` | Blank labelling sheets. They do not contain system answers. |

On the small sets stored in those result files: the validator caught 18/20 bad replies and wrongly rejected 0/6 good ones; the system refused 10/10 unanswerable questions and answered 2/2 ordinary ones; 32/32 cached answers passed validation, 23 on the first attempt. Event detection accuracy has not been measured on a labelled set.

## Clips

The CAVIAR clips are from the public dataset at <https://homepages.inf.ed.ac.uk/rbf/CAVIAR/> (EC Funded CAVIAR project/IST 2001 37540). The video files are not in this repository. Recorded and uploaded clips are not included, for privacy. `data/clips_meta.json` and the `evidence.json` packages are included. Each evidence file is under 1 MB.

## Limits

- The fall rule is not built, so a fall cannot be checked.
- Only condition B is built. Conditions A and C are not.
- One fixed camera. The system does not identify people, and it does not judge intent, emotion, or health.
- Event detection accuracy has not been measured on a labelled set.

## Authors

CS3235, RV University. Author names and USNs are not written in this repository.
