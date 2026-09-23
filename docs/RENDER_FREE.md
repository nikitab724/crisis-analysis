# Live dashboard on Render Free

The existing Render service can serve the real dashboard while the Mac runs NLP, Jev, ingestion, and CSV storage. The processing architecture stays on one host:

```text
Browser → Render Free → Cloudflare tunnel → Mac dashboard → local CSVs
                                            ↑
                                existing NLP + Jev pipeline
```

This gives the app its stable `onrender.com` address without paying for a larger model host. It still depends on the Mac, its network, and the temporary tunnel. Render Free can sleep when idle; see [Render's current Free limitations](https://render.com/docs/free).

## Deploy or update the existing service

1. Keep the [Mac live pipeline and Cloudflare tunnel](BACKEND.md#share-the-real-local-demo-for-free) running. Verify the current tunnel's `/health` returns `{"mode":"live","status":"healthy"}`. Use the current URL printed by `cloudflared`; restarting a Quick Tunnel changes that address.
2. Use the existing **crisis-analysis-interview-demo** service with its **Free** plan, branch `polish/interview-demo`, build command `pip install -r requirements-hosted-demo.txt`, start command `bash scripts/start_demo.sh`, and health check `/_dash-layout`.
3. In Render's Environment settings, set **`LIVE_DASHBOARD_URL`** to the current HTTPS tunnel origin, for example `https://your-current-tunnel.trycloudflare.com`. Supply no trailing path, query parameters, or credentials. This URL is public, not an API key. The Free service does not need Supabase or Gateway credentials.
4. Deploy the latest commit. Automatic deployments remain disabled. Open the Render URL and verify `/health` reports `mode=live`, `/_proxy/health` reports `mode=proxy`, and `/activity` shows live processor updates. The map, post filters, and all other dashboard callbacks go through the same Render URL.

The launcher selects forwarding mode only when `LIVE_DASHBOARD_URL` is set. Otherwise it builds the original labeled fixture and runs it independently. To deliberately restore that fallback, remove the variable and redeploy. An unavailable live backend never silently becomes fixture data.

To rehearse the forwarding service locally with the lightweight Render dependencies:

```sh
python tests/check_render_gateway.py --backend-url https://your-current-tunnel.trycloudflare.com
```

To verify an already deployed service:

```sh
python tests/check_render_gateway.py --url https://crisis-analysis-interview-demo.onrender.com
```

The rehearsal starts an isolated temporary gateway, checks the real browser assets, layout, all six callbacks, live health/activity, and refusal to forward the model API, then stops only that gateway. It neither restarts the Mac pipeline nor writes test posts.

## Availability and boundaries

- Keep the Mac plugged in, awake, and online, with the pipeline and tunnel running. When the tunnel URL changes, update `LIVE_DASHBOARD_URL` in Render and redeploy.
- If the backend is unavailable, the entry page returns a clear 503 message and callbacks return an unavailable response. Previously loaded browser content may remain until refresh; check the activity timestamp. Render readiness depends on being able to retrieve the actual dashboard layout.
- The gateway only forwards dashboard routes to one configured origin. It rejects model/ingestion routes, arbitrary destinations, unsupported methods, and redirects. It does not forward browser credentials or cookies, or copy provider cookies into the response.
- Callback bodies are limited to 256 KiB and responses to 16 MiB, with connect/read timeouts of 3/15 seconds. Live data responses are not cached; static assets keep their cache headers.
- Forwarding mode uses four request threads and reuses a separate backend HTTP connection pool in each thread to avoid repeating TLS setup for every callback. Cookies are cleared before and after each request; a transport failure discards that thread's connection. The Mac dashboard refreshes every two seconds.
- Mac CSV history is temporary unless explicitly archived and restored with `--resume-from`; see [backend startup](BACKEND.md). This setup does not make the model run on Render or provide independent, always-on processing.
- A Render management API key, if used for deployment, belongs only in an ignored local configuration. It is not a runtime dependency and must never be committed or placed in browser code.
