# Optional crisis classification with Jev

The default remains `CRISIS_CLASSIFICATION_MODE=rules`. The optional `jev` mode asks Jev to assign crisis labels from the post's meaning, independently of the notebook's disaster keywords. It retains the original spaCy location extraction, gazetteer coordinates, US scope, storage, and dashboard. It is not enabled on the live feed yet.

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

For the semantic mode, the processor bypasses the batch keyword gate, and the model service still extracts and resolves locations when there is no rule-based disaster label. Jev then evaluates each supported crisis type against each resolved location. One or two locations share one request; additional locations use bounded chunks, with a maximum of eight locations. Multiple labels are allowed. A post with no score above the configured threshold is not published. API failures keep durable work queued; they never fall back to unreviewed labels.

The default 0.8 threshold is provisional. Probability scores are not calibrated accuracy measurements and do not verify that a reported event happened. The supported definitions are versioned as `crisis-v1`; they preserve the original crisis families while separating **Tornado** from **Hurricane**. Unrecognized disaster types remain unsupported. Output records carry classification mode/taxonomy provenance. The map retains its existing first-disaster display convention for multi-label records.

## Interview explanation and tradeoffs

Describe this as an optional modernization of the original system: a deterministic baseline, a context-aware classifier, and a controlled comparison. Use the Houston example to show why meaning can matter more than an exact word match. Report measured successes, mistakes, response times, and service failures rather than claiming 100% accuracy.

The location-aware classifier replaces the relevance-screening call for a typical one-location post. It does not guarantee lower latency or cost: more questions are evaluated, and bypassing the cheap keyword gate sends more posts through NLP and can increase API usage. Keep this optional until representative accuracy, throughput, and spending limits have been evaluated. Request limits are configured separately: `JEV_MAX_CALLS_PER_RUN=0` disables the app's cap; a positive integer limits attempts per processor run. Enabling semantic classification does not change that setting.

Provider references: [Jev's typed decisions and parallel questions](https://vercel.com/changelog/typesafe-ai-jev-now-available-on-ai-gateway), [HTTP API contract](https://vercel.com/changelog/ai-gateway-now-supports-typesafe-clients-and-http-api-for-jev), and [choosing thresholds from labeled examples](https://vercel.com/i/jev-probabilities-and-thresholds).
