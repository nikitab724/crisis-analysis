# Interview walkthrough

Open the Render page before presenting so the Free service has time to wake. The first view shows the complete dataset. Use **Replay demo** to start from an empty map, **Pause** to explain a result, **Next post** for a controlled step, and **Show all** to jump to the complete view. Playback is separate for each visitor and never writes live data.

## A two-minute story

1. Explain the problem: useful emergency reports are mixed with everyday conversation, jokes, historical events, and vague place names.
2. State the demo boundary: “This is a fixed synthetic dataset with predefined results so the walkthrough is repeatable. The live pipeline uses spaCy, a geographic database, and Jev; that path depends on external service capacity.”
3. Click **Replay demo**, then **Pause**. Step through the first four posts: coffee is skipped; an Austin warning is mapped; sports metaphors are skipped; the Houston post describes flooding without using the word “flood.” Its parent context explicitly locates Houston in Texas.
4. Step to bare “Portland”: a crisis is present but there is insufficient location context, so no marker appears. The next post names Portland, Oregon and is mapped. A later example names Portland, Maine separately.
5. Click **Show all**. Use the state filter to show Texas. Austin and Houston each have two reports, so their circles grow by report count. Circle size is not the physical area of a disaster.
6. Optionally use **Try a test post** for a real prediction: enter “The streets in Houston, Texas are underwater and people are trapped in their homes.” Click **Analyze post**. A resolved result appears as a green diamond with its own label. **Clear test** removes it. Test results never affect the replay counts or another visitor's browser.

Test posts share a 12-second budget across location lookup, model pacing, and model requests. A request that cannot fit returns a retry message and frees the test slot. Render's backend read timeout is 16 seconds, allowing for the tunnel. An interactive Jev evaluation can retry once after a 502/503/504 response, only if the full cooldown fits the remaining budget with time left for the request. Rate-limit and access failures are not retried. Provider cooldowns remain enforced, and sample results never substitute for a failed prediction. Errors distinguish Jev availability, Jev access, location analysis, and the backend connection. Resolved locations receive one classification pass; an unresolved location may require a separate classification. Include the state when a city name is ambiguous, for example “flood in San Mateo, CA.” Ordinary illness alone does not meet the Pandemic definition.
7. Close with the engineering tradeoff: controlled playback makes the product story reliable; live throughput, external rate limits, factual verification, and location accuracy still require evaluation.

## What actually runs

| Mode | Input and analysis | External dependencies |
| --- | --- | --- |
| Interview replay (`CRISIS_PIPELINE_MODE=sample`) | 24 authored posts and authored decisions; real dashboard aggregation/rendering | Browser basemap asset only |
| Test-post box | Arbitrary typed text through the existing real analysis worker; no file writes or publishing | Mac/model, Supabase, Jev, and tunnel |
| Single-post fixture (`process_test_tweet.py --fixture`) | One authored Austin post and a predefined HTTP model response; real filtering, CSV writes, aggregation | Local HTTP only; browser basemap for viewing |
| Real model injection | Synthetic text through spaCy, gazetteer, and configured semantic checks | Built model, Supabase, Jev when enabled |
| Live pipeline | Collected Bluesky posts through the real processing services | Mac/backend, Bluesky, Supabase, configured Jev provider; tunnel for Free Render gateway |

The replay's 14 mapped examples, nine skipped examples, and one unresolved location are **expected demonstration outcomes**, not an accuracy score or captured model predictions. Weather-alert text is invented and has no official source attribution. Rows link to no real accounts. Each mapped post has one predefined US city; 14 reports aggregate into 12 map points across nine states. Replay controls do not trigger provider calls. Only an explicit **Analyze post** submission invokes real analysis; nothing is published to Bluesky.

The JSON dataset is `proj-dev/app/live_demo/fixtures/interview_feed.json`. The replay reads it in memory and ignores live report files, expiry, and provider settings. Dates are deliberately absent; these examples stay available for rehearsal.

## Connect the optional test box

1. Keep the real model service and Mac dashboard running. Give the Mac dashboard the existing `MODEL_SERVER_URL`, `CRISIS_RELEVANCE_MODE=jev`, `AI_GATEWAY_API_KEY`, and the chosen Jev limits. The background collector is not required for these tests.
2. Generate a random secret of at least 32 characters and set it as `CRISIS_TEST_API_TOKEN` on both the Mac dashboard and Render. Keep it in ignored local configuration and Render's server environment; never put it in browser code or commit it. Set `CRISIS_TEST_BACKEND=1` only on the Mac dashboard, then restart that dashboard. Leave it unset on Render.
3. On Render, retain `CRISIS_PIPELINE_MODE=sample` and set `LIVE_DASHBOARD_URL` to the Mac dashboard's HTTPS tunnel origin. Redeploy. Replay still runs independently; only test submissions call the authenticated `/demo/analyze` endpoint through the server.

Test text is limited to 1,000 characters, with one real test in flight on the Mac at a time. It uses the existing Jev/location analysis worker without entering the collector queue, fetching a user profile, writing CSVs, or acknowledging posts. A locationless crisis can be identified but stays unplotted; unrelated text is explicitly rejected. Provider and network failures are reported as unavailable, never replaced by a predefined outcome. Custom tests can still encounter the live provider's rate limits. The Mac and tunnel can be offline without affecting replay.

An ambiguous place produces an actionable explanation. For example, lowercase “houston” is recognized, but the gazetteer contains multiple places with that name. Add “Houston, Texas” or “houston tx” to identify the intended city. State abbreviations accept mixed case except ordinary words such as “in”, “or”, and “me”, which still need uppercase or a full state name. The suggested city/state pair is an example from the database, not an automatic selection or a claim that Texas was inferred. Missing place names, unmatched places, and crises that cannot be linked to a resolved place have separate messages.

## Deploy and restore

Use the existing Free Render service with the normal build/start commands. Set `CRISIS_PIPELINE_MODE=sample` and deploy the latest commit. `/health` should return `mode: sample`, `status: healthy`, and `posts: 24`.

To restore the live gateway, remove `CRISIS_PIPELINE_MODE`, set `LIVE_DASHBOARD_URL` to the current Mac tunnel, and redeploy. Collection may still be intentionally paused; resume it separately with `python scripts/collection_control.py resume` only when ready. Existing queued posts and live outputs are preserved by the mode switch.

Local fallback: install `requirements-demo.txt`, then run `CRISIS_PIPELINE_MODE=sample python proj-dev/app/live_demo/dash_client.py` and open port 8051. For the same Gunicorn startup as Render, install `requirements-hosted-demo.txt` and run `CRISIS_PIPELINE_MODE=sample bash scripts/start_demo.sh`.
