# Recover the gazetteer from a paused project's backup

A project beyond Supabase's pause recovery window can be recovered by moving its downloaded backup to a new project. See [Supabase's recovery guide](https://supabase.com/docs/guides/troubleshooting/restore-project-after-90-days-pause). Do not delete the old project until recovery is verified.

This app needs the `public.gazetteer` data. The supplied cluster backup was inspected locally: **2,241,204 gazetteer rows**, including **193,736 populated places and first-level administrative regions**. Those are the feature types the current lookup queries (`PPL%` and `ADM1`). The default extraction retains all those records unchanged; it does not restrict the database to Austin/Texas. Authentication tables, roles/passwords, Vault secrets, and unrelated cluster SQL are excluded.

The original backup remains untouched and is not committed or uploaded by preparation. The generated restore file also stays outside Git in `.restore/`.

## Completed hosted recovery

On September 22, 2026, the selected records were restored to the replacement **crisis-analysis** project in **nikitab724's Org**, on the confirmed **$0/month Free plan**. The [project dashboard](https://supabase.com/dashboard/project/zhsnegbrxgdthfdcblpn) requires owner access. The old paused project and unrelated projects were left untouched.

The hosted schema matches the restore script. The data was uploaded in batches through the Supabase API using a private server key and a temporary INSERT grant. That grant was removed after import: `service_role` can SELECT only, while `anon` and `authenticated` have no table privileges. RLS remains enabled, with no public policies. Credentials are stored only in ignored, owner-readable local files.

Verification found **193,736 rows**, the expected Austin/Texas IDs, and an identical complete-table fingerprint in the local and hosted databases (`a253760600912226de1dee9f3e9c9fc1`, computed from ordered row JSON). Hosted storage measured **40 MB for the table including indexes**, **51 MB for the database** immediately after restoration. The original backup is still untouched.

The local app now uses this hosted project at **http://localhost:8052**. This hosts the location database only; the transformer, processor, and dashboard still run locally. The public Render URL remains the separate fixture demo.

## Prepare the restore

From the repository root:

```sh
python scripts/prepare_gazetteer_restore.py /path/to/downloaded.backup
```

This accepts the plain-text PostgreSQL dump format used by the supplied backup. It validates the gazetteer COPY columns and row structure, preserves COPY escaping, and writes **`.restore/gazetteer.sql`**. It prints row counts and a SHA-256 checksum of the selected data. It refuses to overwrite an existing output and removes incomplete output on failure.

To retain all gazetteer feature types, including those the app never queries:

```sh
python scripts/prepare_gazetteer_restore.py /path/to/downloaded.backup \
  --all-features --output .restore/gazetteer-full.sql
```

The application-sized restore is about **17.6 MB of SQL** and occupied **38 MB including indexes** in the local PostgreSQL 16 check. A new Supabase database also has platform overhead. Inspect the total size after cloud import; the [Free plan database quota](https://supabase.com/docs/guides/platform/database-size) currently is 500 MB. Full-feature import size has not been measured.

## Restore into a new hosted Supabase project

1. Create a new project in a **Free organization** at [Supabase](https://supabase.com/dashboard). Review that no paid plan or add-on is selected.
2. In **Connect**, choose the **Session pooler** connection details. Keep the database password private.
3. Use PostgreSQL's `psql` client with those host, port, database, and username values. The command below prompts for the password rather than storing it in shell history:

```sh
PGSSLMODE=require psql -X --host YOUR_SESSION_POOLER_HOST --port 5432 \
  --username postgres.YOUR_PROJECT_REF --dbname postgres \
  --password --set ON_ERROR_STOP=1 --file .restore/gazetteer.sql
```

The command requires TLS for the hosted connection. The script uses `COPY FROM stdin`, so run it through `psql`; do not paste it into the browser SQL editor. A native PostgreSQL client or a PostgreSQL Docker image can supply `psql`.

The generated script runs table creation, import, indexing, and access configuration in one transaction. **It fails if `public.gazetteer` already exists** and never drops/truncates an existing table. Inspect a conflicting table before deciding how to handle it. Retrying after a successful restore is expected to fail harmlessly. The final `ANALYZE` runs after commit; an interruption during that final step does not undo the completed import.

The restored table has a GeoNames primary key, city-name/population and state indexes, and row-level security enabled. Only the server's `service_role` receives SELECT access; browser/anonymous clients receive no table access. Use a server secret or legacy service-role key for this restore's access policy. No public read policy or database write API is needed.

After importing, verify the row count and city selection in the SQL editor:

```sql
SELECT count(*) FROM public.gazetteer; -- expected default: 193736

SELECT geonameid, name, "stateCode", "featureCode", population
FROM public.gazetteer
WHERE name = 'Austin' AND "featureCode" ILIKE 'PPL%'
ORDER BY population DESC NULLS LAST, geonameid
LIMIT 1; -- Austin, TX, GeoNames ID 4671654
```

Then set the new project's `SUPABASE_URL` and server-only `SUPABASE_KEY` in the app environment and follow [backend startup](BACKEND.md). API keys and database passwords belong in private settings, never chat or Git. Provisioning a Free database does not pay for the separate Render instance required by the transformer.

## Local recovered rehearsal

On the recovery machine, a separate local Supabase project was initialized under the ignored `.restore/local-supabase` directory with project ID `crisis-analysis-rehearsal`. It uses API port **55431**, database port **55432**, and the original restored data. Its settings are separate from other local projects. Its credentials are preserved in the ignored, owner-readable `.env.local`; `.env` now selects the hosted database.

To restart the prepared local project and demo:

```sh
supabase start --workdir .restore/local-supabase \
  -x realtime,storage-api,imgproxy,mailpit,postgres-meta,studio,edge-runtime,logflare,vector,supavisor
source .venv-live-check/bin/activate
python - <<'PY'
import os
import sys
from dotenv import load_dotenv

load_dotenv(".env.local", override=True)
os.execv(sys.executable, [sys.executable, "scripts/run_pipeline.py", "--mode", "demo"])
PY
```

Stop an existing dashboard before starting this fallback, since both use **http://localhost:8052**. The command above selects the local database for that run without changing `.env`. Stop the app with Ctrl+C and stop only this database with `supabase stop --workdir .restore/local-supabase`. Ordinary local stop preserves its database volume; do not use reset or delete the volume to stop it.

The local project directory and credentials are machine-specific, not included in a fresh clone. For a fresh local setup, initialize a separate Supabase CLI project, select unused ports in its `supabase/config.toml`, start it, and restore the generated SQL into that project's database. Use its local API URL/service key in `.env`, then follow the normal model build/start instructions.

The recovered data contains many places called Austin. The app now orders exact city-name matches by population and then GeoNames ID, consistent with its existing population-based fallback. This makes the interview example deterministic without changing the NLP model. It remains a heuristic; an unqualified place named Austin may still be misidentified. The later location refinement uses explicit state context before population ordering; see [validation](VALIDATION.md).
