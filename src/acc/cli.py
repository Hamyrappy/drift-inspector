"""
`acc` command-line interface.

Drives the deterministic, locally-reproducible steps of the pipeline. The
interactive steps (corpus download, LLM extraction) stay in notebooks. Run
`acc status` to see what's built, `acc all` to rebuild the demo from the
canonical clustering, or `acc ui` for the dashboard.
"""
import argparse
import functools
import http.server
import socketserver

from . import config


def cmd_status(args):
    from .status import pipeline_status
    glyph = {"fresh": "✓", "stale": "⚠", "missing": "✗"}
    print(f"\n  Drift Inspector pipeline  (acc v{config.SCHEMA_VERSION})\n")
    for r in pipeline_status():
        size = f"{r['size']/1e6:.1f} MB" if r["size"] else "—"
        print(f"  {glyph[r['state']]:<2} {r['label']:<24} {r['state']:<8} "
              f"{size:>10}   ({r['how']})")
    print()


def cmd_embed(args):
    from .corpus import load_canonical_corpus
    from .embed import embed_claims
    df = load_canonical_corpus()
    embed_claims(df["atomic_claim"].astype(str).tolist())


def cmd_project(args):
    from .corpus import load_canonical_corpus
    from .embed import embed_claims
    from .project import umap_2d
    df = load_canonical_corpus()
    E = embed_claims(df["atomic_claim"].astype(str).tolist())
    umap_2d(E)


def cmd_names(args):
    from .cluster import regenerate_canonical_names
    regenerate_canonical_names(write=not args.dry_run)


def _parse_years(spec):
    spec = str(spec)
    if ":" in spec or "-" in spec:
        sep = ":" if ":" in spec else "-"
        a, b = spec.split(sep)
        return list(range(int(a), int(b) + 1))
    return [int(y) for y in spec.split(",") if y.strip()]


def cmd_download(args):
    from .download import download_source
    download_source(args.venue, _parse_years(args.years),
                    source_id=args.id, name=args.name, color=args.color,
                    collection=args.collection, append=args.append,
                    register=not args.no_register)


def cmd_extract(args):
    from .extract import extract_source
    extract_source(args.source, provider=args.provider, model=args.model,
                   reasoning_effort=args.effort, workers=args.workers,
                   per_year=args.per_year, max_new=args.max_new, domain=args.domain)


def cmd_assign(args):
    from .assign import assign_source
    assign_source(args.source)


def cmd_judge(args):
    from .judge import judge_source, judge_validation
    kw = dict(provider=args.provider, model=args.model, reasoning_effort=args.effort,
              workers=args.workers, domain=args.domain)
    if args.validation:
        judge_validation(sample_n=args.sample, **kw)
    else:
        judge_source(args.source, sample_n=args.sample, **kw)


def cmd_filter(args):
    from .judge import filter_source
    filter_source(args.source, sample_n=args.sample, drop=tuple(args.drop),
                  write=not args.no_write, provider=args.provider, model=args.model,
                  reasoning_effort=args.effort, workers=args.workers, domain=args.domain)


def cmd_authors(args):
    from .authors import backfill_authors
    backfill_authors(source_ids=args.source)


def cmd_cluster(args):
    from .clustering import run_clustering
    run_clustering(reassemble=args.reassemble)


def cmd_name(args):
    from .naming import name_clusters
    name_clusters(provider=args.provider, model=args.model, effort=args.effort,
                  workers=args.workers, domain=args.domain)


def cmd_build_inspector(args):
    from .inspector import build_data
    build_data()


def cmd_bake(args):
    from .inspector import bake
    bake()


def cmd_figures(args):
    from .figures import build_butterfly, build_trajectories
    build_butterfly()
    build_trajectories()


def cmd_robustness(args):
    from .robustness import run
    run()


def cmd_serve(args):
    directory = str(config.INSPECTOR)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    with socketserver.TCPServer(("", args.port), handler) as httpd:
        print(f"Serving {directory}\n  ->  http://localhost:{args.port}/   (Ctrl-C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")


def cmd_all(args):
    cmd_embed(args)
    cmd_project(args)
    cmd_build_inspector(args)
    cmd_bake(args)


def cmd_export_public(args):
    from .export import export_public
    export_public(args.dest)


def cmd_ui(args):
    from .tui import run as run_ui
    run_ui()


def main(argv=None):
    p = argparse.ArgumentParser(prog="acc",
                                description="ACC / Drift Inspector pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="show pipeline stage freshness")
    nm = sub.add_parser("names", help="regenerate cluster_name (c-TF-IDF) in acc_clusters.csv")
    nm.add_argument("--dry-run", action="store_true", help="compute but don't write")
    dl = sub.add_parser("download", help="download a venue's main-track papers from the ACL Anthology")
    dl.add_argument("--venue", required=True, help="anthology venue id, e.g. acl / coling / emnlp")
    dl.add_argument("--years", required=True, help="2020:2025 or 2020,2022,2025")
    dl.add_argument("--id", default=None, help="source id (default: venue)")
    dl.add_argument("--name", default=None)
    dl.add_argument("--color", default="#2ca02c")
    dl.add_argument("--collection", default=None, help="override collection id, e.g. 2024.lrec-main (COLING 2024 = LREC-COLING)")
    dl.add_argument("--append", action="store_true", help="merge into an existing source's papers.csv")
    dl.add_argument("--no-register", action="store_true", dest="no_register",
                    help="write the source folder but don't add it to the manifest (stage a corpus without showing it in the inspector)")

    ex = sub.add_parser("extract", help="extract atomic claims for a source (LLM)")
    ex.add_argument("--source", required=True, help="source id (a data/claims_sources/<id> folder)")
    ex.add_argument("--provider", default="auto", choices=["auto", "custom", "openrouter"])
    ex.add_argument("--model", default="gpt-oss", help="model id or substring (resolved at runtime)")
    ex.add_argument("--effort", default="high", choices=["low", "medium", "high"])
    ex.add_argument("--workers", type=int, default=48)
    ex.add_argument("--per-year", type=int, default=None, dest="per_year", help="cap papers/year")
    ex.add_argument("--max-new", type=int, default=None, dest="max_new")
    ex.add_argument("--domain", default="NLP")

    asg = sub.add_parser("assign", help="assign an overlaid source's claims to existing clusters (nearest centroid)")
    asg.add_argument("--source", required=True)

    jd = sub.add_parser("judge", help="LLM-as-judge: grade extraction quality / human agreement")
    jd.add_argument("--source", default=None, help="source id to grade (omit with --validation)")
    jd.add_argument("--validation", action="store_true", help="grade the human-validation set + report agreement")
    jd.add_argument("--provider", default="auto", choices=["auto", "custom", "openrouter"])
    jd.add_argument("--model", default="gpt-oss")
    jd.add_argument("--effort", default="high", choices=["low", "medium", "high"])
    jd.add_argument("--sample", type=int, default=120)
    jd.add_argument("--workers", type=int, default=24)
    jd.add_argument("--domain", default="NLP")

    fl = sub.add_parser("filter", help="judge a source's claims and drop bad ones -> claims_filtered.csv (unused until manifest points at it)")
    fl.add_argument("--source", required=True)
    fl.add_argument("--sample", type=int, default=None, help="judge only N random claims (test); omit for all")
    fl.add_argument("--drop", nargs="+", default=["BAD"], help="labels to drop (default: BAD)")
    fl.add_argument("--no-write", action="store_true", help="report only, don't write claims_filtered.csv")
    fl.add_argument("--provider", default="auto", choices=["auto", "custom", "openrouter"])
    fl.add_argument("--model", default="gpt-oss")
    fl.add_argument("--effort", default="high", choices=["low", "medium", "high"])
    fl.add_argument("--workers", type=int, default=24)
    fl.add_argument("--domain", default="NLP")

    au = sub.add_parser("authors", help="backfill authors/venue into papers.csv from the ACL Anthology")
    au.add_argument("--source", nargs="*", default=None, help="source ids (default: all)")
    sub.add_parser("embed", help="SPECTER2 claim embeddings (cached)")
    cl = sub.add_parser("cluster", help="jointly cluster all display venues (UMAP-5D + HDBSCAN)")
    cl.add_argument("--reassemble", action="store_true", help="rebuild corpus+UMAP from scratch (ignore caches)")
    nm2 = sub.add_parser("name", help="LLM cluster names -> data/clusters/cluster_names.json")
    nm2.add_argument("--provider", default="auto")
    nm2.add_argument("--model", default="gpt-oss")
    nm2.add_argument("--effort", default="high")
    nm2.add_argument("--workers", type=int, default=16)
    nm2.add_argument("--domain", default="NLP")
    sub.add_parser("project", help="2D UMAP projection (cached)")
    sub.add_parser("build-inspector", help="compute inspector/data/acc_data.json")
    sub.add_parser("bake", help="bake the portable single-file HTML")
    sub.add_parser("figures", help="regenerate paper figures (butterfly + trajectories)")
    sub.add_parser("robustness", help="run the hyperparameter robustness grid")
    sv = sub.add_parser("serve", help="serve the inspector/ site locally")
    sv.add_argument("--port", type=int, default=8000)
    sub.add_parser("all", help="embed -> project -> build-inspector -> bake")
    sub.add_parser("ui", help="launch the interactive pipeline dashboard")
    ep = sub.add_parser("export-public", help="copy the public demo subset to a folder")
    ep.add_argument("--dest", default=None,
                    help="destination dir (default: ../drift-inspector-public)")

    args = p.parse_args(argv)
    dispatch = {
        "status": cmd_status, "names": cmd_names, "authors": cmd_authors,
        "download": cmd_download, "extract": cmd_extract,
        "assign": cmd_assign, "judge": cmd_judge,
        "embed": cmd_embed, "project": cmd_project,
        "cluster": cmd_cluster, "name": cmd_name, "filter": cmd_filter,
        "build-inspector": cmd_build_inspector, "bake": cmd_bake,
        "figures": cmd_figures, "robustness": cmd_robustness,
        "serve": cmd_serve, "all": cmd_all, "ui": cmd_ui,
        "export-public": cmd_export_public,
    }
    dispatch[args.cmd](args)


if __name__ == "__main__":
    main()
