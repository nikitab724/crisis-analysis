# Optional Jev relevance screening

Jev screens candidate US disaster reports for literal event relevance before they are saved. For example, a post about a claimed current disease outbreak should be distinguished from a “pandemic of bad drivers,” a board game, or a recollection of past lockdowns. It also checks whether the reported event affects the matched US location rather than merely mentioning that place.

This is **claim classification, not fact verification**. A made-up report can still read like a literal event. The model has no news retrieval or independent evidence in this integration.

## Configure Vercel AI Gateway

Create an [AI Gateway key](https://vercel.com/docs/ai-gateway/authentication-and-byok) and store it only in the server environment or this repository's ignored `.env` file:

```dotenv
AI_GATEWAY_API_KEY=your-gateway-key
CRISIS_RELEVANCE_MODE=off
JEV_MIN_PROBABILITY=0.8
JEV_MAX_CALLS_PER_RUN=200
```

Run the bounded evaluation first, using the installed live Python environment:

```sh
python tests/check_jev_relevance.py
```

This explicitly makes up to 12 requests using authored synthetic examples and saves an ignored `.demo-hosted/jev-evaluation.json` report. It measures end-to-end latency and agreement with the example labels without injecting posts into the dashboard. On September 22, 2026, the real Gateway call passed all 12 examples at the default 0.8 threshold: median response time 333.8 ms, maximum 1012.4 ms. These are a small smoke test, not measured general accuracy or a speed comparison with spaCy. Broader validation on independently labeled posts is still needed before replacing the original NLP.

To enable screening after reviewing the results, set `CRISIS_RELEVANCE_MODE=jev` and restart the live pipeline. Off is the default and makes no Jev calls. The deterministic fixture always bypasses Jev, even when the environment enables it.

## Behavior and limits

- Uses Vercel's [HTTP evaluation API](https://vercel.com/changelog/ai-gateway-now-supports-typesafe-clients-and-http-api-for-jev): `POST https://ai-gateway.vercel.sh/v1/evaluate`, model `typesafe-ai/jev`, boolean questions, and numeric `probability` answers. It uses the existing Python HTTP dependency; LangChain and a separate Node service are unnecessary.
- Runs only after the existing NLP detects a disaster and the US gazetteer resolves a supported US location. One request evaluates all candidate disaster/location pairs for that post. Low-scoring disaster labels are removed individually; a location record stays only if at least one label passes.
- Requires probability at least `JEV_MIN_PROBABILITY` (default 0.8). This is a provisional threshold, not a measured accuracy guarantee. No percentage is presented as verified-event confidence in the UI.
- Bounds each request to 32 candidate pairs, 10,000 text characters, and connect/read timeouts of 3/6 seconds. Successful evaluations are cached in memory (512 entries). Requests have no automatic retries; an error pauses further attempts for 30 seconds.
- Caps API calls at `JEV_MAX_CALLS_PER_RUN` (default 200) per processor process, including failed attempts. A restart resets that cap; this is not a billing limit. Provider budgets/credits remain authoritative. Check [current Gateway pricing](https://vercel.com/ai-gateway/models/jev); promotional “Free” listings are not an unlimited-free guarantee. This code never purchases credits or enables top-ups.
- Missing, malformed, uncertain, failed, or budget-exhausted decisions never become automatic approvals. In enabled mode those candidates are skipped, and failures appear in live activity. Previously saved records are not retroactively screened or labeled as screened.
- Saves the model alias, minimum accepted probability, and `relevance_status=passed` with retained records. Public activity includes `relevance_checked`, `relevance_excluded`, and `relevance_errors`; the first two count location records and errors count posts whose review was unavailable.

Only candidate public post text, its timestamp, and extracted location/disaster labels are sent to Vercel/TypeSafe. Credentials stay server-side and provider errors are not logged verbatim.

The transformer still extracts free-form locations, and the gazetteer still supplies coordinates. Jev returns bounded decisions rather than arbitrary place strings, so replacing those steps would require a separate extraction/candidate-selection design. Adding this screen does not by itself make the existing transformer faster or smaller.
