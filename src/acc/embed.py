"""
Claim embeddings, with a pluggable encoder seam.

The canonical encoder is SPECTER2 (claim text only, CLS pooling) — its vectors
keep their historical cache filename and reproduce the published Drift Inspector.
The encoder is a registry so the decisive embedding-model ablation
(REPORT_DRIFT_SPECTER2 §9, E1) is a matter of registering another encoder and
calling ``embed_claims(texts, encoder="e5-large-v2")``; each encoder gets its own
cache, so runs never collide. Heavy ML deps are imported lazily inside the
encoder, so importing ``acc`` stays cheap and only a real cache-miss pulls them.
"""
import numpy as np

from . import config

#: name -> callable(list[str]) -> np.ndarray. Register alternatives here for E1.
_ENCODERS = {}


def register_encoder(name):
    """Decorator: register an encoder function under ``name``."""
    def deco(fn):
        _ENCODERS[name] = fn
        return fn
    return deco


@register_encoder("specter2")
def _encode_specter2(texts):
    """Canonical encoder: SPECTER2 proximity adapter, CLS pooling (768-d)."""
    import torch
    from transformers import AutoTokenizer
    from adapters import AutoAdapterModel

    print(f"Loading SPECTER2: {config.SPECTER2_MODEL}")
    tok = AutoTokenizer.from_pretrained(config.SPECTER2_MODEL)
    model = AutoAdapterModel.from_pretrained(config.SPECTER2_MODEL)
    model.load_adapter(config.SPECTER2_ADAPTER, source="hf",
                       load_as="specter2", set_active=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    model.eval()

    out = []
    bs = config.EMBED_BATCH
    n = len(texts)
    with torch.no_grad():
        for i in range(0, n, bs):
            batch = texts[i:i + bs]
            enc = tok(batch, padding=True, truncation=True,
                      return_tensors="pt", return_token_type_ids=False,
                      max_length=config.EMBED_MAX_LENGTH).to(device)
            out.append(model(**enc).last_hidden_state[:, 0, :].cpu().numpy())
            if (i // bs) % 50 == 0:
                print(f"  embedded {i}/{n}", flush=True)
    return np.vstack(out)


def embed_claims(texts, encoder=None, cache=None) -> np.ndarray:
    """Return embeddings for ``texts``, using the per-encoder cache when valid.

    encoder : name of a registered encoder (default config.DEFAULT_ENCODER).
    cache   : override the cache path (defaults to config.embeddings_cache).
    """
    texts = list(texts)
    encoder = encoder or config.DEFAULT_ENCODER
    if encoder not in _ENCODERS:
        raise KeyError(f"unknown encoder {encoder!r}; registered: {sorted(_ENCODERS)}")
    cache = cache if cache is not None else config.embeddings_cache(encoder)

    if cache.exists():
        E = np.load(cache)
        if len(E) == len(texts):
            print(f"Using cached embeddings: {cache} {E.shape}")
            return E
        print("Cached embeddings have wrong length; recomputing.")

    E = _ENCODERS[encoder](texts)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache, E)
    print(f"Saved embeddings: {cache} {E.shape}")
    return E
