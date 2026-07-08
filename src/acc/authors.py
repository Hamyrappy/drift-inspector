"""
Author / venue backfill from the ACL Anthology.

Authors were not captured at download time historically (notebook 01 kept only
title/abstract/url). This backfills ``authors`` (display names), ``author_ids``
(disambiguated Anthology person ids, e.g. ``yohan-jo``) and ``n_authors`` into
each source's ``papers.csv``, joining on the canonical ``paper_id`` (= Anthology
``full_id``). Offline, via the ``acl-anthology`` library against its cached repo.

Disambiguated ids matter: a per-author subsample keyed on raw name strings would
merge distinct ``J. Smith``s; the Anthology person id is the stable identity.
"""
import re
import warnings

import pandas as pd

from . import config
from . import corpus


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "unknown"


def _paper_authors(anth, paper_id):
    """(display_names, person_ids) for a paper, or None if unavailable."""
    try:
        paper = anth.get(paper_id)
    except Exception:
        return None
    if paper is None or not getattr(paper, "authors", None):
        return None
    names, ids = [], []
    for ns in paper.authors:
        nm = ns.name.as_full() if ns.name else ""
        names.append(nm)
        ids.append(ns.id or _slug(nm))   # fall back to a name slug if undisambiguated
    return names, ids


def backfill_authors(source_ids=None):
    """Fill authors/author_ids/n_authors in each source's papers.csv in place."""
    from acl_anthology import Anthology
    warnings.filterwarnings("ignore")           # SchemaMismatchWarning is benign
    print("Loading ACL Anthology (cached repo)...")
    anth = Anthology.from_repo()

    manifest = corpus.load_manifest()
    sources = manifest["sources"]
    if source_ids:
        sources = [s for s in sources if s["id"] in source_ids]

    for s in sources:
        ppath = corpus._resolve(s["paths"]["papers"])
        papers = pd.read_csv(ppath)
        names_col, ids_col, n_col, miss = [], [], [], 0
        for pid in papers["paper_id"]:
            res = _paper_authors(anth, pid)
            if res is None:
                miss += 1
                names_col.append(""); ids_col.append(""); n_col.append(0)
            else:
                names, ids = res
                names_col.append("; ".join(names))
                ids_col.append("; ".join(ids))
                n_col.append(len(ids))
        papers["authors"] = names_col
        papers["author_ids"] = ids_col
        papers["n_authors"] = n_col
        papers.to_csv(ppath, index=False)
        n_with = int((papers["n_authors"] > 0).sum())
        print(f"[{s['id']}] {len(papers)} papers, {n_with} with authors, "
              f"{miss} without -> {ppath}")
