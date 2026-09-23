# Optional Jev location selection and relevance screening

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

To enable location selection and screening after reviewing the results, set `CRISIS_RELEVANCE_MODE=jev` and restart the live pipeline. Off is the default and makes no Jev calls. The deterministic fixture always bypasses Jev, even when the environment enables it.

## Ambiguous city names

The existing transformer extracts location mentions and the gazetteer finds exact names or whole aliases. Explicit city/state matches still take the existing path. When there are several possible cities, the model service supplies their canonical names, states, identifiers, and coordinates to the processor.

The processor asks Jev two independent questions in one request for each ambiguous mention: choose a supplied candidate (or **unknown**), and judge whether the post provides geographic evidence that uniquely distinguishes a candidate. For example, “Flood in Portland along the Willamette River” points to Oregon, while Casco Bay points to Maine. “Flood in Portland” alone must remain unresolved. The writer's home location is not evidence for where the event happened.

Both the selected-option probability and the geographic-evidence probability must reach **0.9**. This is a conservative provisional rule, not a calibrated accuracy estimate. Coordinates and names are copied from the selected database record; Jev cannot supply new coordinates or invent a city. If two candidates share both city and state, the choice remains unresolved because the current candidate schema lacks county/landmark information to distinguish them. Foreign-context rules remain active before classification.

Candidate lists must be complete within their query window: at most **50 cities per mention**, **8 ambiguous mentions per post**. Larger exact-name results and alias scans that hit the existing 26-row search limit are not offered as partial choices. Unknown, low-scoring, malformed, and unavailable decisions remain unresolved. A successful choice then goes through the separate disaster-relevance check before being saved. State-only supporting rows and duplicate locations are folded into the selected city so report counts are not inflated.

Run the real-provider location smoke test with:

```sh
python tests/check_jev_locations.py
```

It reads real Supabase candidates and makes at most eight Gateway requests, without writing posts or database rows. On September 22, 2026, **8/8 authored examples passed with all 27 Portland candidates**, including river/bay clues, bare names, foreign places, unrelated author location, multiple places, embedded instructions, and reversed option order. Median call latency was **262.1 ms**, maximum **413.1 ms**. Results are saved to ignored `.demo-hosted/jev-location-evaluation.json`. These examples are a smoke test, not general location accuracy.

To exercise both Jev stages after the real NLP and database lookup, run `python tests/check_jev_location_pipeline.py --url http://127.0.0.1:5002` against your running model service (adjust its port). This separate six-example check makes at most 12 Gateway calls and never saves posts.

## Behavior and limits

- Uses Vercel's [HTTP evaluation API](https://vercel.com/docs/ai-gateway/modalities/evaluation): `POST https://ai-gateway.vercel.sh/v1/evaluate`, model `typesafe-ai/jev`, choice/boolean questions, and numeric probability answers. It uses the existing Python HTTP dependency; LangChain and a separate Node service are unnecessary.
- Runs only after the existing NLP detects a disaster and location mentions. Ambiguous names can use one candidate-selection request; after locations resolve, a separate request evaluates all candidate disaster/location pairs for that post. Low-scoring disaster labels are removed individually; a location record stays only if at least one label passes. Unique city/state matches need only the relevance request.
- Requires probability at least `JEV_MIN_PROBABILITY` (default 0.8). This is a provisional threshold, not a measured accuracy guarantee. No percentage is presented as verified-event confidence in the UI.
- Bounds each request to 32 candidate pairs, 10,000 text characters, and connect/read timeouts of 3/6 seconds. Successful evaluations are cached in memory (512 entries). Requests have no automatic retries; an error pauses further attempts for 30 seconds.
- `JEV_MAX_CALLS_PER_RUN` defaults to 200 attempts per processor process, **shared by location selection, relevance screening, and optional crisis classification**, including failed attempts. Set it to **`0` in the backend's `.env` and restart the processor to disable the app's cap**. Positive integers retain a finite allowance; negative values are rejected. Two concurrent requests, caching, timeouts, and the 30-second failure cooldown apply in both modes. `/activity` reports `jev_max_calls: 0` when uncapped and continues counting requests. A restart resets the count; this is not a billing limit. Provider budgets, credits, and rate limits remain authoritative. Check [current Gateway pricing](https://vercel.com/ai-gateway/models/jev); this code never purchases credits or enables top-ups.
- Missing, malformed, uncertain, failed, or budget-exhausted decisions never become automatic approvals. Valid negative/uncertain decisions exclude the candidate. In the continuous live pipeline, unavailable/failed decisions keep the entire batch queued for retry; an exhausted request cap pauses that batch until the operator restores availability. Failures appear in live activity and include retry attempts. Standalone checks without a queued receipt still omit unavailable candidates. Previously saved records are not retroactively screened or labeled as screened.
- Saves the model alias, minimum accepted probability, and `relevance_status=passed` with retained records. Public activity includes `relevance_checked`, `relevance_excluded`, and `relevance_errors`; the first two count location records and errors count posts whose review was unavailable.
- Context-selected rows also save `geonameid`, `location_model`, `location_probability`, and `location_context_probability`, and display a context-match label. Activity tracks `location_checked` and `location_resolved` (mentions), plus `location_errors` (posts with unavailable location review). Existing saved records are not reclassified.

Only candidate public post text, its timestamp, extracted location/disaster labels, and candidate city/state names and gazetteer identifiers are sent to Vercel/TypeSafe. Coordinates stay local. Credentials stay server-side and provider errors are not logged verbatim.

The transformer still extracts free-form locations, and the gazetteer still supplies coordinates. Jev returns bounded decisions rather than arbitrary place strings. These added checks do not make the existing transformer faster or smaller, and cannot recover a place mention the transformer missed.
