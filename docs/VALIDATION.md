# Cleanup audit and validation

Scope: interview preparation, reproducible model build, and one dependable demo path. The existing service boundaries, transformer, disaster rules, sentiment approach, and CSV architecture are retained.

## Current location behavior and validation

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
