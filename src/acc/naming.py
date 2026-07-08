"""
LLM cluster naming (standardized).

For each cluster, build a compact "card" — representative claims (closest to the
cluster centroid), class-based TF-IDF keyword hints, size, and year/venue spread
— and ask an LLM for a concise ``short`` label + a descriptive ``full`` name
(see ``prompts.acc_namer_prompt``). Writes ``data/clusters/cluster_names.json``
= {cluster_id: {short, full}}, which ``inspector.build_data`` prefers over the
c-TF-IDF descriptor. Reproducible: rerun to re-name after re-clustering.
"""
import json
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from . import config
from . import corpus
from . import llm
from . import prompts
from . import cluster as _ctfidf

_NAME_SCHEMA = {
    "type": "object",
    "properties": {"short": {"type": "string"}, "full": {"type": "string"}},
    "required": ["short", "full"], "additionalProperties": False,
}


def _corpus_with_text():
    """acc_clusters.csv joined with atomic_claim (by claim_id), aligned to EMB_CACHE."""
    acc = pd.read_csv(config.ACC_CLUSTERS)
    emb = np.load(config.EMB_CACHE)
    if len(acc) != len(emb):
        raise RuntimeError(f"acc_clusters={len(acc)} vs emb={len(emb)} — re-run `acc cluster`")
    manifest = corpus.load_manifest()
    disp = [s for s in manifest["sources"] if s["id"] in manifest["display"]["sources"]]
    src = pd.concat([corpus.read_source_claims(s)[["claim_id", "atomic_claim"]] for s in disp],
                    ignore_index=True).drop_duplicates("claim_id")
    acc = acc.merge(src, on="claim_id", how="left")
    acc["atomic_claim"] = acc["atomic_claim"].fillna("").astype(str)
    return acc, emb


def _card(acc, emb, cid, desc, k_reps=22):
    m = (acc["cluster"] == cid).to_numpy()
    idx = np.where(m)[0]
    sub = emb[idx].astype(np.float64)
    cen = sub.mean(0)
    sims = sub @ cen / (np.linalg.norm(sub, axis=1) * np.linalg.norm(cen) + 1e-9)
    reps = idx[np.argsort(sims)[::-1][:k_reps]]
    claims = acc["atomic_claim"].to_numpy()[reps]
    years = acc.loc[m, "year"]
    yr = f"{int(years.min())}–{int(years.max())}"
    venues = acc.loc[m, "venue"].value_counts().to_dict() if "venue" in acc.columns else {}
    ven = ", ".join(f"{k}:{v}" for k, v in venues.items())
    hint = desc[cid][1] if cid in desc else ""
    lines = [f"Size: {int(m.sum())} claims", f"Years: {yr}", f"Venues: {ven}",
             f"Keyword hints: {hint}", "Representative claims:"]
    lines += [f"- {c}" for c in claims]
    return "\n".join(lines)


# max_tokens must cover the reasoning channel AND the JSON answer: at high
# reasoning effort gpt-oss can spend a few thousand tokens thinking, so a tight
# budget (e.g. 4000) leaves content empty/truncated -> a nameable cluster falls
# back to c-TF-IDF. Give it ample room, and retry on the transient proxy errors.
@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=2, max=20))
def _name_call(client, model, effort, prompt):
    kw = dict(model=model, temperature=0, max_tokens=16000,
              messages=[{"role": "user", "content": prompt}],
              response_format={"type": "json_schema", "json_schema":
                               {"name": "clname", "schema": _NAME_SCHEMA, "strict": True}})
    if "gpt-oss" in model.lower():
        kw["reasoning_effort"] = effort
    r = client.chat.completions.create(**kw)
    content = r.choices[0].message.content
    if not content or not content.strip():          # reasoning exhausted the budget
        raise ValueError("empty content (raise max_tokens / lower effort)")
    obj = json.loads(content)
    return {"short": str(obj["short"]).strip(), "full": str(obj["full"]).strip()}


def name_clusters(provider="auto", model="gpt-oss", effort="high", workers=16,
                  domain="NLP", only=None):
    """Name clusters via LLM. ``only`` (iterable of cluster ids) re-names just
    those and merges into the existing cluster_names.json (leaving the rest)."""
    acc, emb = _corpus_with_text()
    desc = _ctfidf.compute_descriptors(acc)
    cids = sorted(int(c) for c in acc["cluster"].unique() if int(c) != -1)
    if only is not None:
        only = {int(c) for c in only}
        cids = [c for c in cids if c in only]
    cards = {c: _card(acc, emb, c, desc) for c in cids}

    client = llm.get_client(provider)
    resolved = llm.resolve_model(client, model)
    print(f"Naming {len(cids)} clusters · {provider}:{resolved} effort={effort} workers={workers}")

    def name_one(cid):
        prompt = (prompts.acc_namer_prompt
                  .replace("<<DOMAIN>>", domain).replace("<<CARD>>", cards[cid]))
        try:
            return cid, _name_call(client, resolved, effort, prompt)
        except Exception as e:
            return cid, {"short": desc[cid][0], "full": desc[cid][1], "error": str(e)[:120]}

    # when re-naming a subset, start from the existing names and overwrite `only`
    names = {}
    if only is not None and config.CLUSTER_NAMES.exists():
        names = json.loads(config.CLUSTER_NAMES.read_text(encoding="utf-8"))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for cid, obj in ex.map(name_one, cids):
            names[str(cid)] = obj

    config.CLUSTER_NAMES.parent.mkdir(parents=True, exist_ok=True)
    with open(config.CLUSTER_NAMES, "w", encoding="utf-8") as f:
        json.dump(names, f, indent=2, ensure_ascii=False)
    n_err = sum(1 for v in names.values() if "error" in v)
    print(f"Wrote {config.CLUSTER_NAMES} — {len(names)} names ({n_err} fell back to c-TF-IDF)")
    for c in cids[:12]:
        print(f"  {c:>2}  {names[str(c)]['short']:<28}  {names[str(c)]['full']}")
    return names
