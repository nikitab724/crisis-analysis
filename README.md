# Crisis Analysis

A college prototype that turns public social posts into a geographic view of potential crisis reports.

## The problem

Social feeds can contain early reports of floods, wildfires, and other emergencies, but relevant posts are mixed with unrelated discussion. Manually finding disaster mentions, locating them, and grouping reports takes time.

## What the app does

Crisis Analysis collects posts from the Bluesky firehose, identifies disaster and location mentions, estimates text sentiment, and resolves locations using a Supabase gazetteer. It groups results by U.S. state and disaster type, then displays a map, report counts, and the underlying posts in a Dash dashboard.

The intended users are analysts and operations teams exploring social-media situational awareness. This project demonstrates an analysis workflow; it does not verify incidents or provide emergency alerts.

## Architecture

```mermaid
flowchart LR
    B[Bluesky firehose] --> S[Firehose service · 5001]
    S --> E[Batch processor · entry.py]
    E --> M[Model service · 5000]
    M --> N[spaCy transformer + disaster rules + sentiment]
    M --> G[Supabase gazetteer]
    M --> E
    E --> C[Local CSV files]
    C --> D[Dash dashboard · 8051]
```

The processes run on one host (or in one development container). The model service and scraper communicate with the processor over local HTTP. The dashboard reads CSV files on a five-second refresh interval. This cleanup retains those boundaries and the existing NLP approach.

## Tech stack

| Layer | Implementation |
| --- | --- |
| Runtime | Python 3.12 |
| Ingestion | Bluesky AT Protocol client, Flask |
| NLP | spaCy 3.8.4, `en_core_web_trf`, EntityRuler disaster patterns |
| Sentiment | spaCyTextBlob / TextBlob polarity |
| Location lookup | Supabase/PostgreSQL gazetteer |
| Processing/storage | pandas, local CSV files |
| Dashboard | Dash 2.18.2, Plotly |
| Serving/development | Waitress, Gunicorn, Docker, Jupyter |

The disaster pipeline is assembled from a pretrained English transformer and the rules in `proj-dev/data/disasters/disaster_types.json`. It is not a disaster classifier trained from scratch.

## Run the deterministic demo

This is the shortest rehearsal path. It injects a synthetic post, **“Flood in Austin Texas.”**, and replays a predefined model response over local HTTP. The real processor performs filtering, CSV writing, and aggregation; the real dashboard displays the results. **Fixture mode does not run NLP or query Supabase.** It is labeled in both the terminal and dashboard.

From the repository root, with Python 3.12 installed:

```sh
git clone https://github.com/nikitab724/crisis-analysis.git
cd crisis-analysis
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-demo.txt
python proj-dev/app/live_demo/process_test_tweet.py --fixture --output-dir .demo
CRISIS_DATA_DIR="$PWD/.demo" python proj-dev/app/live_demo/dash_client.py
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` and set `$env:CRISIS_DATA_DIR = "$PWD/.demo"` before running the dashboard command.

Open **http://localhost:8051**. Expect one Flood report in Texas, an Austin marker, and the synthetic post after selecting Texas in the dropdown. Repeating the injection replaces the two demo CSVs with the same result. Without `--output-dir`, the script validates temporary results and removes them on exit. Live CSVs are preserved. Stop the dashboard with Ctrl+C.

The browser's geographic basemap may require internet access to Plotly's geographic assets. Rehearse on the presentation network beforehand; the table and bar chart do not depend on the map download.

## Deploy the interview demo to Render

[Deploy the fixture demo to Render](https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2Fnikitab724%2Fcrisis-analysis%2Ftree%2Fpolish%2Finterview-demo)

Sign in to Render, follow the link, and create the Blueprint from the `polish/interview-demo` branch. Review that the service uses the **Free** instance plan, then deploy it. The repository's `render.yaml` provides the settings:

| Setting | Value |
| --- | --- |
| Runtime | Python 3.12, via `.python-version` |
| Build command | `pip install -r requirements-hosted-demo.txt` |
| Start command | `bash scripts/start_demo.sh` |
| Health check | `/_dash-layout` |
| Instance plan | Free |

The launcher regenerates the synthetic demo data at each start and runs one Gunicorn worker on the host's `PORT`. It requires no secrets, model weights, Supabase, or Bluesky access. The public dashboard explicitly labels its data as a fixture. It does not expose the model or ingestion APIs. Automatic deployments are disabled so a later push cannot interrupt interview rehearsal; redeploy manually when ready.

Render supplies the public `onrender.com` address after the service becomes live. Open that address and verify the fixture label, Texas map/chart, and post table. [Free instances sleep after 15 minutes without traffic](https://render.com/docs/free) and can take about a minute to wake. Open the page before your interview and keep the local demo available as a backup. No paid resources are defined by this Blueprint.

To rehearse the same server startup locally (stop any other app using port 8051 first):

```sh
python -m pip install -r requirements-hosted-demo.txt
bash scripts/start_demo.sh
```

For an alternate local port, run `PORT=8052 bash scripts/start_demo.sh`. The full live NLP/database deployment remains separate from this fixture deployment.

## Rebuild and verify the original NLP pipeline

Install the full environment and download the same base model used in the notebook:

```sh
python -m pip install -r requirements.txt
python -m spacy download en_core_web_trf
python build_disaster_model.py
python tests/check_disaster_model.py
```

`build_disaster_model.py` extracts the pipeline-building logic from `proj-dev/app/dataset_test.ipynb`:

1. Load `en_core_web_trf`.
2. Read the existing disaster labels and synonyms.
3. Generate the notebook's case-insensitive, lemma-derived optional-plural regex patterns.
4. Add an EntityRuler **before** the existing NER component, then add `spacytextblob`.
5. Save to `proj-dev/app/disaster_ner`.

The script resolves paths relative to the repository, so it can run from another working directory. Rebuilding replaces that generated model folder. The model weights remain ignored by Git. The transformer download is roughly 457 MB, with additional runtime dependencies and memory needed during loading/inference.

The integration check loads the saved pipeline through `live_demo/entity_extraction.py` and asserts that the example produces canonical disaster `Flood` and locations `Austin` and `Texas` (separate `GPE` entities, preserving the notebook's behavior). No Supabase account is required for this NLP-only check.

## Run with the real model service

Complete the model setup above, then create a local configuration file:

```sh
cp .env.example .env
```

Set `SUPABASE_URL` and `SUPABASE_KEY` for a database containing the existing `gazetteer` table. The live lookup expects these exact column names:

| Column | Expected content |
| --- | --- |
| `name` | Place or state name |
| `featureCode` | GeoNames code, such as `PPL` or `ADM1` |
| `stateCode` | U.S. state abbreviation, such as `TX` |
| `countryCode` | Country code, such as `US` |
| `latitude`, `longitude` | Numeric coordinates |
| `alternate_list` | Searchable text of alternate names, comma-delimited for token matching |
| `population` | Numeric population for fallback ordering |

The credentials must allow the server to read that table. A populated database, database migration, and original GeoNames `US.txt` download are **not included**. The legacy `proj-dev/data/load_csv.py` is an experiment, not a complete database provisioning command. Do not commit credentials.

In separate terminals with the environment activated, run:

```sh
# Terminal 1: model API, including Supabase location lookup
python proj-dev/app/live_demo/model_server.py

# Terminal 2: inject the known post through the real model API
python proj-dev/app/live_demo/process_test_tweet.py --output-dir .demo-live

# Terminal 3: show those results
CRISIS_DATA_DIR="$PWD/.demo-live" python proj-dev/app/live_demo/dash_client.py
```

The injector exits nonzero if it cannot produce both a crisis record and aggregate counts. This mode requires the model API and Supabase, but does not require Bluesky or the scraper. `GET http://127.0.0.1:5000/health` reports whether the NLP pipeline is loaded; it does **not** verify database connectivity. A missing model makes extraction return HTTP 503 instead of pretending a basic English model can detect custom disaster labels.

For continuous live collection, run these four processes in separate terminals:

```sh
python proj-dev/app/live_demo/model_server.py
python proj-dev/app/live_demo/firehose_scraper_server.py
python proj-dev/app/live_demo/entry.py
python proj-dev/app/live_demo/dash_client.py
```

Each processor run requests 100 posts. Default live outputs are `filtered_posts.csv` and `crisis_counts.csv` beside the live-demo scripts. If changing `CRISIS_DATA_DIR`, use the same absolute path for the processor and dashboard. Do not run multiple CSV-writing processors against the same directory.

## Docker

The Docker image installs dependencies and the base English transformer. It contains the repository, but the custom disaster pipeline still needs to be built. Its default command is `sleep infinity`; it does not automatically launch services.

From the repository root (POSIX shell):

```sh
docker build -t crisis-analysis .
docker run -d --name crisis-analysis-demo \
  -p 127.0.0.1:8051:8051 \
  -v "$PWD:/workspace" crisis-analysis

# Repeatable fixture demo; no credentials required
docker exec crisis-analysis-demo python proj-dev/app/live_demo/process_test_tweet.py --fixture --output-dir .demo
docker exec -d -e CRISIS_DATA_DIR=/workspace/.demo crisis-analysis-demo \
  gunicorn --chdir /workspace/proj-dev/app/live_demo dash_client:server \
  --bind 0.0.0.0:8051 --workers 1 --threads 2
```

For the real model path, keep `.env` at the mounted repository root, build the custom pipeline, and run the model server:

```sh
docker exec crisis-analysis-demo python build_disaster_model.py
docker exec -d crisis-analysis-demo python proj-dev/app/live_demo/model_server.py
docker exec crisis-analysis-demo python proj-dev/app/live_demo/process_test_tweet.py --output-dir .demo-live
```

Start a dashboard pointing at `/workspace/.demo-live` using the same Gunicorn command with that `CRISIS_DATA_DIR`. Stop an already-running dashboard/container before switching modes; both modes use port 8051. For continuous collection, also start `firehose_scraper_server.py` and `entry.py` with `docker exec -d`.

| Port | Purpose | Published to host? |
| --- | --- | --- |
| `8051` | Dash/Gunicorn dashboard | Yes, bound to host loopback |
| `5000` | Local model API | No |
| `5001` | Local firehose API | No |
| `8888` | Optional Jupyter notebook | Only if explicitly requested at container creation |

If macOS already occupies port 5000, use the container path. For notebook work, add `-p 127.0.0.1:8888:8888` when creating the container and run `jupyter notebook --ip=0.0.0.0 --port=8888 --no-browser --allow-root` inside it. Keep Jupyter's token authentication enabled.

Stop the demo with `docker stop crisis-analysis-demo`; remove its stopped container with `docker rm crisis-analysis-demo` before recreating it. Mounted source files, generated model weights, and demo outputs remain on the host.

## Checks

```sh
# Runs with requirements-demo.txt; no model or credentials needed
python -m unittest discover -s tests -v

# Requires the rebuilt real model
python tests/check_disaster_model.py

# Real model/API/CSV integration, with controlled database responses
python tests/check_model_pipeline.py
```

The regression suite covers HTTP fixture injection, deterministic CSV output, dashboard callbacks, scraper restoration after failure, stale-output rejection, safe CSV list parsing, and empty/error handling. See [docs/VALIDATION.md](docs/VALIDATION.md) for the checks actually run during cleanup and remaining blockers.

## Limitations and next steps

- **Unverified social reports:** keyword/rule matches can include figurative language, historical reports, negation, and misinformation. Human review is required.
- **U.S.-focused location handling:** ambiguous names and multiple locations can resolve incorrectly; reports without state/country data may not appear in aggregates. In the verified example, the transformer identifies Austin and Texas separately.
- **Counts represent extracted records:** a post with several locations can create several rows. Only the first disaster label is aggregated, and deduplication is within a batch, not across all runs.
- **Heuristic statistics:** “severity” is a relative report-count z-score, not physical impact. Accumulated sentiment currently averages batch means without weighting by batch size.
- **Taxonomy is inherited:** for example, tornado synonyms map to `Hurricane`. The cleanup preserves the notebook's rules rather than changing classification behavior.
- **Prototype storage and services:** CSV writes are not transactional; there is no authentication, retry queue, service orchestration, or production deployment configuration. Live firehose collection depends on external availability and has limited concurrency handling.
- **Reproducibility limits:** primary versions are pinned, but not all transitive dependencies. A full cross-platform lockfile and CI are future work.
- **Legacy experiments:** `proj-dev/app/main.py`, `live_demo/scraper_server.py`, `gazetteer_db.py`, and the notebook are not the supported demo startup path. The old scraper references an absent `blueskyapi_copy` module.

For a technical-sales walkthrough, explain the user need, follow one post through the service boundaries, show its location and supporting text, and close with the limits above and the validation needed before operational use. Do not claim production readiness or measured model accuracy from the fixture demo.
