"""
LLM-as-judge for extraction quality.

Two uses:
  * ``judge_source`` — grade a sample of a source's claims GOOD / BAD / UNSURE
    to compare extraction quality across venues / extractors.
  * ``judge_validation`` — grade the human-validation set and report agreement
    (accuracy + Cohen's kappa) against the human annotators, so a new judge/model
    can be checked against the published κ.

Provider/model-agnostic via acc.llm. One claim per call, thread-pooled.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from . import config
from . import llm
from . import prompts

JUDGE_SYSTEM = "You are a careful scientific reviewer. Return only valid JSON."
_LABELS = {"GOOD", "BAD", "UNSURE"}


def _parse_label(content: str) -> str:
    content = (content or "").strip()
    try:
        obj = json.loads(re.search(r"\{[\s\S]*\}", content).group(0))
        if "evaluations" in obj and obj["evaluations"]:
            obj = obj["evaluations"][0]
        lab = str(obj.get("label", "")).upper()
        if lab in _LABELS:
            return lab
    except Exception:
        pass
    m = re.search(r"\b(GOOD|BAD|UNSURE)\b", content.upper())
    return m.group(1) if m else "UNSURE"


def judge_items(items, *, provider="auto", model="gpt-oss", domain=prompts.DEFAULT_DOMAIN,
                workers=24, reasoning_effort="high", max_tokens=4000):
    """items: list of dicts with title/abstract/claim. Returns list of labels."""
    client = llm.get_client(provider)
    model = llm.resolve_model(client, model)
    template = prompts.judge_prompt(domain)
    rf = ({"type": "json_object"} if provider == "openrouter"
          else {"type": "json_object"})

    def one(it):
        user = (template.replace("<<TITLE>>", str(it.get("title", "")))
                .replace("<<ABSTRACT>>", str(it.get("abstract", "")))
                .replace("<<CLAIM>>", str(it.get("claim", ""))))
        kwargs = dict(model=model, temperature=0, max_tokens=max_tokens, response_format=rf,
                      messages=[{"role": "system", "content": JUDGE_SYSTEM},
                                {"role": "user", "content": user}])
        if reasoning_effort and llm.supports_reasoning_effort(model):
            kwargs["reasoning_effort"] = reasoning_effort
        try:
            r = client.chat.completions.create(**kwargs)
            return _parse_label(r.choices[0].message.content)
        except Exception as e:
            return f"ERROR:{type(e).__name__}"

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(one, items))


def judge_source(source_id, sample_n=120, *, seed=42, **kw):
    src = config.CLAIMS_SOURCES_DIR / source_id
    claims = pd.read_csv(src / "claims.csv")
    papers = pd.read_csv(src / "papers.csv")[["paper_id", "title", "abstract"]]
    df = claims.merge(papers, on="paper_id", how="left")
    if sample_n and len(df) > sample_n:
        df = df.sample(n=sample_n, random_state=seed)
    items = [{"title": r.title, "abstract": r.abstract, "claim": r.atomic_claim} for r in df.itertuples()]
    labels = judge_items(items, **kw)
    vc = pd.Series(labels).value_counts()
    good = int(vc.get("GOOD", 0))
    rated = sum(v for k, v in vc.items() if not str(k).startswith("ERROR"))
    print(f"[{source_id}] judged {len(items)} claims: " +
          " · ".join(f"{k}={v}" for k, v in vc.items()) +
          (f"  → GOOD {good/rated*100:.1f}%" if rated else ""))
    return {"source": source_id, "n": len(items), "counts": vc.to_dict(),
            "good_pct": (good / rated * 100) if rated else None}


def filter_source(source_id, sample_n=None, drop=("BAD",), write=True, **kw):
    """Judge a source's claims and drop the bad ones — an optional pipeline step.

    Writes the survivors to ``<source>/claims_filtered.csv`` (same schema as
    claims.csv); the canonical ``claims.csv`` is never modified. Not wired into
    the build — point the manifest at the filtered file only when you want it.
    """
    src = config.CLAIMS_SOURCES_DIR / source_id
    claims = pd.read_csv(src / "claims.csv")
    papers = pd.read_csv(src / "papers.csv")[["paper_id", "title", "abstract"]]
    df = claims.merge(papers, on="paper_id", how="left")
    if sample_n and len(df) > sample_n:
        df = df.sample(n=sample_n, random_state=42).reset_index(drop=True)
    items = [{"title": r.title, "abstract": r.abstract, "claim": r.atomic_claim}
             for r in df.itertuples()]
    df = df.assign(judge_label=judge_items(items, **kw))
    drop_set = {d.upper() for d in drop}
    dropped = df[df["judge_label"].isin(drop_set)]
    kept = df[~df["judge_label"].isin(drop_set)]
    print(f"[{source_id}] filter: {len(df)} judged · {len(dropped)} dropped "
          f"({'/'.join(sorted(drop_set))}) · {len(kept)} kept "
          f"({len(kept)/max(len(df),1)*100:.1f}%)")
    for r in dropped.head(5).itertuples():
        print(f"   DROP [{r.judge_label}] {str(r.atomic_claim)[:96]}")
    if write:
        out = kept[list(claims.columns)]
        out.to_csv(src / "claims_filtered.csv", index=False)
        print(f"   wrote {src/'claims_filtered.csv'} ({len(out)} claims) — "
              f"not used until the manifest points at it")
    return {"judged": len(df), "dropped": len(dropped), "kept": len(kept)}


def judge_validation(*, sample_n=None, **kw):
    """Judge the human-validation items; report accuracy + kappa vs annotators."""
    from sklearn.metrics import cohen_kappa_score
    hv = config.ARTIFACTS / "human_validation"
    master = pd.read_csv(hv / "master_sheet.csv")
    if sample_n and len(master) > sample_n:
        master = master.sample(n=sample_n, random_state=42)
    items = [{"title": r.paper_title, "abstract": r.abstract, "claim": r.atomic_claim}
             for r in master.itertuples()]
    judge = judge_items(items, **kw)
    master = master.assign(judge_label=judge)
    bin_judge = master["judge_label"].map(lambda x: "BAD" if x == "BAD" else "GOOD")

    # proxy ground truth: deliberately-degraded claims (is_negative) should be BAD
    truth = master["is_negative"].map(lambda neg: "BAD" if neg else "GOOD")
    acc = (bin_judge.values == truth.values).mean()
    kappa = cohen_kappa_score(truth, bin_judge)
    print(f"[validation] {len(master)} items · judge vs is_negative proxy: "
          f"acc {acc*100:.1f}% · κ {kappa:.3f}")

    # agreement vs each human annotator, where available
    for n in (1, 2):
        ap = hv / f"annotator_sheet-{n}.csv"
        if not ap.exists():
            continue
        ann = pd.read_csv(ap)[["item_id", "label"]].dropna()
        if ann.empty:
            continue
        merged = master.merge(ann, on="item_id", how="inner")
        if merged.empty:
            continue
        hb = merged["label"].str.upper().map(lambda x: "BAD" if x == "BAD" else "GOOD")
        jb = merged["judge_label"].map(lambda x: "BAD" if x == "BAD" else "GOOD")
        a = (hb.values == jb.values).mean()
        k = cohen_kappa_score(hb, jb)
        print(f"[validation] vs annotator-{n} ({len(merged)} items): acc {a*100:.1f}% · κ {k:.3f}")
    return master
