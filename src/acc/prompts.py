acc_extractor_prompt = """You extract Atomic Contribution Claims (ACCs) from <<DOMAIN>> paper titles and abstracts.

An ACC is a faithful, self-contained, atomic, contribution-bearing proposition about what this paper contributes to the scientific record.

Your task is not to summarize the abstract. Extract only claims about what the paper itself introduces, proposes, evaluates, measures, demonstrates, or establishes.

Include claims about:
- new methods, models, architectures, algorithms, objectives, training procedures, or inference procedures;
- new datasets, benchmarks, resources, taxonomies, tools, annotation schemes, or evaluation setups;
- empirical findings established by the paper;
- concrete analyses of model behavior, data, tasks, or evaluation practices performed by the paper.

Exclude:
- background, motivation, or general field context;
- known limitations or prior-work claims unless this paper explicitly measures, demonstrates, or establishes them;
- vague problem statements such as “X is challenging”;
- related-work summaries;
- future work, broad impact claims, code availability, website links, or release logistics;
- raw metric-only claims such as “improves F1 by 2.3 points”. If the result is contribution-bearing, rewrite it as the scientific nature of the result instead.

Critical distinction:
A statement about existing models, datasets, or tasks is an ACC only if the abstract presents it as a finding, measurement, analysis, or conclusion of this paper. If it merely motivates the work, omit it.

Rules:
1. Atomicity: each claim must contain exactly one scientific proposition.
2. Faithfulness: do not add facts, mechanisms, entities, datasets, or conclusions not stated in the title or abstract.
3. Decontextualization: each claim must be understandable without the abstract. Resolve pronouns and vague references.
4. No meta-language: do not write “this paper”, “we”, “our method”, “the authors”, “the proposed model”, “the proposed method”, “this framework”, or “the approach”.
5. Granularity: prefer mid-level scientific claims. Avoid both overly broad claims and overly specific raw numbers.
6. No raw metrics: do not include exact numerical scores, percentages, or benchmark numbers. If a result is contribution-bearing, rewrite it without the number while preserving the type of result.
7. No near-duplicates: do not extract multiple claims that state the same contribution at different levels of detail. Keep the most specific faithful version.
8. Omit vague effectiveness claims such as “is effective”, “improves performance”, or “produces high-quality results” if a more specific claim has already been extracted.
9. If unsure whether a statement is a contribution, omit it.
10. Usually extract 1–5 claims. Return an empty list if the abstract contains no clear contribution-bearing claims.

Self-validation before output:
Before returning the JSON, silently check every candidate claim against all four core criteria:
- contribution-bearing;
- atomic;
- faithful to the title and abstract;
- decontextualized.

Discard any candidate claim that fails any criterion or is uncertain. Do not explain this check. Return only the final accepted claims.

Return ONLY valid JSON in this exact format:
{
  "claims": [
    {
      "text": "A self-contained atomic contribution claim."
    }
  ]
}

If there are no valid ACCs, return:
{"claims": []}

Examples:

Input:
Title: PromptShield: Defending Instruction-Following Models
Abstract: We introduce PromptShield, a method for detecting jailbreak attempts in instruction-following models. PromptShield uses a contrastive objective over benign and malicious prompts. Experiments show that PromptShield improves jailbreak detection F1 by 6 points while maintaining a low false positive rate. Code is available online.

Output:
{
  "claims": [
    {
      "text": "PromptShield detects jailbreak attempts in instruction-following models."
    },
    {
      "text": "PromptShield uses a contrastive objective to distinguish benign prompts from malicious prompts."
    },
    {
      "text": "PromptShield improves jailbreak detection while maintaining a low false positive rate."
    }
  ]
}

Input:
Title: CompBench: A Benchmark for Compositional Reasoning
Abstract: Large language models are increasingly used for reasoning tasks, but they often struggle with compositional generalization. To address this problem, we introduce CompBench, a benchmark for evaluating compositional reasoning under controlled perturbations.

Output:
{
  "claims": [
    {
      "text": "CompBench evaluates compositional reasoning under controlled perturbations."
    }
  ]
}

Input:
Title: Nationality Personas in Large Language Models
Abstract: We analyze nationality personas in large language models and find that Eastern European, Latin American, and African national personas are associated with more negative sentiment than other regions.

Output:
{
  "claims": [
    {
      "text": "Large language models associate Eastern European, Latin American, and African national personas with more negative sentiment than other regions."
    }
  ]
}

Input:
Title: Recent Progress in Prompting
Abstract: Recent advances in large language models have transformed natural language processing. Prompting and instruction tuning are now widely used across many applications. This area is rapidly evolving and requires further research.

Output:
{"claims": []}

PAPER DATA TO PROCESS:
Title: <<TITLE>>
Abstract: <<ABSTRACT>>
"""

llm_as_judge_prompt = """You are evaluating extracted Atomic Contribution Claims (ACCs) from <<DOMAIN>> paper titles and abstracts.

Your task is to decide whether each candidate claim is an acceptable ACC for the given paper.

An Atomic Contribution Claim (ACC) is a short, self-contained claim about a concrete contribution of this paper.

A candidate claim should be labeled GOOD only if it satisfies all three core requirements:

1. SUPPORTED
The claim is supported by the title and abstract.
It must not add important facts, mechanisms, entities, datasets, conclusions, causal explanations, or scope that are not stated or clearly implied.

2. CONTRIBUTION-BEARING
The claim describes what this paper contributes to the scientific record.
This includes something the paper introduces, proposes, builds, evaluates, measures, analyzes, demonstrates, or establishes.

Valid contribution types include:
- method, model, architecture, algorithm, objective, training procedure, inference procedure;
- dataset, benchmark, resource, taxonomy, annotation scheme, tool, evaluation setup;
- empirical finding or result established by the paper;
- concrete analysis of model behavior, data, tasks, or evaluation practices performed by the paper.

A statement about existing models, datasets, tasks, or known problems is GOOD only if the abstract presents it as a finding, measurement, analysis, or conclusion of this paper.
If it merely motivates the work or describes general field context, it is BAD.

3. ATOMIC AND SELF-CONTAINED ENOUGH
The claim expresses one main scientific proposition and can be mostly understood without reading the abstract.
It should avoid unresolved references such as “this method,” “the model,” “our approach,” “it,” or “the proposed framework.”
Do not reject a claim only because it could be split more elegantly. Reject it only if it clearly merges separate contributions in a confusing or misleading way.

Labels:
- GOOD: acceptable ACC.
- BAD: clearly not an acceptable ACC.
- UNSURE: borderline case; use sparingly.

Use GOOD when the claim is basically correct, contribution-bearing, and usable for downstream clustering.
Use BAD when there is a clear substantive flaw.
Use UNSURE only when the decision genuinely depends on interpretation.

Common BAD cases:
- background or motivation rather than a paper contribution;
- unsupported information or hallucinated detail;
- too vague or generic to identify a concrete contribution;
- not understandable without the abstract;
- overgeneralizes a narrow result;
- merges separate claims in a way that changes or obscures the meaning.

Return ONLY valid JSON.
Do not include markdown.
Preserve item_id exactly.

Output format:
{
  "evaluations": [
    {
      "label": "GOOD | BAD | UNSURE",
      "main_issue": "none | background_context | unsupported | too_vague | not_self_contained | not_contribution | overgeneralized | mixed_claims | other",
      "brief_reason": "One short sentence explaining the decision.",
      "confidence": "high | medium | low"
    }
  ]
}

Examples:

Example 1 — GOOD method claim

Title:
PromptShield: Defending Instruction-Following Models

Abstract:
We introduce PromptShield, a method for detecting jailbreak attempts in instruction-following models. PromptShield uses a contrastive objective over benign and malicious prompts. Experiments show that PromptShield improves jailbreak detection F1 by 6 points while maintaining a low false positive rate. Code is available online.

Candidate claim:
PromptShield uses a contrastive objective to distinguish benign prompts from malicious prompts.

Output:
{
  "label": "GOOD",
  "main_issue": "none",
  "brief_reason": "The claim is supported, self-contained, and describes a concrete method contribution.",
  "confidence": "high"
}

Example 2 — GOOD result claim with metric generalized

Title:
PromptShield: Defending Instruction-Following Models

Abstract:
We introduce PromptShield, a method for detecting jailbreak attempts in instruction-following models. PromptShield uses a contrastive objective over benign and malicious prompts. Experiments show that PromptShield improves jailbreak detection F1 by 6 points while maintaining a low false positive rate. Code is available online.

Candidate claim:
PromptShield improves jailbreak detection while maintaining a low false positive rate.

Output:
{
  "label": "GOOD",
  "main_issue": "none",
  "brief_reason": "The claim faithfully converts a numerical result into a qualitative contribution-bearing result.",
  "confidence": "high"
}

Example 3 — BAD background/context

Title:
CompBench: A Benchmark for Compositional Reasoning

Abstract:
Large language models are increasingly used for reasoning tasks, but they often struggle with compositional generalization. To address this problem, we introduce CompBench, a benchmark for evaluating compositional reasoning under controlled perturbations.

Candidate claim:
Large language models are increasingly used for reasoning tasks.

Output:
{
  "label": "BAD",
  "main_issue": "background_context",
  "brief_reason": "The claim is general background context rather than a contribution of the paper.",
  "confidence": "high"
}

Example 4 — GOOD resource claim

Title:
CompBench: A Benchmark for Compositional Reasoning

Abstract:
Large language models are increasingly used for reasoning tasks, but they often struggle with compositional generalization. To address this problem, we introduce CompBench, a benchmark for evaluating compositional reasoning under controlled perturbations.

Candidate claim:
CompBench evaluates compositional reasoning under controlled perturbations.

Output:
{
  "label": "GOOD",
  "main_issue": "none",
  "brief_reason": "The claim describes the benchmark contribution introduced by the paper.",
  "confidence": "high"
}

Example 5 — BAD known problem / motivation

Title:
CompBench: A Benchmark for Compositional Reasoning

Abstract:
Large language models are increasingly used for reasoning tasks, but they often struggle with compositional generalization. To address this problem, we introduce CompBench, a benchmark for evaluating compositional reasoning under controlled perturbations.

Candidate claim:
Large language models struggle with compositional generalization.

Output:
{
  "label": "BAD",
  "main_issue": "background_context",
  "brief_reason": "The abstract uses this statement as motivation, not as a finding established by the paper.",
  "confidence": "high"
}

Example 6 — GOOD finding about existing models

Title:
Nationality Personas in Large Language Models

Abstract:
We analyze nationality personas in large language models and find that Eastern European, Latin American, and African national personas are associated with more negative sentiment than other regions.

Candidate claim:
Large language models associate Eastern European, Latin American, and African national personas with more negative sentiment than other regions.

Output:
{
  "label": "GOOD",
  "main_issue": "none",
  "brief_reason": "Although the claim concerns existing models, the abstract presents it as an empirical finding of this paper.",
  "confidence": "high"
}

Example 7 — BAD unsupported detail

Title:
GraphPrompt: Retrieval-Augmented Prompting for Multi-Hop QA

Abstract:
We propose GraphPrompt, a retrieval-augmented prompting method for multi-hop question answering. GraphPrompt constructs an entity graph from retrieved passages and uses graph paths to guide answer generation. Experiments show that GraphPrompt improves answer faithfulness on multi-hop QA benchmarks.

Candidate claim:
GraphPrompt uses reinforcement learning to optimize graph paths for multi-hop question answering.

Output:
{
  "label": "BAD",
  "main_issue": "unsupported",
  "brief_reason": "The abstract does not state that GraphPrompt uses reinforcement learning.",
  "confidence": "high"
}

Example 8 — BAD not self-contained

Title:
GraphPrompt: Retrieval-Augmented Prompting for Multi-Hop QA

Abstract:
We propose GraphPrompt, a retrieval-augmented prompting method for multi-hop question answering. GraphPrompt constructs an entity graph from retrieved passages and uses graph paths to guide answer generation. Experiments show that GraphPrompt improves answer faithfulness on multi-hop QA benchmarks.

Candidate claim:
The proposed method improves answer faithfulness.

Output:
{
  "label": "BAD",
  "main_issue": "not_self_contained",
  "brief_reason": "The claim uses an unresolved reference and does not identify the method or task.",
  "confidence": "high"
}

Example 9 — UNSURE mixed but supported

Title:
GraphPrompt: Retrieval-Augmented Prompting for Multi-Hop QA

Abstract:
We propose GraphPrompt, a retrieval-augmented prompting method for multi-hop question answering. GraphPrompt constructs an entity graph from retrieved passages and uses graph paths to guide answer generation. Experiments show that GraphPrompt improves answer faithfulness on multi-hop QA benchmarks.

Candidate claim:
GraphPrompt constructs an entity graph from retrieved passages and improves answer faithfulness on multi-hop QA benchmarks.

Output:
{
  "label": "UNSURE",
  "main_issue": "mixed_claims",
  "brief_reason": "The claim is supported and contribution-bearing, but it combines a method mechanism and an empirical result.",
  "confidence": "medium"
}

Example 10 — BAD too vague

Title:
GraphPrompt: Retrieval-Augmented Prompting for Multi-Hop QA

Abstract:
We propose GraphPrompt, a retrieval-augmented prompting method for multi-hop question answering. GraphPrompt constructs an entity graph from retrieved passages and uses graph paths to guide answer generation. Experiments show that GraphPrompt improves answer faithfulness on multi-hop QA benchmarks.

Candidate claim:
GraphPrompt is effective for question answering.

Output:
{
  "label": "BAD",
  "main_issue": "too_vague",
  "brief_reason": "The claim is too vague and loses the concrete contribution described in the abstract.",
  "confidence": "high"
}

Now evaluate the following items.

Input JSON:
{
  "items": [
    {
      "title": "<<TITLE>>",
      "abstract": "<<ABSTRACT>>",
      "candidate_claim": "<<CLAIM>>"
    }
  ]
}
"""

acc_namer_prompt = """You name a topic cluster discovered in a large collection of <<DOMAIN>> scientific contribution claims.

You are given, for one cluster: representative claims (the ones closest to the cluster centroid), lexical keyword hints (class-based TF-IDF — anchors only, they can mislead), the cluster size, and its year/venue spread.

Decide what this cluster is really about by reading the CLAIMS themselves, then return two names:

- "short": a concise topic label, typically 2–4 words, that a researcher in the field would immediately recognize as the name of this subfield. It must:
  * capture the ESSENCE of the cluster as a natural, cohesive phrase;
  * NOT be a truncation of the long name, and NOT be padded with empty words (method, model, approach, task, framework, system, technique, learning) unless one is genuinely part of the field's name;
  * name the actual subfield specifically (e.g. prefer "Chain-of-Thought Reasoning" over "Reasoning", "Aspect Sentiment" over "Sentiment").
  If the cluster genuinely centers on two co-equal themes, you may join them — but strongly prefer a single cohesive phrase (e.g. "Efficient Transformers" rather than "Transformers & Efficiency"). Use "&" or "and" sparingly, only when a single phrase would lose real meaning.

- "full": a slightly longer, precise descriptive name (up to ~60 characters) for detail views.

Guidelines:
- Be specific and faithful to the claims, not generic.
- A cluster may be a bit heterogeneous; name the dominant, unifying theme.
- Title Case. No trailing punctuation. No quotes inside the names.

Examples (short → full):
- Efficient Transformers → Transformer Training and Efficiency Methods
- Aspect Sentiment → Aspect-Based Sentiment Analysis
- Chain-of-Thought Reasoning → Chain-of-Thought Reasoning in LLMs
- Dialogue Systems → Task-Oriented Dialogue and Response Generation
- Dense Retrieval → Neural Dense Passage Retrieval
- Hate Speech Detection → Hate and Offensive Speech Detection

Return ONLY valid JSON in this exact format:
{"short": "…", "full": "…"}

CLUSTER TO NAME:
<<CARD>>
"""

# The corpus the tool ships with is NLP (ACL Anthology venues), so the few-shot
# examples above are NLP-flavoured. The opening line is domain-parameterised
# (<<DOMAIN>>) so the same pipeline runs on any field: pass e.g. "biomedical" or
# "machine learning" — and, for a distant field, swap the examples too.
DEFAULT_DOMAIN = "NLP"


def extractor_prompt(domain: str = DEFAULT_DOMAIN) -> str:
    return acc_extractor_prompt.replace("<<DOMAIN>>", domain)


def judge_prompt(domain: str = DEFAULT_DOMAIN) -> str:
    return llm_as_judge_prompt.replace("<<DOMAIN>>", domain)