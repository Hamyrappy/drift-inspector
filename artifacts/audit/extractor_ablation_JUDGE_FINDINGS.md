# Extractor Ablation — Human-Aligned LLM Judge Run (gpt-oss vs qwen control)

**Date:** 2026-07-07
**Status:** `partial_quota` — STOPPED by Google AI Studio free-tier **daily** quota after 14 of 600 items.
**Judge:** gemini-2.5-flash-lite via Google AI Studio OpenAI-compatible endpoint
(`https://generativelanguage.googleapis.com/v1beta/openai/`), the same human-aligned
judge (κ=0.863 vs human majority) established in `notebooks/human_validation.ipynb`.
**No fallback judge was used** (a same-family judge is exactly what the ablation must avoid).

## Bottom line

The run cannot be completed on this API key before the deadline. The binding limit is a
**per-day** cap of **20 requests/day** for `gemini-2.5-flash-lite` free tier on this
project — not the ~1000/day the task assumed and not a per-minute limit. Verbatim quota
violation returned by the API:

```
status: RESOURCE_EXHAUSTED
metric:  generativelanguage.googleapis.com/generate_content_free_tier_requests
quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier
quotaValue (limit): 20
model:   gemini-2.5-flash-lite
```

At 20 requests/day the full 600-request run (300 gpt-oss + 300 qwen) needs ~30 days.
The daily allowance today was consumed by: 1 smoke call + 14 persisted judge calls +
a handful of diagnostic probes = 20. The `retryDelay: 14s` in the body is a token-bucket
refill hint and is misleading here; the **daily** bucket does not refill until the
free-tier daily reset (Pacific midnight). A single probe succeeded only transiently before
the daily counter saturated.

**To finish this ablation, one of the following is required (all outside this run's mandate):**
- Enable billing / a paid tier on the `GOOGLE_API_KEY` project (raises daily cap far above 600), then re-run — the script is resumable and will skip the 14 done items; ~600 calls, est. cost ~\$0.2; OR
- Spread across ~30 days at 20/day (infeasible before Fri Jul 10); OR
- Use a different Google project/key with a higher free-tier allocation.

## What we have (partial, NOT sufficient for a conclusion)

The 14 persisted items are all **gpt-oss, year 2020 only** (sampling is year-ordered and the
run stopped in the first stratum). This is a single-year, tiny, non-representative slice.
Zero qwen-control items were reached.

| Sample | n | GOOD | BAD | UNSURE | GOOD % (drop-Unsure) | Wilson 95% |
|---|---|---|---|---|---|---|
| gpt-oss-120b | 14 | 13 | 1 | 0 | 92.9% | [68.5, 98.7] |
| qwen control | 0 | — | — | — | — | — |

gpt-oss BAD failure modes (n=1): `background_context` ×1 (a motivation sentence judged
non-contribution — the expected dominant ACC failure mode).

**Reference points (not compared — partial data too thin):**
- May human-validation: judge said GOOD for ~97.8% of the 136 human-sampled **qwen** claims.
- Paper Table 1 ACC coverage (qwen yield): 83.9%.

The 92.9% GOOD is directionally consistent with quality parity but the CI is enormous
[68.5, 98.7] and there is no same-day qwen control to net out judge-version drift, so
**no ablation verdict can be drawn.** Verdict: **mixed** (i.e. insufficient evidence,
pending completion — not a contradiction of parity).

## Provenance / reproducibility

- Judge prompt reused **verbatim** from the notebook judge cell: raw `llm_as_judge_prompt`
  from `src/acc/prompts.py` with only `<<TITLE>>/<<ABSTRACT>>/<<CLAIM>>` substituted
  (`<<DOMAIN>>` left literal, exactly as `human_validation.ipynb` cell 24 does), same system
  prompt, temperature 0.0, top_p 1.0, max_tokens 400, `response_format=json_object`, same
  `extract_first_json_object` + `normalize_judge_response` parsing.
- **Prompt hash note:** current `llm_as_judge_prompt` sha256[:12] = `a2869fe464bf`. The hash
  recorded in the prior human-validation run was `34e9c8b0003a` — the prompt in `prompts.py`
  has been edited since May. Both this run and any re-run use the identical *current* object,
  and the qwen control (once run) uses the same object, so the ablation stays internally valid;
  but the current judge is **not** byte-identical to the one that produced the May κ=0.863 / 97.8%.
- Samples are deterministic (seed 42), 300 each, stratified 50/year, no missing abstracts,
  no duplicate claim_ids. See `extractor_ablation_sample_gptoss.csv` / `_qwen.csv`.

## Resumability

`extractor_ablation_judge_results.csv` is written incrementally (append + fsync per item)
with `claim_id` keys; on restart the runner skips already-present ids. Re-running once quota
allows will judge the remaining **586** items (286 gpt-oss year 2021–2025 + 300 qwen),
gpt-oss first, then the qwen control.

## Files

- `extractor_ablation_sample.py` — deterministic sampler (seed 42, 50/year).
- `extractor_ablation_sample_gptoss.csv`, `extractor_ablation_sample_qwen.csv` — the 300+300 samples.
- `extractor_ablation_judge.py` — resumable judge runner (verbatim prompt/parse; token-paced; daily-quota-aware stop).
- `extractor_ablation_judge_results.csv` — 14 persisted results (no API key).
- `extractor_ablation_analyze.py` — Wilson CIs + failure-mode breakdown.
- `extractor_ablation_JUDGE_FINDINGS.md` — this file.

## Recommended paper sentence

**Do NOT add a parity sentence yet.** The scaling paragraph should not claim gpt-oss/qwen
extractor parity until the judge run completes with the qwen control. If, after completing
the 600-item run, gpt-oss GOOD-rate CI overlaps the qwen control's, a defensible dry sentence is:

> On a 300-claim stratified sample, an independent human-aligned LLM judge (a different model
> family from either extractor) rated the gpt-oss-120b extraction GOOD at a rate statistically
> indistinguishable from the qwen pipeline, indicating the extractor substitution does not
> degrade claim quality at scale.

This sentence is **not yet supported** by data and must be gated on the completed run.

## CORRECTION (2026-07-07, post-review)

The "prompt drift" concern above is largely retracted after a git-history diff:

- **Extractor**: the current templated prompt rendered with DOMAIN=NLP is byte-identical
  (sha256[:12] = f9a9b434c72c) to the prompt used for the qwen EMNLP corpus, emnlp_full,
  acl_full, and the full-anthology extraction. Unchanged in substance since 2026-05-24.
- **Judge**: current rendered prompt = 26802a1ff768 = the 2026-06-02 version (534437e).
  Diff vs the prompt that produced kappa=0.863 on 2026-05-26 (da51c62cb70c, dc40ba0):
  ONLY the removal of the item_id echo field from the JSON output examples, plus the
  <<DOMAIN>> templating. All GOOD/BAD/UNSURE criteria and issue categories identical.
- The 34e9c8b0003a hash printed in notebooks/human_validation.ipynb cell 7 output matches
  no committed revision — it is a stale provenance print from an intermediate working-tree
  state, not evidence of criteria drift.

No prompt restore is needed. Release note: kappa=0.863 was measured with da51c62cb70c;
the shipped prompt differs only by the dropped item_id example field and domain templating.
