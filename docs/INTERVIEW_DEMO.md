# Interview walkthrough

Open the Render page before presenting so the Free service has time to wake. The map shows all saved results immediately; the feed starts with the newest 50 posts. **Load more posts** shows the next 50. The original live collector and backlog are paused; browsing this dataset does not collect or analyze anything.

Use the map's **Zoom in**, **Zoom out**, and **Reset** controls in the upper-right corner. You can also scroll over the map to zoom and drag to move around. Reset restores the full US view.

## A two-minute story

1. Explain the problem: useful emergency reports are mixed with unrelated discussion and vague place names.
2. State the demo boundary: “These are real Bluesky posts our pipeline already processed. We are browsing a saved snapshot so the presentation does not depend on live collection or model availability.”
3. Read a post, inspect its date, and use **View on Bluesky** to open its original source if desired. No fictional names, sample labels, or authored classifications are added to the feed.
4. Select a state to browse its reports. Each source post appears once; its saved locations contribute to the map. Circle size represents location records, not the physical size of a disaster or verified incidents.
5. Optionally use **Try a test post** for a new prediction: enter “The streets in Houston, Texas are underwater and people are trapped in their homes.” Click **Analyze post**. A resolved result appears as a green diamond. **Clear test** removes it. Tests do not change the saved dataset or another visitor's browser.
6. Explain the tradeoff: saved results make browsing predictable; new predictions still depend on location lookup and model availability. The snapshot is not an accuracy benchmark.

Test posts share a 12-second budget across location lookup, model pacing, and model requests. A request that cannot fit returns a retry message and frees the test slot. Render's backend read timeout is 16 seconds, allowing for the tunnel. An interactive Jev evaluation can retry once after a 502/503/504 response, only if the full cooldown fits the remaining budget with time left for the request. Rate-limit and access failures are not retried. Provider cooldowns remain enforced, and saved results never substitute for a failed prediction. Errors distinguish Jev availability, Jev access, location analysis, and the backend connection. Resolved locations receive one classification pass; an unresolved location may require a separate classification. Include the state when a city name is ambiguous, for example “flood in San Mateo, CA.” Ordinary illness alone does not meet the Pandemic definition.

An identical test can reuse its validated real result for up to 60 seconds in the Render worker (128 entries maximum). Failed requests are never cached; a changed post or expired entry runs real analysis again. The cache is separate from the saved dataset, uses no persistent storage, and is invalidated by a backend URL or credential change. Backend connections are reused within each worker thread. Interactive tests retain the configured minimum request interval and provider cooldowns without inheriting the live collector's escalating batch cadence. Fresh text still needs the Mac, gazetteer, and Jev; this setup does not promise instant first-time predictions.

## What actually runs

| Mode | Input and analysis | External dependencies |
| --- | --- | --- |
| Saved-post demo (`CRISIS_PIPELINE_MODE=sample`) | 453 previously processed public posts and 586 saved US location records; real dashboard aggregation | Browser basemap asset only |
| Test-post box | Arbitrary typed text through the real analysis worker; no file writes or publishing | Mac/model, Supabase, Jev, and tunnel |
| Single-post fixture (`process_test_tweet.py --fixture`) | One authored Austin post and a predefined HTTP model response; real filtering, CSV writes, aggregation | Local HTTP only; browser basemap for viewing |
| Real model injection | Synthetic text through spaCy, gazetteer, and configured semantic checks | Built model, Supabase, Jev when enabled |
| Live pipeline | Collected Bluesky posts through the processing services | Mac/backend, Bluesky, Supabase, configured Jev provider; tunnel for Free Render gateway |

The snapshot preserves the processed CSV's text, original posting times and URIs, categories, and coordinates. It groups multiple location records under the original post and excludes non-public, synthetic, and non-US rows when exporting. The current export includes all 453 distinct source posts and all 586 valid location records in that saved file, with no rows excluded. Public names were not collected with these records, so the feed links to original posts without inventing author names. Saved classifications and geocoding can be wrong; importing them does not validate or improve their accuracy.

The JSON dataset is `proj-dev/app/live_demo/fixtures/interview_feed.json`. The dashboard reads it in memory and ignores live files, expiry, and provider settings. It does not fetch profiles or posts from Bluesky. Clicking an original source link opens Bluesky separately. Dates remain unchanged so historical reports are not presented as current alerts.

To explicitly replace the snapshot from another processed CSV:

```sh
python scripts/export_demo_posts.py --input /path/to/filtered_posts.csv
```

The exporter only reads that file. It never invokes collection, NLP, geocoding, or Jev; it exports an allowlist of public post fields and saved map results. Review the output before committing. It records the input file's SHA-256 for provenance and does not modify or resume the source pipeline.

## Connect the optional test box

1. Keep the real model service and Mac dashboard running. Give the Mac dashboard the existing `MODEL_SERVER_URL`, `CRISIS_RELEVANCE_MODE=jev`, `AI_GATEWAY_API_KEY`, and the chosen Jev limits. The background collector is not required for these tests.
2. Generate a random secret of at least 32 characters and set it as `CRISIS_TEST_API_TOKEN` on both the Mac dashboard and Render. Keep it in ignored local configuration and Render's server environment; never put it in browser code or commit it. Set `CRISIS_TEST_BACKEND=1` only on the Mac dashboard, then restart that dashboard. Leave it unset on Render.
3. On Render, retain `CRISIS_PIPELINE_MODE=sample` and set `LIVE_DASHBOARD_URL` to the Mac dashboard's HTTPS tunnel origin. Redeploy. The saved feed still runs independently; only test submissions call the authenticated `/demo/analyze` endpoint through the server.

Test text is limited to 1,000 characters, with one real test in flight on the Mac at a time. It uses the existing Jev/location analysis worker without entering the collector queue, fetching a user profile, writing CSVs, or acknowledging posts. A locationless crisis can be identified but stays unplotted; unrelated text is explicitly rejected. Provider and network failures are reported as unavailable, never replaced by a predefined outcome. Custom tests can still encounter the live provider's rate limits. The Mac and tunnel can be offline without affecting the saved feed.

An ambiguous place produces an actionable explanation. For example, lowercase “houston” is recognized, but the gazetteer contains multiple places with that name. Add “Houston, Texas” or “houston tx” to identify the intended city. State abbreviations accept mixed case except ordinary words such as “in”, “or”, and “me”, which still need uppercase or a full state name. The suggested city/state pair is an example from the database, not an automatic selection or a claim that Texas was inferred. Missing place names, unmatched places, and crises that cannot be linked to a resolved place have separate messages.

## Deploy and restore

Use the existing Free Render service with the normal build/start commands. Set `CRISIS_PIPELINE_MODE=sample` and deploy the latest commit. `/health` should return `mode: sample`, `status: healthy`, and `posts: 453`.

To restore the live gateway, remove `CRISIS_PIPELINE_MODE`, set `LIVE_DASHBOARD_URL` to the current Mac tunnel, and redeploy. Collection may still be intentionally paused; resume it separately with `python scripts/collection_control.py resume` only when ready. Existing queued posts and live outputs are preserved by the mode switch.

Local fallback: install `requirements-demo.txt`, then run `CRISIS_PIPELINE_MODE=sample python proj-dev/app/live_demo/dash_client.py` and open port 8051. For the same Gunicorn startup as Render, install `requirements-hosted-demo.txt` and run `CRISIS_PIPELINE_MODE=sample bash scripts/start_demo.sh`.
