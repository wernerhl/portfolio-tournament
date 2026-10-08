# research/

Working code delivered with execution orders, kept for reproducibility. **Not served by the site**: the deploy jobs
remove this folder before the Pages upload (see the `rm -rf research` step in each deploy job).

- `ml_stratification_test/` — the design workspace's stratification test (delivered 7 October 2026 with the follow-up
  order; `feats2.py`, `ml2.py`, `uni2.py` and their result tables). Its data pickles were not delivered; `sec.py` reads
  the SEC contact from `SEC_USER_AGENT` instead of a literal. The repository's single harness is
  `scripts/analyst/walkforward_test.py`; `reports/analyst_followup_2026-10-07.md` reconciles the two.
