"""
Central configuration for the ACC / Drift Inspector pipeline.

Single source of truth for paths, seeds, hyperparameters, and the curated
cluster constants. Everything else in ``acc`` imports from here, so relocating
a directory is a one-file change.
"""
from pathlib import Path

# --- Schema / product version -------------------------------------------------
# The Drift Inspector data schema. The UI design has iterated (v3 monolith ->
# modular redesign), but acc_data.json's shape has been stable; bump this only
# when the JSON schema actually changes.
SCHEMA_VERSION = "1.0"

# --- Roots --------------------------------------------------------------------
# config.py lives at <repo>/src/acc/config.py -> parents[2] == <repo root>.
ROOT = Path(__file__).resolve().parents[2]

DATA = ROOT / "data"                     # all corpus / claim / cluster data
CLUSTERS_DIR = DATA / "clusters"         # canonical clustering outputs
EXTERNAL_DIR = DATA / "external"         # third-party datasets (SToP taxonomy)
ARTIFACTS = ROOT / "artifacts"           # derived caches, figures, paper outputs
INSPECTOR = ROOT / "inspector"           # demo web app (source of truth)

# --- Claim sources (schema 2.0): one folder + a manifest per growing dataset ---
# Each source is {claims.csv, papers.csv, meta.json}; manifest.json registers
# every source and its roles (clustering / display / compare). New conferences or
# extraction experiments are added as sources without changing the format.
CLAIMS_SOURCES_DIR = DATA / "claims_sources"
MANIFEST = CLAIMS_SOURCES_DIR / "manifest.json"

# --- Canonical data files -----------------------------------------------------
ACC_CLUSTERS = CLUSTERS_DIR / "acc_clusters.csv"    # CANONICAL claim -> cluster
CLUSTER_NAMES = CLUSTERS_DIR / "cluster_names.json"  # LLM cluster names {id:{short,full}}
SENT_CLUSTERS = CLUSTERS_DIR / "sent_clusters.csv"  # sentence-level clustering
STOP_TAXONOMY = EXTERNAL_DIR / "STop_topic_classification_dataset_for_scientific_papers.csv"

# --- Caches (derived; safe to delete and recompute) ---------------------------
# Per-encoder embeddings cache: the canonical SPECTER2 vectors keep their
# historical filename; alternative encoders (future E1 ablation) get their own.
EMB_CACHE = ARTIFACTS / "acc_specter2_embeddings.npy"   # SPECTER2 claim vectors
UMAP2D_CACHE = ARTIFACTS / "acc_umap2d.npy"             # 2D map projection
UMAP5D_CACHE = ARTIFACTS / "acc_umap5d.npy"             # 5D clustering projection


def embeddings_cache(encoder: str = "specter2") -> Path:
    """Cache path for an encoder's claim embeddings (keyed by encoder name)."""
    if encoder == "specter2":
        return EMB_CACHE
    return ARTIFACTS / f"acc_{encoder}_embeddings.npy"

# --- Inspector outputs --------------------------------------------------------
DATA_JSON = INSPECTOR / "data" / "acc_data.json"        # site data payload
PORTABLE_HTML = ROOT / "drift_inspector_v5.html"        # baked single-file build

# --- Robustness / figure cross-check artifacts --------------------------------
ROBUSTNESS_DIR = ARTIFACTS / "robustness"
HEADLINE_TRAJ = ROBUSTNESS_DIR / "headline_significance_trajectories.csv"

# --- Paper study corpus (EMNLP 2020-2025) --------------------------------------
# The 16,576-claim corpus behind every number in the paper. Both files ship in
# the public release, so the robustness grid reproduces from a fresh clone.
STUDY_CLUSTERS = ARTIFACTS / "baseline" / "acc_clusters_emnlp.csv"  # clusters (no text)
STUDY_CLAIMS_TEXT = DATA / "claims" / "openrouter_claims.csv"       # raw extraction (claim text)

# --- Corpus / sampling --------------------------------------------------------
# anthology-mainconf branch: the main *ACL conferences' abstract coverage is
# sparse before 2018 (ACL abstracts start ~2016, and early years have few
# papers), so restrict the corpus + trends axis to 2018-2026.
START_YEAR, END_YEAR = 2018, 2026
YEARS = list(range(START_YEAR, END_YEAR + 1))
TARGET_PAPERS_PER_YEAR = 748
BALANCE_RANDOM_SEED = 42

# --- Embedding (SPECTER2) -----------------------------------------------------
SPECTER2_MODEL = "allenai/specter2_aug2023refresh_base"
SPECTER2_ADAPTER = "allenai/specter2_aug2023refresh"
EMBED_BATCH = 32
EMBED_MAX_LENGTH = 512

# --- UMAP 2D (visualization projection) ---------------------------------------
UMAP_2D = dict(n_neighbors=40, n_components=2, min_dist=0.5,
               metric="cosine", random_state=42)

# --- UMAP 5D + HDBSCAN (clustering projection) --------------------------------
# The canonical clustering recipe used by `acc cluster` (src/acc/clustering.py)
# to produce data/clusters/acc_clusters.csv. Centralised here so an ablation
# re-runs the *identical* clustering on alternative embeddings.
UMAP_5D = dict(n_neighbors=40, n_components=5, min_dist=0.0,
               metric="cosine", random_state=42)
# min_cluster_size=115 keeps ~88 clusters on the joint 6-venue corpus
# (~70k claims), matching the granularity of the EMNLP-only study corpus
# (80 clusters @ 16.5k claims, min_cluster_size=25).
HDBSCAN_PARAMS = dict(min_cluster_size=115, min_samples=5, metric="euclidean",
                      cluster_selection_method="eom")

# --- Embedding ablation (future work, REPORT_DRIFT_SPECTER2 §9 E1) -------------
# `acc.embed.embed_claims(texts, encoder=...)` is encoder-pluggable; register
# additional encoders in acc.embed to run the decisive embedding ablation.
DEFAULT_ENCODER = "specter2"
ABLATION_ENCODERS = ["e5-large-v2", "bge-large-en-v1.5", "gte-large", "scincl"]  # not yet implemented

# --- Drift color ramp (relative log2 share ratio) -----------------------------
DRIFT_EPS = 0.1       # pp smoothing for zero-start/zero-end clusters
DRIFT_LOG_MAX = 3.0   # |log2 ratio| that saturates the scale (= 8x)

# --- Cluster palette (size-ordered; carried over from main.ipynb cell 31) -----
CLUSTER_PALETTE = [
    '#1f77b4', '#d62728', '#2ca02c', '#ff7f0e', '#9467bd', '#17becf',
    '#8c564b', '#e377c2', '#bcbd22', '#7f7f7f', '#003f5c', '#ffa600',
    '#58508d', '#ef5675', '#72b7b2', '#4c78a8', '#f58518', '#54a24b',
    '#e45756', '#b279a2',
] * 10

# --- Curated human-readable labels: cluster id -> (short, full) ----------------
# short <= 24 chars (maps / figures / table cells); full for body text. Resolved
# with automatic-descriptor fallback by acc.cluster.short_label / full_label, so
# an unlabelled cluster degrades to its c-TF-IDF descriptor rather than breaking.
# All 80 clusters were reviewed against representative claims (CLUSTER_LABEL_REVIEW.md).
READABLE_LABELS = {
     0: ('Coreference Resolution', 'Coreference Resolution and Cross-Document Event Coreference'),
     1: ('Sentiment Analysis', 'Aspect-Based Sentiment Analysis'),
     2: ('Keyphrase Extraction/Gen', 'Keyphrase Extraction and Generation'),
     3: ('Paraphrase Generation', 'Paraphrase Generation and Control'),
     4: ('LLM Hallucination', 'Hallucination Detection and Mitigation in LLMs'),
     5: ('Molecule-Text Models', 'Molecule-Text Cross-Modal Modeling'),
     6: ('Vision-Language NLP', 'Vision-Language and Multimodal Models'),
     7: ('Text Summarization', 'Text Summarization Models and Evaluation'),
     8: ('Adversarial & Privacy', 'Adversarial Attacks, Robustness, and Privacy in NLP/LLMs'),
     9: ('Definitions & Clauses', 'Definitions, Legal Clauses, and Tables'),  # mixed
    10: ('Event Extraction', 'Event Detection and Relation Extraction'),
    11: ('Dialogue Systems', 'Dialogue and Conversational Systems'),
    12: ('Text Style Transfer', 'Text Style Transfer Methods'),
    13: ('Toxicity Detect & Detox', 'Toxicity Detection and Detoxification'),
    14: ('Text Classification', 'Hierarchical and Multi-Label Text Classification'),
    15: ('Few/Zero-Shot Learning', 'Few-Shot and Zero-Shot Learning'),
    16: ('Intent Detection', 'Few-Shot Intent Detection and Text Classification'),
    17: ('Story Generation', 'Story Generation, Evaluation and Representation'),
    18: ('Emotion & Affect NLP', 'Emotion, Affect and Personality Modeling'),
    19: ('Discourse Structure', 'Discourse Structure and Segmentation'),
    20: ('Argument Mining', 'Computational Argumentation and Argument Mining'),
    21: ('Conversational RecSys', 'Conversational and LLM-Based Recommendation Systems'),
    22: ('Claim Verification', 'Claim Detection, Decomposition and Fact Verification'),
    23: ('Explanations', 'Faithful Explanations and Rationales'),
    24: ('Dialogue Response Gen', 'Dialogue Response Generation and Selection'),
    25: ('SciBiomedical NLP', 'NLP for Scientific and Biomedical Literature'),
    26: ('Grammatical Error Corr.', 'Grammatical Error Correction and Detection'),
    27: ('LLM-as-a-Judge Eval', 'LLM-as-a-Judge and Automatic Evaluation'),
    28: ('Human-Metric Agreement', 'Human Agreement and Annotation Quality in Evaluation'),
    29: ('ICL Demonstrations', 'In-Context Learning Demonstration Selection'),
    30: ('Mental Health NLP', 'Mental Health Detection and Support NLP'),
    31: ('Document Layout', 'Document Layout and Reading-Order Understanding'),
    32: ('Rumor & Fake News Detect', 'Rumor and Fake News Detection'),
    33: ('Text Generation', 'Natural Language Generation Methods and Evaluation'),
    34: ('Text Simplification', 'Text Simplification and Edit-Based Rewriting'),
    35: ('Hate Speech Detection', 'Hate and Offensive Speech Detection'),
    36: ('Stance Detection', 'Stance Detection in News and Social Text'),
    37: ('Social & Political NLP', 'Social, Political, and Moral NLP'),
    38: ('Knowledge Distillation', 'Teacher-Student Knowledge Distillation'),
    39: ('Preference Optimization', 'Preference Optimization for LLM Alignment'),
    40: ('Non-Autoregressive MT', 'Non-Autoregressive Machine Translation'),
    41: ('Speech & Audio Models', 'Speech Processing and Audio-Language Models'),
    42: ('Speech Translation', 'End-to-End Speech Translation'),
    43: ('Machine Translation', 'Neural Machine Translation Methods'),
    44: ('RL Reward & Policy Opt', 'RL Reward Models and Policy Optimization'),
    45: ('RL Rewards for LLMs', 'Reward-Based RL Optimization of Language Models'),
    46: ('LLM Agents', 'LLM Agents and Multi-Agent Systems'),
    47: ('Prompt Tuning', 'Prompt Tuning and Engineering'),
    48: ('Arabic NLP & Dialects', 'Arabic NLP and Dialect-Aware LLM Evaluation'),
    49: ('Instruction Tuning Data', 'Instruction-Tuning Data Construction and Selection'),
    50: ('Code Intelligence', 'Machine Learning for Source Code'),
    51: ('Reading & Readability', 'Reading Comprehension and Text Readability'),
    52: ('NLP Meta-Eval Critique', 'Critical Meta-Science of NLP Evaluation'),
    53: ('Knowledge Graph Embed', 'Knowledge Graph Embedding and Completion'),
    54: ('Syntactic Parsing', 'Syntactic and Semantic Parsing'),
    55: ('Tokenization Methods', 'Tokenization and Token-Level Modeling'),
    56: ('Transformer Methods', 'Transformer Training and Efficiency Methods'),
    57: ('Dense Retrieval', 'Neural Information Retrieval and Dense Retrievers'),
    58: ('Relation Extraction', 'Relation Extraction and Open Information Extraction'),
    59: ('Dense Retrieval QA', 'Dense Retrieval and Query Rewriting for QA'),
    60: ('Dense Passage Retrieval', 'Dense Passage Retrieval Methods'),
    61: ('Text-to-SQL Parsing', 'Text-to-SQL Semantic Parsing'),
    62: ('Fact Verification', 'Fact Verification and Factuality Checking'),
    63: ('Topic Modeling', 'Neural and Probabilistic Topic Modeling'),
    64: ('Commonsense Reasoning', 'Commonsense Reasoning and Knowledge in NLP'),
    65: ('Entity Linking', 'Entity Linking and Alignment'),
    66: ('Named Entity Recognition', 'Named Entity Recognition'),
    67: ('Multi-Hop & Temporal QA', 'Complex Reasoning Question Answering'),
    68: ('Question Answering', 'Question Answering and Question Generation'),
    69: ('Morphological Inflection', 'Morphological Inflection and Lemmatization'),
    70: ('Word Alignment', 'Word and Cross-Lingual Alignment'),
    71: ('Cross-Lingual Transfer', 'Multilingual Models and Cross-Lingual Transfer'),
    72: ('Math & Logic Reasoning', 'Mathematical and Logical Reasoning in LLMs'),
    73: ('CoT Reasoning', 'Chain-of-Thought Reasoning in LLMs'),
    74: ('Text Embeddings', 'Word and Sentence Embedding Representations'),
    75: ('PLM Knowledge', 'Knowledge in Pre-trained Language Models'),
    76: ('Lexical Semantics', 'Lexical Ambiguity and Semantic Change'),
    77: ('Word Sense Disambig.', 'Word Sense Disambiguation and Sense Embeddings'),
    78: ('LLM Efficiency & PEFT', 'LLM Efficiency, Adaptation, and Compression'),
    79: ('NLI Bias & Factuality', 'NLI Robustness, Debiasing, and Factual Probing'),
}

# --- Headline themes for robustness sign-preservation checks -------------------
# canonical cluster id -> short name (subset of READABLE_LABELS).
HEADLINE = {
    54: "Parsing", 43: "MachineTranslation", 11: "Dialogue", 68: "QA",
    7: "Summarization", 6: "Multimodal", 72: "Reasoning", 46: "Agents",
    78: "LargeModelTuning", 57: "Retrieval", 39: "PrefOptimization",
    73: "LLMReasoning", 8: "Adversarial", 56: "ModelAdaptation", 37: "Social",
}
