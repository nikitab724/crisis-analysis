# Cleanup audit and validation

Scope: interview preparation, reproducible model build, and one dependable demo path. The existing service boundaries, transformer, disaster rules, sentiment approach, and CSV architecture are retained.

## Optional request cap and live recovery checkpoint

On September 23, 2026, added `JEV_MAX_CALLS_PER_RUN=0` to disable the app's per-process request cap, following the owner's request. Positive limits retain the existing atomic cap. Two concurrent requests, caching, confidence thresholds, provider-failure cooldown, and durable retry behavior remain active. The repository default is still 200; the running Mac backend's ignored `.env` now explicitly uses 0. Semantic crisis classification remains optional and was not activated by this operational change.

- All **157 regression tests passed**, plus targeted lint and whitespace checks. New tests cover continuing past 200 calls in uncapped mode, environment loading, invalid limits, cache reuse, and a provider 429 that retains the receipt and applies cooldown without falsely reporting an exhausted app limit.
- Archived the 447 existing reports, verified their totals, and replaced only the processor. The original supervisor had already exited; the model, collector, dashboard, and tunnel were still running and were preserved. The replacement uses the same report directory and durable queue; process metadata now records the individual service PIDs.
- Public Render `/activity` confirmed `jev_max_calls: 0`. The first provider call failed and triggered the existing cooldown; the retry succeeded and processing resumed. At 22:00 UTC, 2,303 additional queued posts had been acknowledged and the queue had fallen from 100,000 to 97,697. This establishes recovery, not a guarantee that the full backlog has caught up or that provider delays cannot recur.
- The public warning callback returned HTTP 200 with no usage-limit warning. API unavailability and backlog still produce their appropriate warnings. No provider account limits, billing settings, or Render plan were changed.

## Optional semantic classifier checkpoint

On September 23, 2026, added opt-in Jev crisis classification and retained the original rules as the default. The owner explicitly chose comparison before live activation. No live environment setting, processing budget, model weights, database schema, or pipeline process was changed.

- The exact requested sentence, **“The streets in Houston are underwater and people are trapped in their homes.”**, returned **Flood, score 0.93** from a real Jev request. The original token rules returned no label. The first isolated call took 2,088 ms.
- All **154 regression tests passed** in the full environment; the lightweight environment passed 110 and skipped 44 optional live checks. Added coverage includes independent category assignment, multiple hazards and locations, bounded question chunks, cache/cap sharing, malformed output, no partial publication on failure, durable retry, old-server compatibility, no-keyword location extraction, and offline-fixture isolation.
- The real-backend runtime check passed NLP, SDK/local HTTP gazetteer responses, the new gate-bypass path for a non-keyword Austin post, all four dashboard callbacks, outage recovery, bounded lookup timeouts, and cleanup. The first attempt encountered a NumPy worker-start error; an unchanged rerun passed. That transient startup issue is recorded, not treated as a classifier accuracy failure.
- A bounded provider comparison completed 12/12 expected label sets after retrying one provider error (13 attempted comparison calls). The rule-only baseline matched 2/12; it excludes the existing Jev relevance screen. Successful comparison requests had a 307.5 ms median. These deliberately selected synthetic examples do not establish overall accuracy, calibration, or sustained throughput. The prompts and [recorded results](jev-classification-results.json) remain reviewable.
- Both keyword gates are bypassed only in the opt-in mode, allowing non-keyword descriptions to reach semantic classification. A typical one-location post uses classification in place of the relevance call; extra locations are bounded and chunked. US geocoding still controls which records can appear on the map. Text-only classification can identify a crisis while its place is unresolved.
- The original live feed remains paused at its configured 200-call limit. A broader semantic path may increase transformer work and API usage; it has not been enabled to process the live backlog. See [Jev classification and demo commands](JEV_CLASSIFICATION.md).

## Simplified dashboard and connection recovery checkpoint

On September 23, 2026, simplified the dashboard to a full-width report map and a readable recent-post feed with a state filter. Removed the state chart, overview statistics, sentiment column, repeated matching notes, and data-explanation footer. Source links, timestamps, circle-size legend, sample-data labels, US scope, and the rolling 24-hour window remain. Collection and analysis behavior are unchanged. Detailed diagnostics remain available through `/activity` rather than repeated in the interface.

- All **139 regression tests passed**. After the final warning refinement, all nine activity tests passed again. Targeted lint, whitespace checks, the UI mechanical detector, and foreground-text contrast calculations passed.
- Reloaded only the dashboard worker, preserving the live processor and durable queue. Warnings remain hidden during healthy operation; an exhausted Jev allowance now has a concise usage-limit warning rather than a misleading catching-up message.
- Verification found that the previous temporary Cloudflare tunnel had expired. Replaced it, updated the existing Free Render service's `LIVE_DASHBOARD_URL`, and redeployed its existing gateway build. Render reported the replacement deployment live at **2026-09-23 21:34 UTC**. No paid service or API-budget increase was applied.
- Public Render checks passed the simplified layout, **11 assets**, exact stylesheet match, all **four remaining callbacks**, real post links, state filtering, and the empty state. Analysis readiness still returns **503** because the existing **200-call Jev allowance is exhausted**; the page correctly shows that warning. Restoring the page's connection does not resume analysis or guarantee recovery beyond the provider's replay window.
- Browser visual inspection remains blocked by an unavailable admin-enforced security check. No alternate browser bypass was used; HTTP verification does not establish visual rendering or keyboard behavior.

## Concurrent processing checkpoint

On September 23, 2026, added bounded concurrent post processing, grouped screening with the existing token rules, pooled HTTP connections, reuse of completed posts during receipt retries, and removal of the pause after full batches. Live batches contain up to 100 posts, four post workers overlap network waits, and two Jev slots share the original request cap and cooldown. One lock protects the single loaded transformer. Output order, classification prompts, thresholds, source deduplication, and the single CSV writer remain unchanged. A failed location lookup now keeps the receipt pending instead of being mistaken for a completed nonmatch.

- **139 regression tests passed** in the full environment; the minimal environment passed 97 and skipped 42 optional live checks. Coverage includes bounded concurrency, an atomic Jev budget, shared in-flight decisions, cooldown propagation, completed-post reuse, final progress after duplicate removal, private endpoint bounds, and a specific warning when the request limit stops analysis.
- A controlled 1,000-post burst took **10.395 seconds sequentially and 1.442 seconds concurrently (7.21×)**. Both runs accepted identical 50 location records and made 50 simulated Jev requests. Model-service calls fell from 1,000 to 50, plus one grouped screening request per optimized batch. The test uses the real queue/processor with prescribed service delays, not a live throughput or accuracy benchmark.
- The real-model integration passed batch screening, identical serial/concurrent outputs, all five data callbacks, database outage/recovery and timeouts, and process cleanup. **19 location cases** passed concurrently against the actual model and hosted gazetteer. Public Render checks passed readiness, 11 assets, all six callbacks, and Jev activity.
- The upgrade preserved all **302 current report records** and the persistent queue. After restart, 5,617 posts were queued with an oldest age of 260.9 seconds. The queue subsequently drained. Across nine samples over 40 seconds, 1,833 posts arrived and 1,836 were acknowledged, sampled waiting age peaked at **0.9 seconds**, and the last sample had an empty queue and no known gaps. Two transient database disconnects retained their posts for successful retry. These bounded observations do not guarantee continuous coverage or latency.
- Inspection also identified exhaustion of the original **200-call per-run Jev guard** as a separate cause of a stalled batch. The concurrency update retains that configured allowance; a fresh process starts a new run as before. Restarting to apply the update therefore also reset that run's counter, so the observed recovery cannot be attributed solely to faster processing. The exhausted-limit warning is now explicit, and diagnostics expose the call count/cap without adding routine UI statistics. Increasing the allowance requires the owner's budget choice.

## Rolling 24-hour window checkpoint

On September 23, 2026, live reports began expiring by their original posting time. The processor removes expired reports from active CSVs and rebuilds counts; dashboard callbacks independently filter the same window. The fixed interview demos remain repeatable. Earlier checkpoints below describe behavior at their respective dates.

- **126 regression tests passed** in the full environment. The lightweight environment passed 86 and skipped 40 optional live checks. Coverage includes the exact expiry boundary, timezone offsets, invalid/future dates, cleanup during collection outages, empty reports/counts, stale saved totals, expired queue acknowledgements without model calls, repair after an interrupted write, and resuming an empty run.
- The real-model runtime check passed NLP, the database SDK with controlled local HTTP responses, all five data callbacks, database outage/recovery and timeouts, and child-process cleanup. Targeted lint and whitespace checks passed.
- The Mac upgrade preserved all **159 unexpired location records** from the prior 160-record snapshot and removed its historical synthetic example. Active CSV counts matched the remaining reports. The persistent ingest queue resumed from its saved position; the collector reported a connected stream and no known gaps at verification. A backlog was still present, so this is not a throughput claim.
- Local readiness and the replacement public tunnel returned healthy live status. The original temporary tunnel had failed independently; Render's existing Free gateway was pointed at the verified replacement, and its deployment reached `live`. An initial HTTP 429 challenge from Render's public edge cleared after backing off.
- Both the local gateway rehearsal through the replacement HTTPS tunnel and the final public Render check passed live readiness, 11 browser assets, layout, all six dashboard callbacks, Jev activity, and denial of the private model route. Render's returned layout also showed the new **Last 24 hours** summary. These are HTTP/data checks; visual browser inspection remains unavailable.

## Continuous collection checkpoint

On September 22, 2026, replaced per-batch firehose connections with one independent continuous collector and a local SQLite queue. Stream positions and incoming posts commit together. The processor acknowledges work only after successful analysis and saves; failed batches are redelivered, source URIs prevent replay duplication, and totals rebuild from the complete saved records. The existing transformer, disaster rules, location/relevance decisions, Jev thresholds, and request cap are unchanged. The Mac still runs the backend behind the Free Render gateway.

- **117 regression tests passed** in the full environment; the lightweight environment passed 78 and skipped 39 optional live checks. Coverage includes durable pending batches/cursors, continued collection during a held batch, replay deduplication, rollback when the queue is full, reconnect cursor selection, expired replay/oversized-commit warnings, model/Jev failures, failed writes, lost acknowledgements, fresh collector status, and duplicate port detection.
- An isolated **real-feed rehearsal** held a batch while collection continued, forced a disconnect, restarted the collector against the same disk queue, and verified unchanged pending delivery plus idempotent acknowledgement. Normal batch reads never reopened the stream. No known gaps were reported. No NLP/Jev calls or dashboard reports were created by this rehearsal.
- The **real-backend runtime check** passed real NLP through the database SDK and local HTTP test responses, all five data callbacks, database outage/recovery, stalled reads, process cleanup, and preservation of existing data.
- The live upgrade preserved **29 archived report records** and prior activity. Over 12 samples spanning about 22 seconds, the collector received **698 posts** and the consumer acknowledged **694**, with **one connection**, **zero reported gaps**, and no model/location/relevance errors. Pending work peaked at 68 posts with an oldest age of 2.1 seconds; the final sample had four posts pending, oldest 0.1 seconds. This is a short workload observation, not a throughput or completeness guarantee.
- The existing public Render URL passed live readiness, 11 browser assets, all six dashboard callbacks, and Jev activity. Its layout now reports a continuous connection, pending count, oldest waiting age, and known coverage gaps. Browser visual inspection remains unavailable; these are HTTP/data checks.
- A later public check showed 10,155 posts captured and 10,151 acknowledged, still on one connection with zero reported stream gaps. Temporary Jev failures had accumulated 40 relevance and 14 location retry errors; processing recovered and the queue drained back to four posts, oldest 0.1 seconds. Provider failures are therefore distinct from lost collection. Public queue read/acknowledgement routes returned 404.
- Upgrade startup exposed two old orphan processes holding local ports. They were stopped after report archival; queue recovery retained newly collected work. The launcher now rejects occupied ports before starting children, preventing readiness checks from mistaking a previous service for a new one.

The new queue starts coverage at its first stream position; it does not reconstruct posts missed by the former sampling implementation. Recovery depends on the provider replay window, and oversized commits or long outages can leave visible gaps. Pending storage is bounded to 100,000 posts without silent eviction. The unchanged Jev budget can pause analysis while incoming posts accumulate. See [continuous ingestion and operational limits](BACKEND.md#continuous-ingestion).

## Latency and Render gateway checkpoint

On September 22, 2026, the existing Free Render service was connected to the live Mac dashboard through its public tunnel. NLP, Jev, ingestion, and CSV storage remain on the Mac. The public gateway passed live readiness, all 11 browser assets, all six dashboard callbacks, Jev activity, and rejection of public model API calls. No paid instance was created.

The next performance update retains the original model, disaster patterns, location checks, Jev thresholds, and request cap. Collection now requests 20 posts with a two-second window; the processor pauses 0.1 seconds between batches, and the dashboard refreshes every two seconds. An exact surface-rule precheck skips heavy NLP only when the saved rules cannot match. Render forwarding reuses per-thread HTTP connections, clears cookies between requests, and uses four request threads.

- **102 regression tests passed** in the full environment. The lightweight Render environment passed 65 and skipped 37 optional live checks. Targeted lint and whitespace checks passed.
- The real-model gate comparison covered **138 authored case/plural probes across 46 saved rules plus 20 ordinary negative posts**, with **zero dropped original candidates**. Three gamma-ray-burst probes already failed in the original pipeline because of its existing text/rule behavior. On the 20 ordinary posts, median full NLP time was **29.165 ms**, versus **0.155 ms** for the gate. This is a bounded synthetic comparison, not general accuracy or whole-pipeline throughput.
- **6/6 real NLP → hosted gazetteer → Jev → processor examples passed** after the gate change. No evaluation posts were saved. Real backend runtime checks also passed callback behavior, database outage/recovery, stalled database reads, and child-process cleanup.
- The optimized live pipeline resumed all **16 archived reports** and existing counters without adding a duplicate startup example. In eight activity samples over 14 seconds, median collection time was **1,040.65 ms** and median reported processing time was **124.4 ms per batch**; 174 more posts were processed, with zero accumulated model, location-classifier, or relevance errors. These samples are workload-dependent and can repeat a completed stage's timing.
- The exact updated Render launcher passed a local forwarding rehearsal against the live tunnel: 11 assets, all six callbacks, live/Jev status, and a blocked model route. Before connection reuse, six sequential public activity requests had a warm median of **1,920.9 ms** through Render, versus **45.9 ms** directly through the tunnel; network latency is variable. Deployment verification should repeat `tests/check_render_gateway.py --url https://crisis-analysis-interview-demo.onrender.com`.

Collection remains sampled rather than continuous, so posts between windows can be missed. Jev interprets claims rather than verifying real events; passing authored examples does not establish 100% live accuracy. The Mac and tunnel must stay online. CSV history is temporary unless explicitly archived and restored with `--resume-from`. Earlier checkpoints below describe their own revisions, including the former fixture-only Render deployment.

## Jev location selection checkpoint

On September 22, 2026, added bounded choice classification for ambiguous US city names. The model service returns complete gazetteer candidate lists (up to 50 cities per mention); the processor asks Jev to choose a candidate or abstain, alongside an independent geographic-evidence question. Both scores must reach 0.9. Same-name places within the same state, truncated lists, and uncertain results remain unresolved. A chosen city still passes the separate crisis-relevance check; both steps share the existing 200-call cap. Names and coordinates come only from the database. Explicit unique matches retain the existing path, and no transformer/disaster-rule changes were made.

- **82 regression tests passed** in the full environment. The fixture environment passed 53 and skipped 29 optional live checks. New coverage includes complete candidate lists, shared caps/caches, malformed responses, abstention, same-state ambiguity, state-row folding, and preserving other resolved locations.
- **8/8 real Gateway location examples passed** with all 27 Portland gazetteer entries. Willamette River selected Oregon; Casco Bay selected Maine. Bare names, foreign places, unrelated author context, multiple places, and embedded instructions abstained. Reversed options still selected Oregon. Median call latency was 262.1 ms, maximum 413.1 ms. This is a small authored smoke test, not general accuracy.
- **6/6 combined real NLP → hosted gazetteer → Jev → processor examples passed**: the two contextual Portland cases and explicit Austin survived, while bare Portland, an Australian event, and a flood metaphor were excluded. No evaluation posts were saved to the dashboard.
- **Real backend runtime checks passed**, including all five data callbacks, explicit database outage/recovery, model-process failure cleanup, and a new stalled-database test. Live validation initially exposed a roughly 75-second readiness read that blocked the single model worker. Supabase network operations now time out after three seconds; the stalled-response test confirms prompt worker release and recovery. This is a per-operation bound, not a whole-batch deadline.
- The live Mac pipeline was restarted with both Jev stages enabled. Previous runs and their logs were archived locally outside Git before restart; counters start fresh with the labeled Austin example. The expired tunnel was replaced with a new temporary URL, saved locally in ignored `.demo-hosted/active-tunnel.json`.
- Public readiness, layout/CSS, all six dashboard callbacks, map sizing, and live collection passed after the final restart. At that check, 500 posts had been received and there were zero model, location-classifier, or relevance errors. Targeted lint and whitespace checks passed. Browser visual inspection remains unavailable because the browser security-policy check is blocked.

Run the bounded provider checks with `tests/check_jev_locations.py` and `tests/check_jev_location_pipeline.py --url http://127.0.0.1:5002`; see [Jev setup and limitations](JEV.md). Real collection remains Bluesky. At this checkpoint, Render still served the independent fixture demo; the later gateway checkpoint above supersedes that deployment state. Existing saved reports are not retroactively reclassified.

## US scope and relevance checkpoint

Only records with an explicit `US` country, a supported state (50 states or DC), and no failed/ambiguous location status are now retained. The same rule applies to saved posts, existing CSVs read by the dashboard, map circles, dropdowns, state totals, and statistics. Missing countries are never defaulted to US. Mixed-country posts keep their resolved US locations. This supersedes the older behavior below that displayed unresolved posts in the table.

The optional Jev screen uses Vercel AI Gateway to judge each candidate disaster/location pair for literal, current event relevance. It removes jokes, metaphors, fiction, historical discussion, negation, and unrelated location mentions when their score is below the provisional threshold. It evaluates a claim's meaning, not whether the event really happened. The original transformer and gazetteer still extract and resolve places. See [configuration, privacy, cost caps, and failure behavior](JEV.md).

Validation on September 22, 2026:

- **70 regression tests passed** in the full environment; the fixture environment passed 43 and skipped 27 optional live checks. Coverage includes all dashboard surfaces, mixed-country records, missing country data, Gateway request/response validation, timeouts, request caps, cache behavior, per-disaster filtering, and a fixture that remains offline even when Jev is configured.
- **8 real NLP + hosted gazetteer checks** passed through the new US filter, covering qualified US cities, foreign places, ambiguous Portland/Georgia, and mixed Japan/Austin text.
- **12/12 synthetic Jev examples passed** via the real Gateway key at threshold 0.8. Median end-to-end call latency was **333.8 ms**, maximum **1012.4 ms**. This small authored set is a smoke test, not an accuracy benchmark or a comparison against spaCy.
- **4 combined real pipeline examples passed**: the Austin flood survives; metaphorical pandemic, Pandemic board game, and Japan-only flood examples are excluded. No evaluation posts were injected into the live dashboard.
- The real live pipeline was restarted with Jev enabled and a **200-call cap per processor run**. The previous run was archived locally outside Git and the existing tunnel URL preserved. The new run starts fresh counters and a labeled synthetic Austin example.
- Public readiness, US-only copy, all six callbacks, Jev activity, relevance labels, and saved `US` records with passing scores were verified. At verification, 600 posts had been received; one live candidate had been screened out, with zero NLP or Jev errors. Targeted lint and whitespace checks passed. Visual browser rendering remains unverified because browser security-policy checking is unavailable.

API credentials remain in the ignored server `.env`; fixture deployments do not need them. Historical checkpoints below describe their own earlier revisions.

## Map sizing checkpoint

The owner chose report counts as the meaning of circle size. The previous map averaged cities together, measured their spread in latitude/longitude degrees, multiplied that distance by 50, and passed it to an automatically scaled pixel marker. State-only records used a separate arbitrary size. Those values did not measure report volume or a geographic disaster radius.

The map now reads one complete `filtered_posts.csv` snapshot and counts saved records per resolved location and first disaster label. Different cities keep their own coordinates. State-only records and city records lacking valid coordinates use a labeled approximate state centroid. Unresolved/foreign records are excluded. These are the same saved location-record units as the existing aggregates, including possible cross-batch repeats; no unique-incident count is claimed.

Display diameter is `8 × sqrt(min(record_count, 64))` pixels, with Plotly explicitly using diameter mode and scale factor 1. Circle area is therefore proportional to count through 64 records, and other markers never rescale an existing point. Above 64 records the display remains 64 px, the hover explanation states that the size is capped, and the exact count is retained. A visible 1/4/16 size key and a note distinguish report volume from affected area. The [Plotly marker reference](https://plotly.com/python/reference/scattergeo/#scattergeo-marker-size) documents pixel marker sizing; these are display symbols, not geodesic circles.

All **54 regression tests passed** in the live environment. The fixture environment passed 27 and skipped 27 optional live checks. Nine new tests cover area ratios, separate city positions, invariance under distant/high-count outliers, shared scaling across disaster types and state-level records, truthful capping with exact counts, coordinate validation/fallback, exclusion of unresolved places, and compatibility with the existing first-disaster counting convention. Targeted lint, whitespace, and the UI mechanical scan passed.

Only the dashboard worker was reloaded; the model, collector, current CSV directory, and tunnel remained in place. Public HTTPS checks passed all six callbacks, updated layout/size-key CSS, live readiness, and each returned map point's diameter against its actual hover count. Visual browser rendering remains unverified because the admin security-policy check is unavailable.

## Location resolution checkpoint

The latest refinement replaces population-based guesses with conservative unique matching. Earlier checkpoints below describe previous revisions, including the old two-record Austin/Texas result; the current result is **one resolved location**.

- Exact city names require a single gazetteer match within the available state context. Multiple matches stay unresolved and carry no map coordinates. Exact aliases also require uniqueness; a truncated candidate search cannot claim a unique result.
- Match explanations travel through the model API and CSVs into the post table. They describe the evidence (city/state pair, one state in the post, unique US name/alias, or state mention), not numerical confidence. Unresolved mentions remain readable, including when another location in the same post resolves.
- A city and its supporting state produce one record. Standalone states and different cities/states remain separate. Counts still represent resolved locations, not verified incidents or globally unique posts.
- Bare “Georgia” requires more context. A resolved US city paired with Georgia, an explicit US reference, or the state abbreviation can establish the US interpretation. This remains a text heuristic and does not understand every geographic or semantic ambiguity.

Validation on September 22, 2026: **45 regression tests passed**, including 24 resolver tests and a CSV/dashboard test proving ambiguous Portland stays visible but is excluded from map/count data. The fixture-only environment passed 18 tests and skipped 27 optional live checks. Both real-model integration checks passed; the injector produces one Austin/Texas/Flood record, and runtime coverage includes dashboard callbacks, database outage/recovery, and child-process cleanup.

The running real model plus hosted Supabase passed **19 extraction examples**, including unqualified Portland/Springfield/Austin/Georgia remaining ambiguous, qualified cities resolving, Georgia/USA and Atlanta/Georgia resolving, foreign examples staying unresolved, and standalone states remaining supported. Run `python tests/check_location_pipeline.py --url http://127.0.0.1:5002` to repeat them without publishing test posts.

The live service was restarted with old CSVs archived outside Git and the existing tunnel preserved. Public HTTPS checks passed readiness, activity, all six callbacks, the single startup row, and its matching explanation. Lint, whitespace, and the UI mechanical scan passed. Visual browser verification remains blocked by the unavailable admin security-policy check.

Tradeoff: more vague posts remain unresolved, reducing map coverage. Uniqueness means unique within the restored US database, not globally unique or necessarily the intended place. County coverage, historical aliases, negation, and the relationship between an incident and a mentioned place remain limitations. The original NLP weights, disaster rules, sentiment, and HTTP/CSV architecture are unchanged; no new service or subscription is introduced.

## Audit findings addressed

| Finding | Change |
| --- | --- |
| README was a sequence of outdated Docker notes | Replaced with problem, audience, architecture, stack, demo, model build, live setup, ports, and limitations |
| Logs, backups, macOS files, bytecode, notebook checkpoints/trash, and collected CSVs were committed | Removed generated files and added ignore rules; retained datasets and notebook source |
| Notebook stored old execution output | Cleared output and execution counts |
| Unsafe CSV parsing used `eval()` | Uses `ast.literal_eval()` with list/string validation |
| Injector restored `entry.scrape_posts` after patching `entry.get_scraped_posts` | Context-managed patch restores the exact function even on failure |
| Injector could read stale rows and overwrite live files | Isolated temporary output; explicit export only after validation; nonzero exit on failure |
| Scripts used inconsistent working-directory paths | Model and default CSV paths are relative to source files; dashboard accepts an explicit data directory |
| Imported NLP model loaded unnecessarily in the processor and twice in the model server | Removed unused processor import and share a cached model loader |
| Basic English fallback could not provide disaster labels/sentiment | Missing custom model is reported explicitly; extraction returns HTTP 503 |
| Custom model folder was missing and model construction lived only in a notebook | Added `build_disaster_model.py`, retaining the original 46 patterns and pipeline ordering |
| Shared mutable list default, duplicate imports/conditions, profanity, debug dumps | Targeted cleanup of Python service code |
| One-row severity calculation produced NaN | Uses a finite zero result for a single/equal-count group |
| Docker exposed ports that were not the dashboard port | Publishes documented dashboard port 8051; internal APIs remain 5000/5001 |
| Several directly imported runtime dependencies were implicit | Declared Flask, requests, Plotly, python-dotenv, and psutil; added a small fixture-demo requirements file |

## Checks run

Environment: macOS ARM64, isolated Python 3.12.14. NLP: spaCy 3.8.4, `en_core_web_trf` 3.8.0, spaCyTextBlob 5.0.0. Validation performed September 22, 2026.

| Check | Result |
| --- | --- |
| Full `requirements.txt` installation | Passed |
| `python -m pip check` | Passed; no broken requirements |
| Build using `python build_disaster_model.py` | Passed; saved 46 patterns to `proj-dev/app/disaster_ner` |
| `python tests/check_disaster_model.py` | Passed with the actual saved transformer pipeline |
| `python tests/check_model_pipeline.py` | Passed: actual NLP, actual model HTTP endpoint, controlled Supabase query responses, actual CSV processing; missing-model HTTP 503 also verified |
| `python -m unittest discover -s tests -v` | Seven regression tests passed in the full environment and in a separate environment containing only `requirements-demo.txt` |
| Repeated fixture runs | Identical CSV bytes, one Austin/Texas/Flood record, count 1, severity 0 |
| Dashboard callbacks | Texas dropdown, Flood map data, count chart, original post text, and statistics verified |
| Dashboard Flask routes | `/` and `/_dash-layout` return HTTP 200 |
| Python syntax parsing | Passed for the remaining tracked Python files and new scripts/tests |
| Targeted Ruff checks | Passed: unused/redefined imports, duplicate dictionary keys, undefined names, syntax, mutable defaults |
| `git diff --check` | Passed |

Real NLP output for `Flood in Austin Texas.`:

```text
('Flood', 'DISASTER', 'Flood')
('Austin', 'GPE', '')
('Texas', 'GPE', '')
sentiment: Neutral; polarity: 0.0
```

The base model recognizes **Austin and Texas separately**. Joining them into one entity would change the existing behavior, so the implementation preserves both. With both location lookups supplied by the integration test, the existing aggregator counts two location records from the one post. The fixture demo uses a single predefined Austin record, is labeled as such, and does not measure NLP accuracy.

The existing notebook-building cell was preserved as the reference. The script uses the same base model, synonym iteration, lowercased token lemmas, regex expression `(?i)^{lemma}s?$`, canonical labels, EntityRuler placement, and sentiment component. Build errors are allowed to stop the script rather than silently saving an incomplete model.

## Remaining setup requirements and unverified areas

- **Fixture demo:** works without the custom model, Supabase, or Bluesky after installing Python 3.12 and `requirements-demo.txt`. Initial dependency installation needs internet access.
- **Real NLP on a fresh clone:** download `en_core_web_trf` and run the new model builder. Generated model weights are intentionally excluded from Git. The model was built locally during this cleanup.
- **Real location enrichment:** the original cloud project is paused beyond its recovery window. Its backup was restored into local and new Free hosted Supabase projects; real API lookups and the NLP/dashboard path passed. A fresh clone still needs private credentials; see the recovery sections below.
- **Continuous Bluesky ingestion:** live collection through the hosted gazetteer passed a bounded rehearsal, including corrected record-to-operation mapping. Collection samples batches and can miss posts; this is not a long-term reliability or accuracy benchmark. See the live-collection section below.
- **Application Docker image:** not built/run during validation. The Dockerfile and documented paths/ports were inspected. Isolated PostgreSQL and local Supabase containers were subsequently used successfully for database recovery testing.
- **Visual browser inspection:** blocked because the browser tool could not verify its admin-enforced security policy. No screenshot or visual end-to-end validation is claimed. The geographic basemap may depend on externally served Plotly assets.
- **Legacy scripts:** `proj-dev/app/main.py` references modules no longer next to it; `live_demo/scraper_server.py` imports absent `blueskyapi_copy`. These are documented as unsupported experiments and excluded from the demo instructions.

## Deliberately deferred

Cross-batch deduplication, counting unique posts rather than location rows, weighted sentiment aggregation, changes to disaster taxonomy, comprehensive location disambiguation, transactional storage, authentication, production orchestration, and a full dependency lockfile. These would expand behavior or architecture beyond the requested interview cleanup.

## Render deployment preparation

Added a native Python Render Blueprint (`render.yaml`) using the Free plan, a minimal hosted-demo dependency file, Python 3.12 selection, and `scripts/start_demo.sh`. This publishes only the labeled fixture dashboard. Automatic deployment is disabled.

The exact startup script was exercised from a temporary clean checkout with no NLP weights or Supabase credentials, using the minimal hosted-demo environment. Two fresh starts on assigned test ports returned HTTP 200 for the page and Dash layout, exposed the fixture label, returned the Texas dropdown through an actual Dash callback request, and regenerated byte-identical CSVs after deleting the prior demo directory. A pre-existing live-data directory setting was not used or modified. The first measured server process tree used approximately 126 MiB locally; this is not a measurement of Render's runtime. Shell syntax, YAML parsing, and whitespace checks passed.

The user completed Render provisioning. Public deployment: **https://crisis-analysis-interview-demo.onrender.com**. On September 22, 2026, HTTPS checks returned HTTP 200 for the public page, Dash layout, and all five dashboard callbacks. Verified the explicit fixture label, Texas dropdown, Flood map/chart data with count 1, original synthetic post, and statistics showing one report, one disaster type, one state, one city, and average sentiment 0.00. These checks exercised the deployed service, not a local substitute.

Visual browser inspection remains unverified because the browser tool could not verify its admin-enforced security policy. The public callback checks validate returned data, not browser rendering or geographic asset availability. The Render Free instance can sleep when idle; warm it up before presenting. Automatic deployments are disabled, so documentation-only pushes do not restart the running service.

## Real backend connection preparation

Added `requirements-live.txt`, `scripts/build_live.sh`, `scripts/run_pipeline.py`, the separate optional paid `render-live.yaml`, and [backend setup instructions](BACKEND.md). The existing Free Blueprint is unchanged. The launcher keeps the original services on one host, checks Supabase/table readiness, runs the known post through real NLP, and starts the dashboard only after usable Austin/Texas/Flood data exists. Optional live mode also starts the original collector and processor.

The transformer process alone measured approximately 2,633 MiB RSS locally after inference. This exceeds the Free 512 MB and 2 GB instances; the optional Blueprint selects 4 GB. This measurement does not guarantee Linux resource use or sustained feed throughput. The Linux CPU-only PyTorch 2.14.0 wheel was confirmed available in the official PyTorch index; the Linux build has not been executed here.

`tests/check_backend_runtime.py` passed using the actual saved NLP model, actual Waitress model service, actual Supabase Python client communicating with a controlled local HTTP gazetteer, actual CSV processing, and a Gunicorn dashboard. All five Dash callbacks returned the expected Texas/Flood/post/statistics data. A simulated database outage returned HTTP 503 from public readiness; recovery restored HTTP 200. Terminating the model process caused the supervisor to exit nonzero and shut down the dashboard. Existing local data was preserved. This test does not connect to the user's Supabase project.

The original seven regression tests still pass in the minimal demo environment. Shell syntax, Blueprint YAML parsing, dependency consistency in the working model environment, and targeted lint checks passed. At this preparation stage, real Supabase access was outstanding; the completed hosted recovery below resolves that blocker. Real paid Render provisioning and sustained live processing remain unverified. No paid service was created.

A separate clean Python 3.12 environment installed only the declared live runtime dependencies, PyTorch 2.14.0, and `en_core_web_trf` 3.8.0. The original model builder, complete backend runtime check, and seven regression tests all passed there, with no notebook packages required. Dependency consistency passed for all 110 installed packages. A separate check confirmed that a fixture marker takes precedence over a conflicting environment mode, so fixture data cannot be labeled as real NLP. Native Linux/Render execution is still unverified.

## Recovery from the original database backup

The supplied plain-text PostgreSQL 15 backup contains 2,241,204 gazetteer rows. The new extraction script prepared 193,736 unchanged `PPL%`/`ADM1` records, covering every feature type queried by the supported model server. It excludes other schemas, role definitions, and secrets. Original and extracted database data remain outside Git. Selected COPY data checksum: `f2b4ab9f138c64c8adcf7774889bda8513806f3e4d4b38963d10e8fb4f0f47b4`.

An isolated PostgreSQL 16 restore passed: 193,736 rows, 38 MB with indexes, primary key enforced, backend SELECT access, no anonymous SELECT or backend INSERT grants. Repeating the restore failed on the existing table and preserved all rows. Four extraction regression tests cover scope/escaping, exclusion of unrelated SQL, full-feature mode, overwrite protection, and malformed/truncated input cleanup; all eleven regression tests pass.

The real records exposed a deterministic-demo blocker: several places share the name Austin, while the existing exact-name query used `LIMIT 1` without ordering. It now prefers highest population and then GeoNames ID, following the existing fallback's population heuristic. It resolves Austin to Texas (ID 4671654); the state is ID 4736286. NLP behavior is unchanged. Context-aware location disambiguation remains deferred.

The same restore was loaded into a separate local Supabase project (`crisis-analysis-rehearsal`, PostgreSQL 17). The actual Supabase REST API returned the full restored count and correct Austin/Texas lookups. The unmodified NLP pipeline processed the known synthetic post against this database, produced two location rows, and passed public readiness plus all five dashboard callbacks at `http://localhost:8052`. This check uses the recovered database, not mocked database responses. Local API credentials are stored only in ignored owner-readable files.

## Hosted Supabase verification

After explicit organization and $0/month cost confirmation, the Supabase connector created **crisis-analysis** (`zhsnegbrxgdthfdcblpn`) in **nikitab724's Org**, region `us-east-2`. The recovered 193,736 rows were imported using authenticated server-side API batches. No old project or unrelated project was modified.

The hosted and local databases have the same complete-table fingerprint: `a253760600912226de1dee9f3e9c9fc1` (MD5 over concatenated, GeoNames-ID-ordered MD5 hashes of PostgreSQL row JSON). Austin resolves to ID 4671654, TX; Texas resolves to ID 4736286. Hosted table/index storage is 40 MB and the total database measured 51 MB after import.

Temporary import write access was revoked. SQL checks confirm `service_role` has SELECT but no INSERT/UPDATE/DELETE; `anon` and `authenticated` have none of those privileges. RLS is enabled. Supabase's security advisor reports only the informational [RLS without policies notice](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy), which is intentional for this server-only table: no browser access is permitted. The performance advisor initially reported an [unused state index](https://supabase.com/docs/guides/database/database-linter?lint=0005_unused_index) on the newly restored table; the index supports the app's state lookup and is retained.

The local launcher at **http://localhost:8052** now uses private hosted credentials. The real transformer processed **“Flood in Austin Texas.”** against the hosted Supabase API, produced two extracted location records, and passed `/health`, the real-backend dashboard label, and all five Dash callbacks (Texas dropdown, Flood map, Flood count chart, original post table, and statistics). This check used the actual hosted data and access settings, not substituted database responses. Local database credentials remain available separately for fallback rehearsal.

No paid Render service was created. The original public Render URL still serves the Free fixture demo. Cloud restore steps, local restart/stop commands, and remaining limits are in [GAZETTEER_RESTORE.md](GAZETTEER_RESTORE.md). Browser rendering, native Linux/Render execution of the transformer, and sustained live-feed behavior remain unverified.

## Temporary public access to the real backend

The working Mac dashboard was exposed through a free Cloudflare Quick Tunnel on September 22, 2026. HTTPS checks passed for `/`, `/_dash-layout`, `/health`, the real-backend label, and all five dashboard callbacks. The known post and two extracted location records matched the local results. An independent request from the existing remote server also returned healthy readiness through the public URL.

The remote server had only about 1.4 GB available out of 4 GB RAM. At the owner's request, its Firecrawl services remained running and no application was deployed there. The tunnel forwards only the Mac's dashboard on port 8052; the model API remains local and uses the hosted Supabase database. macOS idle sleep is prevented for the tunnel's lifetime. The generated URL is temporary and intentionally not committed as a stable deployment address. This validates HTTP behavior and returned data, not visual browser rendering.

## Live collection and dashboard polish

The Mac pipeline was switched to live Bluesky collection on September 22, 2026, using the original transformer, rules, sentiment analysis, Supabase lookup, and HTTP/CSV service boundaries. A sustained run received more than 3,400 posts and produced 13 new matching location records at the initial checkpoint, with no model request errors. These were real incoming posts, separate from the startup example. The collector samples batches rather than providing guaranteed coverage of every post.

The collector now reads the CAR record identified by each operation's CID, so text and source URI stay associated correctly. Author resolution is bounded to two seconds, collection to forty seconds, and completed partial batches are retained. Individual CSV replacements and activity snapshots are atomic; there is still no transaction spanning both CSV files.

The dashboard now uses a restrained responsive layout, consistent chart colors, an activity row, all-state browsing by default, newest-first results limited to 30 records, links to original Bluesky posts, and explicit example labels. The summary calls its count **Location records**. Delayed activity and collection errors are visible; stale live activity also fails readiness. A macOS Gunicorn reload crash in system proxy discovery was fixed by using direct local HTTP for the private model readiness check.

All 20 regression tests passed in the live environment; the minimal fixture environment passed 17 and skipped the three optional collector checks. Coverage includes operation/record association, partial batches, input bounds, activity when no posts match, model request errors, collector outage/recovery, stale readiness, preserving the previous CSV when a write fails, and newest-first ordering across mixed timestamp formats. The real-model runtime integration also passed startup, all original five dashboard callbacks, database outage/recovery, process-failure cleanup, and preservation of existing data. Lint, syntax/whitespace checks, and the UI skill's mechanical scan passed.

The final public HTTPS verification passed live readiness, `/activity`, the updated layout and CSS, all six callbacks including activity, Bluesky source links, and saved live records. At that checkpoint, 5,800 posts had been received, 5,526 successfully analyzed after filtering duplicates/empty text, and 23 matching records saved, with zero model request errors. This is a bounded rehearsal observation, not a throughput or accuracy benchmark.

Visual inspection remains unavailable: the browser tool's admin-enforced security-policy check could not be verified. No alternate browser was used to bypass it. HTTP callback checks do not establish screenshot quality, responsive rendering, or keyboard behavior in a real browser.

## Location matching and a quieter dashboard

Live results exposed Perryville, Alaska being assigned to Missouri, country mentions such as Japan being assigned to US towns, substring aliases producing unrelated places, and repeated lowercase hashtags adding location rows. The resolver now uses adjacent city/state pairs (including uppercase state abbreviations), a single extracted state when appropriate, case-insensitive exact city names, and whole aliases parsed from the restored column. State constraints are included in the lookup cache key. A recognized foreign-country or Canadian-province context suppresses unqualified US guesses; explicitly qualified US namesakes such as Mexico, Missouri still resolve. Repeated canonical locations within a post are collapsed. This changes location postprocessing only: transformer weights, entities, disaster patterns, sentiment, HTTP services, and CSV storage remain unchanged.

The dashboard has a white canvas, lighter dividers, fewer repeated notes, and a four-column post table with source links beside the time. Essential live/fixture and example disclosures remain visible; implementation details are under **About the data**.

- All **35 regression tests** passed in the live environment, including 15 location tests. The fixture-only environment passed 17 and skipped 18 optional live checks.
- The real-model runtime check passed startup, dashboard callbacks, database outage/recovery, child-process failure cleanup, and preservation of existing files.
- **12 real model API + hosted gazetteer examples** passed: Austin/Texas, Perryville/Alaska with repeated hashtags, Portland/Maine, Portland/Oregon, Paris/Texas, Mexico/Missouri, McAllen/Texas, New Mexico, West Virginia, and unresolved Japan, Mexico-coast, and Hamilton/Ontario/Canada examples.
- Run the same read-only extraction checks with `python tests/check_location_pipeline.py --url http://127.0.0.1:5002` after starting the real service. These checks send synthetic texts to the private model API and do not publish them to the dashboard or write to the database.
- The live pipeline was restarted with the new resolver; the previous CSVs and activity were archived locally outside Git. The existing tunnel stayed running, retaining its public address. New collection starts from the labeled Austin example.
- Public HTTPS readiness, updated layout/CSS, four-column table, and all six Dash callbacks passed. At that checkpoint the restarted collector had received 500 posts and analyzed 482, with zero model request errors.
- Targeted lint, whitespace, dependency consistency (111 packages), and the UI mechanical scan passed. Visual browser verification remains blocked by the same unavailable security-policy check.

Limits: unqualified city names still use population ordering, and the country/state ambiguity of Georgia is not solved. Foreign locations remain unresolved, not internationally geocoded. Alias search checks at most 25 population-ranked candidates and can miss less prominent aliases. Counties, indirect references, and absent country/state context remain unreliable. The original disaster rules also missed “Flooding” in one test sentence; the location-only comparison uses “Flood” to exercise the resolver without changing those rules. These examples establish regression behavior, not measured extraction accuracy.
