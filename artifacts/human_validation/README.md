# Human validation — protocol, sheets, and judge provenance

This folder documents the human study behind the ACC extraction-quality claim in
the paper (an LLM-as-judge calibrated against three human annotators), and ships
the de-identified annotation sheets and the judge output so the agreement numbers
are reproducible.

## Files

- `annotator_sheet-1.csv`, `annotator_sheet-2.csv`, `annotator_sheet-3.csv` — the
  three annotators' independent labels. Columns:
  `item_id, group_id, paper_title, abstract, atomic_claim, label, main_issue, notes`.
  Sheets are **de-identified**: they carry no annotator names, emails, or other PII —
  only the claim under review and the label. Annotators are referred to by sheet
  number only.
- `judge_results.csv` — the LLM-as-judge verdict for each item (GOOD / BAD / UNSURE
  plus issue category), used to compute judge-vs-human agreement.

## Protocol (summary)

- Each item is one atomic contribution claim (ACC) shown with its source paper
  title and abstract. The task is to label the claim **GOOD** (a self-contained,
  faithful, atomic contribution of the paper) or **BAD**, with a `main_issue`
  category (e.g. `too_vague`, `mixed_claims`, `not_self_contained`,
  `background_context`) and free-text `notes`. `UNSURE` is allowed and dropped
  pairwise before agreement is computed (drop-Unsure convention).
- A pool of deliberately degraded ("bad") claims is mixed with genuine extractions
  so the label distribution is not trivially all-GOOD; the degraded pool and the
  master construction sheet are internal and **not shipped** (see the export's
  excluded list).
- Reported agreement: Fleiss kappa = 0.844 across the three annotators; the
  human-aligned LLM judge agrees with the majority-of-3 human label at accuracy
  0.945 / kappa = 0.863. The reproduction lives in `notebooks/human_validation.ipynb`.

## Judge prompt provenance (important)

The judge kappa = 0.863 was measured on 2026-05-26 with the judge prompt at git
blob `da51c62cb70c` (commit `dc40ba0`). The judge prompt shipped in this release
(`src/acc/prompts.py :: llm_as_judge_prompt`) is **not byte-identical** to that
one. A git-history diff shows the only differences are:

1. removal of the `item_id` echo field from the JSON output examples, and
2. `<<DOMAIN>>` templating (the domain is now a substituted placeholder rather than
   hard-coded "NLP").

All GOOD / BAD / UNSURE criteria and every issue category are identical between the
two versions. The rendered prompt is therefore criteria-equivalent to the one that
produced kappa = 0.863; the substitutions do not change what the judge is asked to
decide. Full analysis: `artifacts/audit/extractor_ablation_JUDGE_FINDINGS.md`
(see the "CORRECTION" section).

Note: an earlier working-tree provenance print in `human_validation.ipynb` recorded
a prompt hash (`34e9c8b0003a`) that matches no committed revision — it was a stale
print from an intermediate edit, not evidence of criteria drift, and can be ignored.
