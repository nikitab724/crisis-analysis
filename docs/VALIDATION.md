# Cleanup audit and validation

Scope: interview preparation, reproducible model build, and one dependable demo path. The existing service boundaries, transformer, disaster rules, sentiment approach, and CSV architecture are retained.

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
- **Real location enrichment:** the original cloud project is paused beyond its recovery window. Its downloaded backup has now been restored into a separate local Supabase project, and actual API lookups plus the NLP/dashboard path passed. A new hosted project, cloud credentials, and hosted connectivity remain outstanding; see the recovery section below.
- **Continuous Bluesky ingestion:** a bounded read-only smoke check collected five real public posts with the expected pipeline fields. Sustained ingestion through the real database is unverified. The legacy firehose record-to-operation matching deserves a separate review before production use; requests now run serially to avoid concurrent use of its shared event loop.
- **Application Docker image:** not built/run during validation. The Dockerfile and documented paths/ports were inspected. Isolated PostgreSQL and local Supabase containers were subsequently used successfully for database recovery testing.
- **Visual browser inspection:** blocked because the browser tool could not verify its admin-enforced security policy. No screenshot or visual end-to-end validation is claimed. The geographic basemap may depend on externally served Plotly assets.
- **Legacy scripts:** `proj-dev/app/main.py` references modules no longer next to it; `live_demo/scraper_server.py` imports absent `blueskyapi_copy`. These are documented as unsupported experiments and excluded from the demo instructions.

## Deliberately deferred

Cross-batch deduplication, counting unique posts rather than location rows, weighted sentiment aggregation, changes to disaster taxonomy, location disambiguation, firehose record mapping, transactional storage, authentication, production orchestration, and a full dependency lockfile. These would expand behavior or architecture beyond the requested interview cleanup.

## Render deployment preparation

Added a native Python Render Blueprint (`render.yaml`) using the Free plan, a minimal hosted-demo dependency file, Python 3.12 selection, and `scripts/start_demo.sh`. This publishes only the labeled fixture dashboard. Automatic deployment is disabled.

The exact startup script was exercised from a temporary clean checkout with no NLP weights or Supabase credentials, using the minimal hosted-demo environment. Two fresh starts on assigned test ports returned HTTP 200 for the page and Dash layout, exposed the fixture label, returned the Texas dropdown through an actual Dash callback request, and regenerated byte-identical CSVs after deleting the prior demo directory. A pre-existing live-data directory setting was not used or modified. The first measured server process tree used approximately 126 MiB locally; this is not a measurement of Render's runtime. Shell syntax, YAML parsing, and whitespace checks passed.

The user completed Render provisioning. Public deployment: **https://crisis-analysis-interview-demo.onrender.com**. On September 22, 2026, HTTPS checks returned HTTP 200 for the public page, Dash layout, and all five dashboard callbacks. Verified the explicit fixture label, Texas dropdown, Flood map/chart data with count 1, original synthetic post, and statistics showing one report, one disaster type, one state, one city, and average sentiment 0.00. These checks exercised the deployed service, not a local substitute.

Visual browser inspection remains unverified because the browser tool could not verify its admin-enforced security policy. The public callback checks validate returned data, not browser rendering or geographic asset availability. The Render Free instance can sleep when idle; warm it up before presenting. Automatic deployments are disabled, so documentation-only pushes do not restart the running service.

## Real backend connection preparation

Added `requirements-live.txt`, `scripts/build_live.sh`, `scripts/run_pipeline.py`, the separate optional paid `render-live.yaml`, and [backend setup instructions](BACKEND.md). The existing Free Blueprint is unchanged. The launcher keeps the original services on one host, checks Supabase/table readiness, runs the known post through real NLP, and starts the dashboard only after usable Austin/Texas/Flood data exists. Optional live mode also starts the original collector and processor.

The transformer process alone measured approximately 2,633 MiB RSS locally after inference. This exceeds the Free 512 MB and 2 GB instances; the optional Blueprint selects 4 GB. This measurement does not guarantee Linux resource use or sustained feed throughput. The Linux CPU-only PyTorch 2.14.0 wheel was confirmed available in the official PyTorch index; the Linux build has not been executed here.

`tests/check_backend_runtime.py` passed using the actual saved NLP model, actual Waitress model service, actual Supabase Python client communicating with a controlled local HTTP gazetteer, actual CSV processing, and a Gunicorn dashboard. All five Dash callbacks returned the expected Texas/Flood/post/statistics data. A simulated database outage returned HTTP 503 from public readiness; recovery restored HTTP 200. Terminating the model process caused the supervisor to exit nonzero and shut down the dashboard. Existing local data was preserved. This test does not connect to the user's Supabase project.

The original seven regression tests still pass in the minimal demo environment. Shell syntax, Blueprint YAML parsing, dependency consistency in the working model environment, and targeted lint checks passed. Real paid Render provisioning, actual Supabase credentials/policies/data, and sustained live processing remain outstanding. No paid service was created during preparation.

A separate clean Python 3.12 environment installed only the declared live runtime dependencies, PyTorch 2.14.0, and `en_core_web_trf` 3.8.0. The original model builder, complete backend runtime check, and seven regression tests all passed there, with no notebook packages required. Dependency consistency passed for all 110 installed packages. A separate check confirmed that a fixture marker takes precedence over a conflicting environment mode, so fixture data cannot be labeled as real NLP. Native Linux/Render execution is still unverified.

## Recovery from the original database backup

The supplied plain-text PostgreSQL 15 backup contains 2,241,204 gazetteer rows. The new extraction script prepared 193,736 unchanged `PPL%`/`ADM1` records, covering every feature type queried by the supported model server. It excludes other schemas, role definitions, and secrets. Original and extracted database data remain outside Git. Selected COPY data checksum: `f2b4ab9f138c64c8adcf7774889bda8513806f3e4d4b38963d10e8fb4f0f47b4`.

An isolated PostgreSQL 16 restore passed: 193,736 rows, 38 MB with indexes, primary key enforced, backend SELECT access, no anonymous SELECT or backend INSERT grants. Repeating the restore failed on the existing table and preserved all rows. Four extraction regression tests cover scope/escaping, exclusion of unrelated SQL, full-feature mode, overwrite protection, and malformed/truncated input cleanup; all eleven regression tests pass.

The real records exposed a deterministic-demo blocker: several places share the name Austin, while the existing exact-name query used `LIMIT 1` without ordering. It now prefers highest population and then GeoNames ID, following the existing fallback's population heuristic. It resolves Austin to Texas (ID 4671654); the state is ID 4736286. NLP behavior is unchanged. Context-aware location disambiguation remains deferred.

The same restore was loaded into a separate local Supabase project (`crisis-analysis-rehearsal`, PostgreSQL 17). The actual Supabase REST API returned the full restored count and correct Austin/Texas lookups. The unmodified NLP pipeline processed the known synthetic post against this database, produced two location rows, and passed public readiness plus all five dashboard callbacks at `http://localhost:8052`. This check uses the recovered database, not mocked database responses. Local API credentials are stored only in ignored owner-readable files.

No hosted Supabase or paid Render resource was created. Browser account setup remains blocked by an unavailable admin-enforced security-policy check. The original public Render URL still serves the Free fixture demo. Cloud restore steps, local restart/stop commands, and limitations are in [GAZETTEER_RESTORE.md](GAZETTEER_RESTORE.md).
