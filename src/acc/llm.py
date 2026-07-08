"""
OpenAI-compatible LLM providers.

Two backends: ``custom`` (any OpenAI-compatible endpoint — e.g. a self-hosted
vLLM cluster; set ``CUSTOM_BASE_URL`` + ``CUSTOM_API_KEY``) and ``openrouter``
(the original EMNLP extraction backend and the documented public path).
Self-hosted model lineups can change between runs, so models are resolved
against a live ``models.list()`` at call time and we fail loudly if a target
is missing.

Keys are read from ``<repo>/.env`` (no python-dotenv dependency).
"""
import os

from . import config

PROVIDERS = {
    # base_url_env: the endpoint comes from the environment / .env, so no
    # private URL ships in the source. base_url: a fixed public endpoint.
    "custom": {"base_url_env": "CUSTOM_BASE_URL", "key_env": "CUSTOM_API_KEY"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY"},
}


def _base_url(cfg):
    return cfg.get("base_url") or os.environ.get(cfg.get("base_url_env", ""))


def load_env():
    """Load <repo>/.env (KEY=VALUE) into os.environ, overriding stale shell vars.

    .env is the source of truth for API keys in this repo — a stale key left
    in the parent shell must not shadow a freshly rotated one in .env, so we
    assign rather than setdefault.
    """
    p = config.ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ[k.strip()] = v.strip().strip('"').strip("'")


def resolve_provider(provider="auto"):
    """Map "auto" to the first provider whose API key is configured (.env or env)."""
    if provider != "auto":
        return provider
    load_env()
    for name, cfg in PROVIDERS.items():
        if os.environ.get(cfg["key_env"]) and _base_url(cfg):
            print(f"provider: {name} (auto-selected via {cfg['key_env']})")
            return name
    raise RuntimeError(
        "no LLM API key configured — set OPENROUTER_API_KEY (or CUSTOM_API_KEY + "
        "CUSTOM_BASE_URL) in <repo>/.env")


def get_client(provider="auto", timeout=120, max_retries=3):
    from openai import OpenAI
    load_env()
    provider = resolve_provider(provider)
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}; choose from {list(PROVIDERS)}")
    cfg = PROVIDERS[provider]
    key = os.environ.get(cfg["key_env"])
    if not key:
        raise RuntimeError(f"{cfg['key_env']} not set (add it to .env or the environment)")
    base_url = _base_url(cfg)
    if not base_url:
        raise RuntimeError(f"{cfg['base_url_env']} not set (add it to .env or the environment)")
    return OpenAI(base_url=base_url, api_key=key, timeout=timeout, max_retries=max_retries)


def list_models(client):
    return [m.id for m in client.models.list().data]


def resolve_model(client, wanted):
    """Resolve `wanted` to a live model id (exact, else unique substring match)."""
    models = list_models(client)
    for m in models:
        if m.lower() == wanted.lower():
            return m
    hits = [m for m in models if wanted.lower() in m.lower()]
    if not hits:
        raise RuntimeError(f"model {wanted!r} not in lineup: {sorted(models)}")
    return hits[0]


def supports_reasoning_effort(model: str) -> bool:
    """gpt-oss is the only model here that takes an explicit reasoning_effort."""
    return "gpt-oss" in model.lower()
