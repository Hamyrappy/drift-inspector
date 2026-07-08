"""
Corpus download from the ACL Anthology.

Generalises the old EMNLP-only notebook to any venue. For each year it pulls the
main-conference volumes (skipping findings / workshops / demos / tutorials / SRW
/ industry), keeping papers that have a title + abstract, and captures authors
(disambiguated ids) and venue/track at download time. Writes a source folder
``data/claims_sources/<id>/papers.csv`` + ``meta.json`` and registers it in the
manifest as a display+compare source.
"""
import json
import re

import pandas as pd

from . import config
from . import corpus

# Volume ids that are NOT the main conference track. Besides the usual
# findings/demos/SRW/tutorials/industry, several venues ship co-located
# workshops as sibling volumes of the same collection — e.g. RANLP's student
# session ("stud") and its co-located workshops ("ahasis", "mdaigt"); these are
# not the main proceedings and must be excluded.
NON_MAIN_VOLUMES = {
    "findings", "demos", "demo", "srw", "tutorials", "tutorial", "industry",
    "workshop", "workshops", "students", "student", "stud", "wat", "challenge",
    "ahasis", "mdaigt",
}


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "unknown"


def _paper_row(paper, year, venue, track):
    names, ids = [], []
    for ns in (paper.authors or []):
        nm = ns.name.as_full() if ns.name else ""
        names.append(nm)
        ids.append(ns.id or _slug(nm))
    return {
        "paper_id": paper.full_id,
        "year": int(year),
        "title": paper.title.as_text(),
        "venue": venue.upper(),
        "track": track,
        "url": f"https://aclanthology.org/{paper.full_id}/",
        "authors": "; ".join(names),
        "author_ids": "; ".join(ids),
        "n_authors": len(ids),
        "abstract": paper.abstract.as_text(),
    }


def download_source(venue, years, source_id=None, name=None, color="#2ca02c",
                    collection=None, append=False, register=True):
    """Download main-track papers for `venue` across `years` into a source folder.

    ``collection`` overrides the default ``{year}.{venue}`` collection id (e.g.
    ``2024.lrec-main`` for COLING 2024, which was the joint LREC-COLING); with a
    single ``years`` entry those papers are tagged with that year and venue.
    ``append`` merges into an existing ``papers.csv`` (dedup on paper_id) instead
    of overwriting — for adding a year to a source that already exists.
    ``register=False`` writes the source folder (papers.csv + meta.json) but does
    NOT add it to the manifest — for staging a corpus (e.g. a full-main-track
    re-extraction) that should be saved without appearing in the live inspector.
    """
    import warnings
    from acl_anthology import Anthology
    warnings.filterwarnings("ignore")

    source_id = source_id or venue.lower()
    print(f"Loading ACL Anthology (cached) for {venue} {years}"
          f"{f' [{collection}]' if collection else ''}...")
    anth = Anthology.from_repo()

    rows = []
    for year in years:
        coll_id = collection or f"{year}.{venue.lower()}"
        try:
            coll = anth.get_collection(coll_id)
        except Exception:
            coll = None
        if coll is None:
            print(f"  {coll_id}: no collection")
            continue
        n_year = 0
        for vol in coll.volumes():
            if str(vol.id).lower() in NON_MAIN_VOLUMES:
                continue
            for paper in vol.papers():
                try:
                    if paper.is_frontmatter or not paper.title or not paper.abstract:
                        continue
                    rows.append(_paper_row(paper, year, venue, str(vol.id)))
                    n_year += 1
                except Exception:
                    continue
        print(f"  {year}.{venue}: {n_year} papers")

    if not rows:
        raise RuntimeError(f"no papers found for {venue} {years}")
    papers = pd.DataFrame(rows)

    src_dir = config.CLAIMS_SOURCES_DIR / source_id
    src_dir.mkdir(parents=True, exist_ok=True)
    if append and (src_dir / "papers.csv").exists():
        prev = pd.read_csv(src_dir / "papers.csv")
        papers = pd.concat([prev, papers], ignore_index=True)
        print(f"  appending to {len(prev)} existing papers")
    papers = papers.drop_duplicates(subset="paper_id").reset_index(drop=True)
    papers.to_csv(src_dir / "papers.csv", index=False)

    yrs = sorted(int(y) for y in papers["year"].unique())
    meta = {
        "id": source_id, "name": name or f"{venue.upper()} main {yrs[0]}-{yrs[-1]}",
        "venue": venue.upper(), "source": "ACL Anthology",
        "years": yrs, "n_papers": int(len(papers)),
        "papers_per_year": {str(y): int((papers["year"] == y).sum()) for y in yrs},
    }
    (src_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    if register:
        corpus.register_source({
            "id": source_id, "name": meta["name"], "venue": venue.upper(),
            "roles": ["display", "compare"], "color": color,
            "paths": {"claims": f"{source_id}/claims.csv",
                      "papers": f"{source_id}/papers.csv",
                      "clusters": f"{source_id}/clusters.csv"},
        })
    reg = f"registered '{source_id}'" if register else f"'{source_id}' (unregistered)"
    print(f"Wrote {len(papers)} papers -> {src_dir/'papers.csv'} ({reg})")
    return papers
