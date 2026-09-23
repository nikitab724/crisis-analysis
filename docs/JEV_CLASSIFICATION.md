# Optional crisis classification with Jev

The repository default remains `CRISIS_CLASSIFICATION_MODE=rules`. The `jev` mode asks Jev to assign crisis labels from the post's meaning, independently of the notebook's disaster labels. It retains the original spaCy location extraction, gazetteer coordinates, US scope, storage, and dashboard. After bounded example tests, the owner enabled it on the live Mac backend on September 23, 2026.

## Try the Houston example

With the live Python dependencies installed and `AI_GATEWAY_API_KEY` in the ignored `.env`:

```sh
python scripts/classify_crisis.py --text "The streets in Houston are underwater and people are trapped in their homes."
```

This sends **one API request** and prints labels and scores. It does not require the model server or write a dashboard post. On September 23, 2026, a real Jev request returned **Flood, score 0.93**, in about **2.1 seconds** for this exact sentence. The original token rules returned no disaster label. This is an observed example, not a guarantee about future outputs or overall accuracy.

Text classification and location resolution are separate. The classifier can recognize flooding without deciding which Houston is meant. A live map point still needs the existing supported US location match; classification does not invent a state or coordinates.

## Compare before enabling

Preview the 12 fixed synthetic cases without making API calls:

```sh
python tests/check_jev_classification.py
```

Run the bounded comparison against the actual tokenizer and EntityRuler saved in `disaster_ner`:

```sh
python tests/check_jev_classification.py --run
```

This makes at most 12 API calls and writes an ignored report to `.demo-hosted/jev-classification-comparison.json`. It covers the exact Houston wording, paraphrases, metaphors, negation, history, fiction, multiple hazards, and instructions embedded in a post. `--case NAME` can select unfinished cases after an outage; `--output PATH` preserves separate attempts. The baseline is the original token rules alone, not the full existing pipeline with Jev relevance screening. These deliberately illustrative cases are not a representative or held-out accuracy benchmark.

The [recorded comparison](jev-classification-results.json) matched all 12 expected label sets after one provider error was retried. The rule-only baseline matched 2/12 on this deliberately chosen set; that is not a comparison against the current complete pipeline. Successful comparison requests had a median latency of about 308 ms. The separate initial Houston request took about 2.1 seconds, showing why one latency number is insufficient.

## Rehearse the optional pipeline

For an isolated known-post demo on unused ports:

```sh
CRISIS_CLASSIFICATION_MODE=jev CRISIS_RELEVANCE_MODE=jev \
  PORT=8053 MODEL_PORT=5005 python scripts/run_pipeline.py --mode demo
```

Both Jev stages share the existing key, threshold, cache, concurrency limit, and request allowance. An updated model service is required: it explicitly acknowledges that its disaster keyword gate was bypassed. An old server that ignores that option causes a retryable error, rather than silently losing non-keyword posts. The fixture demo always forces the original offline path.

In semantic mode, the model service extracts and resolves locations even without a rule-based disaster label. Live batches use `CRISIS_CANDIDATE_FILTER=expanded`: inexpensive, broad wording checks (including underwater, drowning, electricity, flickering, and attached headlines) select candidate reports before transformer inference. Jev makes the actual classification decision. This preserves live throughput but is still a recall limitation: indirect wording with no supported signal can be missed. Set `CRISIS_CANDIDATE_FILTER=all` for bounded evaluations of every post; it is unsuitable for the full firehose on the current Mac. Standalone examples already bypass batch screening.

The live configuration also uses `JEV_BATCH_SCREEN=on`. Up to 16 candidate posts (12,000 text characters total) share a preliminary Jev request before transformer inference and reply fetching. Only clear negatives below 0.2 are skipped; uncertain posts continue to location extraction and final classification at the normal 0.8 threshold. Failures retain the entire receipt. This preliminary screen is optional and off in the repository example configuration. It reduces unnecessary NLP but introduces another model decision and can still miss relevant reports; it is not a full-recall guarantee. A real 10-example screen retained the flooding, drowning, and outage cases while excluding a metaphor and generic flood susceptibility.

The approved Mac live configuration is:

```dotenv
CRISIS_RELEVANCE_MODE=jev
CRISIS_CLASSIFICATION_MODE=jev
CRISIS_CANDIDATE_FILTER=expanded
JEV_BATCH_SCREEN=on
```

Jev evaluates each supported type against each resolved location. Two locations currently share 30 Boolean questions; larger sets use chunks within the 32-question limit, with a maximum of eight locations. Multiple labels are allowed. A post with no score above the configured threshold is not published. API failures keep durable work queued; they never fall back to unreviewed labels.

The default 0.8 threshold is provisional. Probability scores are not calibrated accuracy measurements and do not verify that a reported event happened. `crisis-v2` adds **Drowning** and **Power Outage** to the 13 original semantic categories, including separate **Tornado** and **Hurricane** labels. The earlier recorded 12-case comparison used `crisis-v1`. Drowning alone does not establish flooding; generic susceptibility such as “prone to flood” does not establish an active event. Output records carry classification mode/taxonomy provenance. The map retains its first-disaster display convention for multi-label records.

## Reply and headline context

The collector saves parent/root post references and attached link-card titles/descriptions. For semantic candidates only, the processor fetches at most two public parent/root posts from Bluesky's fixed `getPosts` endpoint, with bounded text, timeouts, and a 1,024-entry cache. It does not crawl arbitrary article URLs or use profile locations. The target post stays separate from context in Jev's request. Prompts prohibit copying unrelated parent events, locations, historical reports, or a student's home/school city into the event location. Context source references are saved with accepted reports; the displayed text remains the original post. Context lookup failures keep work queued for retry.

This does not resolve every location. In real checks, the supplied New Mexico post mapped to a state-level Flood marker. The lake report classified as Drowning and the electricity post as Power Outage, but neither yielded a supported location. They remained unmapped instead of receiving invented coordinates. The current gazetteer lookup covers populated places and states, not arbitrary lakes or utility service areas. Short replies with no candidate wording are not fetched solely to discover a possible event in their parents.

## Interview explanation and tradeoffs

Describe this as an optional modernization of the original system: a deterministic baseline, a context-aware classifier, and a controlled comparison. Use the Houston example to show why meaning can matter more than an exact word match. Report measured successes, mistakes, response times, and service failures rather than claiming 100% accuracy.

The location-aware classifier replaces the relevance-screening call for a typical one-location post. It does not guarantee lower latency or cost: more questions are evaluated, broader candidates require more NLP, and some replies need a public context request. The illustrated examples do not establish representative accuracy or sustained throughput. Request limits are configured separately: `JEV_MAX_CALLS_PER_RUN=0` disables the app's cap; a positive integer limits attempts per processor run. Enabling semantic classification does not change that setting.

Provider references: [Jev's typed decisions and parallel questions](https://vercel.com/changelog/typesafe-ai-jev-now-available-on-ai-gateway), [HTTP API contract](https://vercel.com/changelog/ai-gateway-now-supports-typesafe-clients-and-http-api-for-jev), and [choosing thresholds from labeled examples](https://vercel.com/i/jev-probabilities-and-thresholds).
