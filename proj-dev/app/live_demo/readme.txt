The supported setup, model build, deterministic demo, ports, and limitations
are documented in the repository-root README.md.

From the repository root, after installing requirements-demo.txt:
  python proj-dev/app/live_demo/process_test_tweet.py --fixture --output-dir .demo
  CRISIS_DATA_DIR="$PWD/.demo" python proj-dev/app/live_demo/dash_client.py

Dashboard: http://localhost:8051
Fixture mode uses a predefined response and does not run live NLP or Supabase.
For real NLP, build the model and configure Supabase as described in README.md.
