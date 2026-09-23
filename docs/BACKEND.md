# Connect the real backend

The dashboard reads local CSVs; Supabase supplies location lookups, not report storage. Run the existing model service, processor, and dashboard on **one host** so they share those CSVs. `scripts/run_pipeline.py` starts and supervises them without changing the NLP pipeline or service boundaries.

The currently published free service is still the labeled fixture demo. Adding Supabase variables to that service alone does not activate the real model.

## Hosting and cost

The real transformer used approximately **2.6 GiB for the model process alone** during local loading/inference. Start with at least **4 GB RAM** for the combined service. This is a macOS measurement, not a guarantee of Linux memory use or sustained live-feed capacity; inspect Render metrics after deployment.

Render's Free instance has 512 MB RAM. The optional `render-live.yaml` defines a separate **paid `2c-4g` instance**, currently listed at **$85/month** on [Render's pricing page](https://render.com/pricing), checked September 22, 2026. Review the current price in Render before creating it. The existing `render.yaml` remains Free. Running the real pipeline locally avoids this additional hosting charge.

## Share the real local demo for free

For an interview, the existing Mac can run the model, processor, and dashboard while the Free Supabase project supplies location lookups. A [Cloudflare Quick Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/) gives that dashboard a temporary public HTTPS address without an additional hosting subscription or a Cloudflare account.

First start the real local pipeline on port 8052 using the instructions below. In a separate terminal, with `cloudflared` installed:

```sh
curl --fail http://127.0.0.1:8052/health
caffeinate -i cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8052
```

Open the `https://...trycloudflare.com` URL printed by the tunnel. The `caffeinate` command prevents idle sleep while the tunnel runs on macOS; keep the Mac plugged in, its lid open, and its network connected. On Linux, omit `caffeinate -i`. Stop the tunnel with Ctrl+C in its terminal; this removes public access while leaving the separately launched local pipeline running.

Only the dashboard port is forwarded. Model/database credentials remain in the backend. The startup input is still the labeled synthetic post processed by real NLP and Supabase. This is a temporary demo link, not always-on hosting: restarting the tunnel creates a new address, closing either process breaks the link, and Quick Tunnels have no uptime guarantee. The Render fixture remains an independent backup.

## Configure Supabase

The replacement **crisis-analysis** project is running in **nikitab724's Org** on the quoted **$0/month Free plan**, in Ohio (`us-east-2`). The owner can manage it in the [Supabase dashboard](https://supabase.com/dashboard/project/zhsnegbrxgdthfdcblpn). Its API URL is `https://zhsnegbrxgdthfdcblpn.supabase.co`. The restored table contains 193,736 original location records; server access is read-only and browser roles have no table access.

On the recovery machine, the ignored, owner-readable `.env` already contains the hosted credentials and ports 5002/8052. With the existing model/environment, run `.venv-live-check/bin/python scripts/run_pipeline.py --mode demo` from the repository root, then open **http://localhost:8052**. Stop any already-running copy first. The real model and all five dashboard callbacks have been verified against this hosted database. Credentials and model weights are not included in a fresh clone.

If the old project has exceeded its pause recovery window, [restore the downloaded gazetteer backup into a new project](GAZETTEER_RESTORE.md) first. That guide also covers a local Supabase rehearsal without hosting charges.

Copy the **Project URL** and an API key that permits server-side `SELECT` access to the populated `gazetteer` table. Enter them directly in Render's secret environment fields, or in the ignored local `.env` file:

| Variable | Value |
| --- | --- |
| `SUPABASE_URL` | Project URL, such as `https://your-project.supabase.co` (not a PostgreSQL connection string) |
| `SUPABASE_KEY` | API key with read access to `gazetteer` |

Supabase's current server-only secret keys start with `sb_secret_`; an existing legacy `service_role` key also works. These keys have elevated access and must stay in server settings, never browser code, Git, or chat. If the existing project already provides a lower-privilege key with suitable read permissions, that is sufficient. See [Supabase API key guidance](https://supabase.com/docs/guides/getting-started/api-keys).

The table must expose these exact columns: `geonameid`, `name`, `featureCode`, `stateCode`, `countryCode`, `latitude`, `longitude`, `alternate_list`, and `population`. The known demo expects an Austin city row (`PPL…`, `TX`, `US`) and a Texas state row (`ADM1`, `TX`, `US`). City lookups first respect an adjacent state name or abbreviation (for example, Perryville, Alaska); a single extracted state can also provide context. Case-insensitive exact names and whole aliases must yield a unique match within that context. Population ordering makes query results deterministic; it no longer decides which ambiguous place to plot. Explicit foreign-country context leaves unqualified locations unresolved instead of mapping them to US namesakes. Foreign and ambiguous locations are excluded from saved reports and all dashboard views. Records must carry an explicit US country and a supported state (50 states or DC); missing countries are never assumed to be US. Mixed-country posts retain only their resolved US records. Match labels describe evidence rather than statistical confidence. The app launcher performs no migrations or database writes.

## Deploy the separate real service on Render

Only proceed after accepting the paid instance cost.

1. In Render, choose **New → Blueprint** and select `nikitab724/crisis-analysis`.
2. Select branch **`polish/interview-demo`** and set **Blueprint Path** to **`render-live.yaml`**. The default `render.yaml` starts the free fixture demo instead.
3. Confirm the service is `crisis-analysis-live`, with the **4 GB `2c-4g`** instance. Review its displayed price.
4. Enter `SUPABASE_URL` and `SUPABASE_KEY` when prompted. Leave `CRISIS_PIPELINE_MODE=demo` for the initial rehearsal.
5. Create the Blueprint. The build installs CPU dependencies, downloads `en_core_web_trf` 3.8.0, reproduces the notebook's disaster pipeline, and checks its entity output. The first build includes a large model download.
6. Wait for the service to become live, then open its assigned URL. Its `/health` endpoint must return `{"status":"healthy","mode":"demo"}`.

Startup loads the real model, verifies a readable gazetteer, and processes **“Flood in Austin Texas.”** through the real model API and Supabase. The dashboard starts only after usable CSV output exists. Open **About the data** to confirm **“Real NLP and Supabase”**, and look for Flood/Texas results and the original post in the table. When both Austin and Texas resolve, the supporting state is folded into the city match: **one location record from one synthetic post**. Standalone state reports and genuinely different cities remain separate.

This `demo` mode uses a known synthetic input but **does not replay the saved model response**. It is the repeatable real-backend interview path.

For continuous collection after rehearsal works, change `CRISIS_PIPELINE_MODE` to `live` in this Blueprint and deploy the update. That also starts the original Bluesky firehose service and batch processor. The startup post remains present and labeled. Live traffic may contain no qualifying crisis posts and depends on external availability.

Render supplies the public `PORT`. Model/scraper ports default to `5000`/`5001`, bind only to `127.0.0.1`, and are not public. Only one model process and one CSV writer run. Automatic deployments are disabled; deploy later code updates manually. Blueprint synchronization can still apply configuration changes, including instance plans—review changes before syncing.

## Run locally without a paid instance

Use Python 3.12 on macOS or Linux with at least 4 GB available RAM (more headroom is preferable). From the repository root:

```sh
python3.12 -m venv .venv-live
source .venv-live/bin/activate
bash scripts/build_live.sh
cp .env.example .env
# Fill in SUPABASE_URL and SUPABASE_KEY in .env, then:
PORT=8052 MODEL_PORT=5002 python scripts/run_pipeline.py --mode demo
```

Open **http://localhost:8052**. Port 5002 avoids macOS services that sometimes occupy 5000. If dependencies and the model are already built in your active environment, skip installation/build. Do not overwrite an existing configured `.env`; edit it instead. To collect Bluesky posts, use `--mode live`. Stop with Ctrl+C. The launcher is POSIX-only; on Windows use Docker or WSL.

The recovery machine is now running **live mode**, with the collector on internal port **5004** and the same dashboard/tunnel on **8052**. To restart it with the prepared environment, stop the current pipeline, then run:

```sh
.venv-live-check/bin/python scripts/run_pipeline.py --mode live
```

Use `--mode demo` to return to the repeatable example instead. Restarting the pipeline resets this run's collected data. The separately running tunnel does not need to restart, so its address can stay the same.

The activity row reports posts received, successfully analyzed posts, analysis errors, and the latest processor update. Counts exclude the synthetic startup post; the charts include its extracted records. A batch with no matching crisis posts still advances activity. `/activity` exposes the same counters without credentials or post contents. The collector requests up to 100 posts per batch, returns partial batches after 40 seconds, then reconnects on the next batch. Posts published between collection windows can be missed.

## Troubleshooting and limits

| Symptom | Check |
| --- | --- |
| Blueprint not found / fixture banner | Branch `polish/interview-demo`; real backend Blueprint path `render-live.yaml` |
| Missing Supabase variables | Set both values in service Environment settings and restart |
| `Gazetteer readiness failed` | Project URL, API key, SELECT permissions, exact column names, and Supabase project availability |
| `empty or unreadable` | Table has no rows, or row-level security hides rows from this key |
| No complete startup crisis output | Austin/Texas gazetteer coverage and model-service logs |
| Missing custom model | Build must finish `build_disaster_model.py` successfully |
| Process killed / out of memory | Inspect memory metrics; Free and 2 GB instances are too small for the local measurement |
| Live mode shows only startup post | Check ingestion logs; random traffic need not contain a qualifying report |

Every start uses a fresh temporary data directory and regenerates the known post. CSV history is **not durable** across restarts/deploys. Existing local data directories are preserved. If a child service exits, the launcher stops its other processes and exits nonzero. `/health` checks model/database readiness and both CSVs. Live mode also requires a processor update within three minutes and no current collection error. This does not establish complete stream coverage, recent matching posts, or incident accuracy.

Original CSV concurrency, location ambiguity, counting, and live-feed limitations still apply. See [validation results](VALIDATION.md) for the hosted database verification and separate tests using controlled responses. The public Render fixture has not been switched to the real transformer service.

## Optional semantic relevance filter

The US scope filter is always active. Optional Jev classification can select among complete, bounded gazetteer candidate lists when post context distinguishes one city. It abstains on insufficient evidence, foreign places, or indistinguishable same-city/state entries. Coordinates remain database-supplied. A subsequent relevance screen rejects figurative, historical, or unrelated disaster mentions before saving new records. See [Jev setup and limits](JEV.md) for the Vercel Gateway key, bounded evaluations, shared request cap, activation, and failure behavior. It is off by default and the deterministic fixture never calls the provider.

Supabase database network operations use a three-second timeout so a stalled read releases the model worker. Readiness reports an unavailable database as unhealthy; location lookup failures stay unresolved. This is a per-operation timeout, not a total batch deadline. `tests/check_backend_runtime.py` checks a stalled local database response and recovery as well as explicit database outages.
