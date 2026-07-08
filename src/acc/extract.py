"""
Atomic Contribution Claim extraction — consolidated from notebook 02.

Venue-agnostic: reads any source's ``papers.csv`` and writes ``claims.csv`` in
the canonical schema. Provider-agnostic via acc.llm (auto-selects the
configured backend). Concurrency is a thread pool over the sync OpenAI client;
structured output uses a strict json_schema where the backend honours it.
Ledger-deduplicated and checkpointed, so a run can be re-run / resumed safely.
"""
import hashlib
import json
import os
import re
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from . import config
from . import llm
from . import prompts

CLAIM_SCHEMA = {
    "type": "object",
    "properties": {"claims": {"type": "array", "items": {
        "type": "object", "properties": {"text": {"type": "string"}},
        "required": ["text"], "additionalProperties": False}}},
    "required": ["claims"], "additionalProperties": False,
}
SYSTEM_PROMPT = "You are an expert scientometric extraction engine. Return only valid JSON."


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text)).casefold()
    return re.sub(r"\s+", " ", text).strip()


def make_claim_id(paper_id, claim_text, prompt_hash, model_name) -> str:
    payload = "|".join([str(paper_id), _norm(claim_text), prompt_hash, model_name])
    return "clm_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _parse(content: str) -> list:
    content = (content or "").strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*", "", content).strip().rstrip("`").strip()
    try:
        obj = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            raise ValueError("no JSON object in model output")
        obj = json.loads(m.group(0))
    claims = obj.get("claims", [])
    return [str(c["text"]).strip() for c in claims if isinstance(c, dict) and c.get("text")]


def _read_ledger(path):
    if not os.path.exists(path):
        return set()
    try:
        led = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return set()
    if led.empty or "status" not in led.columns:
        return set()
    ok = {"success_empty", "success_nonempty"}
    return set(led[led["status"].isin(ok)]["paper_id"].unique())


def _append(path, rows):
    if not rows:
        return
    header = (not os.path.exists(path)) or os.path.getsize(path) == 0
    pd.DataFrame(rows).to_csv(path, mode="a", header=header, index=False)


def extract_source(source_id, *, provider="auto", model="gpt-oss", reasoning_effort="high",
                   workers=48, per_year=None, max_new=None, domain=prompts.DEFAULT_DOMAIN,
                   temperature=0.0, max_tokens=8000, checkpoint_every=40, seed=None):
    """Extract claims for a source folder. Returns (n_papers, n_claims)."""
    seed = config.BALANCE_RANDOM_SEED if seed is None else seed
    src = config.CLAIMS_SOURCES_DIR / source_id
    papers = pd.read_csv(src / "papers.csv")
    papers["year"] = pd.to_numeric(papers["year"], errors="coerce").astype("Int64")

    claims_path = str(src / "claims.csv")
    ledger_path = str(src / "processed_papers.csv")
    errors_path = str(src / "extraction_errors.csv")

    done = _read_ledger(ledger_path)
    pending = papers[~papers["paper_id"].isin(done)].copy()

    # Per-year sampling (comparable to the EMNLP balanced corpus).
    if per_year is not None:
        chunks = []
        for y, grp in pending.groupby("year"):
            chunks.append(grp.sample(n=min(len(grp), int(per_year)), random_state=seed))
        pending = pd.concat(chunks, ignore_index=True) if chunks else pending.iloc[0:0]
    if max_new is not None and len(pending) > max_new:
        pending = pending.sample(n=max_new, random_state=seed).reset_index(drop=True)
    if pending.empty:
        print(f"[{source_id}] nothing to extract (all {len(done)} done).")
        return 0, 0

    provider = llm.resolve_provider(provider)   # concrete name for the format branch below
    client = llm.get_client(provider)
    model = llm.resolve_model(client, model)
    user_template = prompts.extractor_prompt(domain)
    prompt_hash = hashlib.sha256(user_template.encode("utf-8")).hexdigest()[:12]
    run_id = f"extract_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    now = datetime.now(timezone.utc).isoformat()
    print(f"[{source_id}] {len(pending)} papers · {provider}:{model} "
          f"effort={reasoning_effort} workers={workers}")

    # vLLM-style backends honour strict json_schema; OpenRouter is safest with json_object.
    response_format = ({"type": "json_schema",
                        "json_schema": {"name": "acc", "schema": CLAIM_SCHEMA, "strict": True}}
                       if provider == "custom" else {"type": "json_object"})

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=30))
    def _call(title, abstract):
        user = user_template.replace("<<TITLE>>", str(title)).replace("<<ABSTRACT>>", str(abstract))
        kwargs = dict(
            model=model, temperature=temperature, max_tokens=max_tokens,
            response_format=response_format,
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": user}])
        if reasoning_effort and llm.supports_reasoning_effort(model):
            kwargs["reasoning_effort"] = reasoning_effort
        r = client.chat.completions.create(**kwargs)
        return _parse(r.choices[0].message.content)

    def work(row):
        try:
            if pd.isna(row["abstract"]) or not str(row["abstract"]).strip():
                return row, [], None
            return row, _call(row["title"], row["abstract"]), None
        except Exception as exc:
            return row, None, exc

    lock = threading.Lock()
    claims_buf, ledger_buf, err_buf = [], [], []
    n_done = n_claims = n_err = 0

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(work, row) for _, row in pending.iterrows()]
        for fut in as_completed(futures):
            row, texts, exc = fut.result()
            pid, year, title = row["paper_id"], int(row["year"]), row["title"]
            if exc is not None:
                ledger_buf.append(dict(paper_id=pid, year=year, status="api_error", n_claims=0,
                                       run_id=run_id, provider=provider, model_name=model,
                                       prompt_hash=prompt_hash, created_at=now))
                err_buf.append(dict(paper_id=pid, year=year, title=title,
                                    error_type=type(exc).__name__, error=repr(exc)[:500],
                                    run_id=run_id, created_at=now))
                n_err += 1
            else:
                status = "success_nonempty" if texts else "success_empty"
                ledger_buf.append(dict(paper_id=pid, year=year, status=status, n_claims=len(texts),
                                       run_id=run_id, provider=provider, model_name=model,
                                       prompt_hash=prompt_hash, created_at=now))
                for i, t in enumerate(texts):
                    claims_buf.append(dict(
                        claim_id=make_claim_id(pid, t, prompt_hash, model), paper_id=pid, year=year,
                        atomic_claim=t, claim_index=i, extractor_model=model,
                        prompt_hash=prompt_hash, run_id=run_id, created_at=now))
                    n_claims += 1
            n_done += 1
            if n_done % checkpoint_every == 0:
                with lock:
                    _append(claims_path, claims_buf); _append(ledger_path, ledger_buf); _append(errors_path, err_buf)
                    claims_buf.clear(); ledger_buf.clear(); err_buf.clear()
                print(f"[{source_id}] {n_done}/{len(pending)} · {n_claims} claims · {n_err} errors", flush=True)

    _append(claims_path, claims_buf); _append(ledger_path, ledger_buf); _append(errors_path, err_buf)

    # de-dup claims by claim_id (stable across re-runs)
    cdf = pd.read_csv(claims_path)
    cdf = cdf.drop_duplicates(subset="claim_id", keep="last")
    cdf.to_csv(claims_path, index=False)

    # refresh the source meta with extractor + counts
    meta_path = src / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {"id": source_id}
    meta["extractor"] = {"provider": provider, "model": model, "reasoning_effort": reasoning_effort,
                         "prompt_hash": prompt_hash, "domain": domain}
    meta["n_claims"] = int(len(cdf))
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[{source_id}] DONE: {n_done} papers, {len(cdf)} total claims, {n_err} errors")
    return n_done, int(len(cdf))
