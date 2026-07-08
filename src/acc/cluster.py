"""
Reproducible cluster naming.

Two layers (see paper §method and ``CLUSTER_LABEL_REVIEW.md``):

  * **Automatic c-TF-IDF descriptors** — ``compute_descriptors()`` returns a
    short (top-3) and a full (top-5) keyword descriptor per cluster. This is the
    reproducible layer: it is a class-based TF-IDF (each cluster = one document)
    over the claim-level vocabulary, with hapax suppression, hyphen-aware
    tokenisation, and a lemmatising de-duplicator so morphological variants
    (``dialogue/dialog/dialogues``) and bigram constituents (drop ``translation``
    once ``machine translation`` is chosen) collapse, while distinct compounds
    (``few-shot`` vs ``zero-shot``) are preserved.

  * **Curated manual labels** — ``config.READABLE_LABELS`` maps cluster id ->
    ``(short, full)`` human-readable names (short <= 24 chars for maps/figures/
    tables; full for body text). ``short_label`` / ``full_label`` resolve the
    manual name, falling back to the automatic descriptor when none exists, so
    the demo never breaks on an unlabelled cluster.

This module NEVER clusters. It reads existing cluster assignments only, so
regenerating names cannot change cluster membership.
"""
import numpy as np
from nltk.stem.snowball import SnowballStemmer
from sklearn.feature_extraction import text
from sklearn.feature_extraction.text import CountVectorizer

from . import config

# --- vocabulary / weighting recipe (the agreed "D+F" configuration) ----------
# Generic ML / paper-boilerplate words to drop on top of the sklearn English
# stoplist. "language" is intentionally kept here (a corpus-generic word in an
# NLP venue); see the project naming decision (phrase_boost off, language out).
_GENERIC = [
    'method', 'methods', 'model', 'models', 'approach', 'approaches', 'paper',
    'papers', 'propose', 'proposed', 'proposes', 'dataset', 'datasets', 'task',
    'tasks', 'result', 'results', 'performance', 'state', 'art', 'based',
    'using', 'use', 'uses', 'used', 'problem', 'problems', 'work', 'works',
    'study', 'studies', 'novel', 'new', 'phenomenon', 'show', 'shows', 'shown',
    'achieve', 'achieves', 'improve', 'improves', 'improved', 'improvement',
    'language', 'data', 'training', 'train', 'large', 'high', 'low',
    'existing', 'various', 'different',
]
STOPWORDS = sorted(text.ENGLISH_STOP_WORDS.union(_GENERIC))

# keep internal hyphens as one token: 'fine-tuning' -> 'fine-tuning'
TOKEN_PATTERN = r'(?u)\b\w[\w-]+\b'

NGRAM_RANGE = (1, 2)
MIN_DF = 10          # term must occur in >= 10 claims (kills hapax artifacts)
MAX_DF = 0.5         # drop terms in > 50% of claims (ultra-generic)
COVERAGE = 0.05      # term must appear in >= 5% of a cluster's claims
STEM_CAP = 2         # a stem may appear in at most this many terms of one name
SHORT_K = 3          # terms in the short (display) descriptor
FULL_K = 5           # terms in the full (detail) descriptor
PHRASE_BOOST = 0.0   # multiword score boost (0 = off, project decision)

# Canonicalise a few stems that are spelling/variant pairs the stemmer misses,
# so the families collapse in the de-duplicator.
_STEM_CANON = {'dialog': 'dialogu', 'summari': 'summar', 'lingual': 'multiling'}
_stem = SnowballStemmer('english').stem


def _kset(term):
    """Stemmed token set of a term; splits on spaces AND hyphens."""
    parts = term.replace('-', ' ').split()
    return frozenset(_STEM_CANON.get(_stem(w), _stem(w)) for w in parts)


def _dedup(cands, k):
    """Pick k terms, dropping containment-redundant ones and capping stem reuse.

    A term is redundant if its stem-set is a subset/superset of an already
    chosen term's (collapses morphology + bigram constituents); additionally a
    stem may be reused in at most ``STEM_CAP`` terms (prevents one word echoing
    across the whole name). Distinct compounds (few-shot vs zero-shot share only
    'shot', neither a subset) survive.
    """
    sel, use = [], {}
    for t in cands:
        ks = _kset(t)
        if any(ks <= sk or sk <= ks for _, sk in sel):
            continue
        if any(use.get(s, 0) >= STEM_CAP for s in ks):
            continue
        sel.append((t, ks))
        for s in ks:
            use[s] = use.get(s, 0) + 1
        if len(sel) == k:
            break
    return ', '.join(s for s, _ in sel)


def compute_descriptors(df):
    """Map cluster id -> ``(short, full)`` c-TF-IDF descriptor.

    ``df`` is the canonical corpus (needs ``atomic_claim`` and ``cluster``).
    Noise (cluster ``-1``) is ignored. Deterministic for a fixed corpus.
    """
    nn = df[df['cluster'] != -1]
    texts = nn['atomic_claim'].astype(str).to_numpy()
    cl = nn['cluster'].to_numpy()
    clusters = sorted(int(c) for c in set(cl))

    cv = CountVectorizer(stop_words=STOPWORDS, ngram_range=NGRAM_RANGE,
                         min_df=MIN_DF, max_df=MAX_DF, token_pattern=TOKEN_PATTERN)
    X = cv.fit_transform(texts)
    vocab = np.asarray(cv.get_feature_names_out())
    Xb = (X > 0).astype(np.int32)

    f_t = np.asarray(X.sum(0)).ravel() + 1.0                 # global term freq
    avg_len = X.sum() / max(len(clusters), 1)                # mean class length
    cidf = np.log(1 + avg_len / f_t)                         # class-based IDF
    nwords = np.array([t.count(' ') + 1 for t in vocab])
    pweight = 1.0 + PHRASE_BOOST * (nwords - 1)

    out = {}
    for c in clusters:
        m = cl == c
        n = int(m.sum())
        tf = np.asarray(X[m].sum(0)).ravel().astype(float)
        cov = np.asarray(Xb[m].sum(0)).ravel() / n
        score = (tf / max(tf.sum(), 1.0)) * cidf * pweight
        score = np.where(cov >= COVERAGE, score, 0.0)
        order = [j for j in np.argsort(score)[::-1] if score[j] > 0][:25]
        cands = [vocab[j] for j in order]
        out[c] = (_dedup(cands, SHORT_K), _dedup(cands, FULL_K))
    return out


# --- name resolution (LLM names first, c-TF-IDF descriptor fallback) ----------
_NAMES_CACHE = None


def load_cluster_names(refresh=False):
    """{cluster_id: {short, full}} from ``acc name`` (cluster_names.json), or {}."""
    global _NAMES_CACHE
    if _NAMES_CACHE is None or refresh:
        import json
        if config.CLUSTER_NAMES.exists():
            raw = json.load(open(config.CLUSTER_NAMES, encoding="utf-8"))
            _NAMES_CACHE = {int(k): v for k, v in raw.items()}
        else:
            _NAMES_CACHE = {}
    return _NAMES_CACHE


def short_label(cid, fallback):
    """LLM short name for a cluster, or ``fallback`` (its c-TF-IDF short)."""
    n = load_cluster_names().get(int(cid))
    return n["short"] if n and n.get("short") else fallback


def full_label(cid, fallback):
    """LLM full name for a cluster, or ``fallback`` (its c-TF-IDF full)."""
    n = load_cluster_names().get(int(cid))
    return n["full"] if n and n.get("full") else fallback


def regenerate_canonical_names(write=True, verbose=True):
    """Rewrite ONLY ``cluster_name`` in ``acc_clusters.csv`` = short descriptor.

    Reads the frozen cluster assignments, recomputes the short c-TF-IDF
    descriptor per cluster, and rewrites only that column. ``claim_id`` /
    ``paper_id`` / ``year`` / ``cluster`` are asserted byte-identical, so cluster
    membership cannot change — only the names do. Noise keeps the name 'noise'.
    Returns the new dataframe (written iff ``write``).
    """
    import pandas as pd
    from .corpus import load_canonical_corpus

    old = pd.read_csv(config.ACC_CLUSTERS)
    df = load_canonical_corpus()                 # balanced corpus aligned to old
    desc = compute_descriptors(df)

    new = old.copy()
    new['cluster_name'] = ['noise' if int(c) == -1 else desc[int(c)][0]
                           for c in old['cluster']]
    for col in ('claim_id', 'paper_id', 'year', 'cluster'):
        if not (new[col].values == old[col].values).all():
            raise RuntimeError(f'invariant broken: {col} changed — refusing to write')

    if verbose:
        changed = int((new['cluster_name'].values != old['cluster_name'].values).sum())
        print(f'cluster_name updated for {changed}/{len(new)} rows; membership '
              f'unchanged ({new["cluster"].nunique() - 1} clusters + noise)')
    if write:
        new.to_csv(config.ACC_CLUSTERS, index=False)
        if verbose:
            print(f'wrote {config.ACC_CLUSTERS}')
    return new
