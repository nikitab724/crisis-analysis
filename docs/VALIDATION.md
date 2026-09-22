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
- **Real location enrichment:** requires valid Supabase credentials and a populated, readable `gazetteer` table. Neither was available, so real database connectivity and data coverage remain unverified. Required columns are documented in the README.
- **Continuous Bluesky ingestion:** requires external network access. Import compatibility was checked; live collection was not exercised. The legacy firehose record-to-operation matching and concurrent request behavior deserve a separate review before production use.
- **Docker execution:** not run because the Docker daemon was stopped. Dockerfile and documented paths/ports were inspected for consistency; no successful image build is claimed.
- **Visual browser inspection:** blocked because the browser tool could not verify its admin-enforced security policy. No screenshot or visual end-to-end validation is claimed. The geographic basemap may depend on externally served Plotly assets.
- **Legacy scripts:** `proj-dev/app/main.py` references modules no longer next to it; `live_demo/scraper_server.py` imports absent `blueskyapi_copy`. These are documented as unsupported experiments and excluded from the demo instructions.

## Deliberately deferred

Cross-batch deduplication, counting unique posts rather than location rows, weighted sentiment aggregation, changes to disaster taxonomy, location disambiguation, firehose record mapping, transactional storage, authentication, service orchestration, and a full dependency lockfile. These would expand behavior or architecture beyond the requested interview cleanup.

## Render deployment preparation

Added a native Python Render Blueprint (`render.yaml`) using the Free plan, a minimal hosted-demo dependency file, Python 3.12 selection, and `scripts/start_demo.sh`. This publishes only the labeled fixture dashboard. Automatic deployment is disabled.

The exact startup script was exercised from a temporary clean checkout with no NLP weights or Supabase credentials, using the minimal hosted-demo environment. Two fresh starts on assigned test ports returned HTTP 200 for the page and Dash layout, exposed the fixture label, returned the Texas dropdown through an actual Dash callback request, and regenerated byte-identical CSVs after deleting the prior demo directory. A pre-existing live-data directory setting was not used or modified. The first measured server process tree used approximately 126 MiB locally; this is not a measurement of Render's runtime. Shell syntax, YAML parsing, and whitespace checks passed.

The user completed Render provisioning. Public deployment: **https://crisis-analysis-interview-demo.onrender.com**. On September 22, 2026, HTTPS checks returned HTTP 200 for the public page, Dash layout, and all five dashboard callbacks. Verified the explicit fixture label, Texas dropdown, Flood map/chart data with count 1, original synthetic post, and statistics showing one report, one disaster type, one state, one city, and average sentiment 0.00. These checks exercised the deployed service, not a local substitute.

Visual browser inspection remains unverified because the browser tool could not verify its admin-enforced security policy. The public callback checks validate returned data, not browser rendering or geographic asset availability. The Render Free instance can sleep when idle; warm it up before presenting. Automatic deployments are disabled, so documentation-only pushes do not restart the running service.
