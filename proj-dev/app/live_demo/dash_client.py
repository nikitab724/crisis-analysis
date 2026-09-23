from dash import Dash, dcc, html, Input, Output
import pandas as pd
import requests
import plotly.graph_objects as go
import os
import ast
from datetime import datetime, timezone
from urllib.parse import quote

from pipeline_status import read_status
from gazetteer import US_STATE_NAMES
from us_scope import us_records
from retention import recent_posts
import math
from pathlib import Path

DATA_DIR = Path(os.environ.get("CRISIS_DATA_DIR", Path(__file__).parent)).resolve()
PIPELINE_MODE = os.environ.get("CRISIS_PIPELINE_MODE", "")
if (DATA_DIR / "fixture-demo.json").is_file():
    PIPELINE_MODE = "fixture"

# Create the Dash app
app = Dash(__name__, assets_folder=str(Path(__file__).parent / "assets"))
server = app.server
backend_http = requests.Session()
# The private model endpoint does not use system proxy discovery. On macOS,
# that discovery can initialize Objective-C unsafely in a forked web worker.
backend_http.trust_env = False


def activity_is_stale(status):
    try:
        updated = datetime.fromisoformat(status["updated_at"])
        return (datetime.now(timezone.utc) - updated).total_seconds() > 180
    except (KeyError, TypeError, ValueError):
        return True


def activity_snapshot():
    status = read_status(DATA_DIR)
    scraper = os.environ.get('SCRAPER_SERVER_URL')
    if PIPELINE_MODE == 'live' and scraper:
        try:
            response = backend_http.get(scraper.rstrip('/') + '/status', timeout=1)
            response.raise_for_status()
            status['collector'] = response.json()
        except (requests.RequestException, ValueError):
            status['collector'] = {**status.get('collector', {}), 'state': 'unavailable'}
    return status


@server.get('/health')
def health_check():
    if PIPELINE_MODE in ("demo", "live"):
        try:
            model_url = os.environ.get("MODEL_SERVER_URL", "http://127.0.0.1:5000").rstrip("/")
            response = backend_http.get(f"{model_url}/ready", timeout=5)
            if response.status_code != 200 or response.json().get("status") != "healthy":
                return {"status": "unavailable", "component": "backend"}, 503
        except (requests.RequestException, ValueError):
            return {"status": "unavailable", "component": "backend"}, 503
    if not all((DATA_DIR / name).is_file() for name in ("filtered_posts.csv", "crisis_counts.csv")):
        return {"status": "unavailable", "component": "data"}, 503
    if PIPELINE_MODE == "live":
        status = activity_snapshot()
        collector = status.get('collector', {})
        if (activity_is_stale(status) or status.get("phase") == "error"
                or (collector.get('source_lag_seconds') or 0) > 60
                or (collector and collector.get('state') != 'connected')):
            return {"status": "unavailable", "component": "collector"}, 503
    return {"status": "healthy", "mode": PIPELINE_MODE or "dashboard"}

def load_dashboard_posts():
    posts = us_records(pd.read_csv(DATA_DIR / 'filtered_posts.csv'))
    return recent_posts(posts) if PIPELINE_MODE == 'live' else posts


def load_dashboard_counts():
    if PIPELINE_MODE == 'live':
        # Recompute from the current window even when the writer is unavailable.
        from entry import calculate_crisis_counts
        return calculate_crisis_counts(load_dashboard_posts())
    return us_records(pd.read_csv(DATA_DIR / 'crisis_counts.csv'))


# Load initial data if available
try:
    if os.path.exists(DATA_DIR / 'crisis_counts.csv'):
        df = pd.read_csv(DATA_DIR / 'crisis_counts.csv')
    else:
        df = pd.DataFrame()

    if os.path.exists(DATA_DIR / 'filtered_posts.csv'):
        posts_df = pd.read_csv(DATA_DIR / 'filtered_posts.csv')
    else:
        posts_df = pd.DataFrame()
except Exception as e:
    print(f"Error loading initial data: {e}")
    df = pd.DataFrame()
    posts_df = pd.DataFrame()

# State coordinates for map visualization (approximate centroids)
state_coordinates = {
    'Alabama': ('32.7794', '-86.8287'),
    'Alaska': ('64.0685', '-152.2782'),
    'Arizona': ('34.2744', '-111.6602'),
    'Arkansas': ('34.8938', '-92.4426'),
    'California': ('37.1841', '-119.4696'),
    'Colorado': ('38.9972', '-105.5478'),
    'Connecticut': ('41.6219', '-72.7273'),
    'Delaware': ('38.9896', '-75.5050'),
    'Florida': ('28.6305', '-82.4497'),
    'Georgia': ('32.6415', '-83.4426'),
    'Hawaii': ('20.2927', '-156.3737'),
    'Idaho': ('44.3509', '-114.6130'),
    'Illinois': ('40.0417', '-89.1965'),
    'Indiana': ('39.8942', '-86.2816'),
    'Iowa': ('42.0751', '-93.4960'),
    'Kansas': ('38.4937', '-98.3804'),
    'Kentucky': ('37.5347', '-85.3021'),
    'Louisiana': ('31.0689', '-91.9968'),
    'Maine': ('45.3695', '-69.2428'),
    'Maryland': ('39.0550', '-76.7909'),
    'Massachusetts': ('42.2596', '-71.8083'),
    'Michigan': ('44.3467', '-85.4102'),
    'Minnesota': ('46.2807', '-94.3053'),
    'Mississippi': ('32.7364', '-89.6678'),
    'Missouri': ('38.3566', '-92.4580'),
    'Montana': ('47.0527', '-109.6333'),
    'Nebraska': ('41.5378', '-99.7951'),
    'Nevada': ('39.3289', '-116.6312'),
    'New Hampshire': ('43.6805', '-71.5811'),
    'New Jersey': ('40.1907', '-74.6728'),
    'New Mexico': ('34.4071', '-106.1126'),
    'New York': ('42.9538', '-75.5268'),
    'North Carolina': ('35.5557', '-79.3877'),
    'North Dakota': ('47.4501', '-100.4659'),
    'Ohio': ('40.2862', '-82.7937'),
    'Oklahoma': ('35.5889', '-97.4943'),
    'Oregon': ('43.9336', '-120.5583'),
    'Pennsylvania': ('40.8781', '-77.7996'),
    'Rhode Island': ('41.6762', '-71.5562'),
    'South Carolina': ('33.9169', '-80.8964'),
    'South Dakota': ('44.4443', '-100.2263'),
    'Tennessee': ('35.8580', '-86.3505'),
    'Texas': ('31.4757', '-99.3312'),
    'Utah': ('39.3055', '-111.6703'),
    'Vermont': ('44.0687', '-72.6658'),
    'Virginia': ('37.5215', '-78.8537'),
    'Washington': ('47.3826', '-120.4472'),
    'West Virginia': ('38.6409', '-80.6227'),
    'Wisconsin': ('44.6243', '-89.9941'),
    'Wyoming': ('42.9957', '-107.5512'),
    'District of Columbia': ('38.9101', '-77.0147')
}

# Convert string coordinates to float
state_coordinates = {k: (float(lat), float(lon)) for k, (lat, lon) in state_coordinates.items()}

# Add common state abbreviations for matching
state_to_full_name = {abbr: name for abbr, name in US_STATE_NAMES.items()}

# Fixed display scale: area is proportional to count through 64 saved records.
MAP_BASE_DIAMETER_PX = 8
MAP_SIZE_CAP_RECORDS = 64


def marker_diameter(count):
    try:
        count = float(count)
    except (TypeError, ValueError, OverflowError):
        return 0
    if not math.isfinite(count) or count <= 0:
        return 0
    return MAP_BASE_DIAMETER_PX * math.sqrt(min(count, MAP_SIZE_CAP_RECORDS))


MODE_LABELS = {"fixture": "Sample data", "demo": "Sample data", "live": "Bluesky"}
MODE_SUMMARIES = {
    "fixture": "United States · Demo",
    "demo": "United States · Demo",
    "live": "United States · Past 24 hours",
}

app.title = "Crisis Analysis"
app.layout = html.Main(className="app-shell", children=[
    html.Header(className="page-header", children=[
        html.Div([
            html.H1("Crisis Analysis"),
            html.P(MODE_SUMMARIES.get(PIPELINE_MODE, "United States"), className="subtitle"),
        ]),
        html.Span(MODE_LABELS.get(PIPELINE_MODE, "Dashboard"), className="mode-label"),
    ]),
    html.Div(id="pipeline-activity"),
    html.Section(className="map-section", **{"aria-labelledby": "map-heading"}, children=[
        html.Div(className="section-heading", children=[
            html.H2("Report locations", id="map-heading"),
            html.Div(className="map-size-key", children=[
                html.Span("Reports"),
                *[html.Span(className="size-key-item", children=[
                    html.Span(className="size-key-circle", style={
                        "width": f"{marker_diameter(count):g}px", "height": f"{marker_diameter(count):g}px",
                    }, **{"aria-hidden": "true"}),
                    html.Span(str(count)),
                ]) for count in (1, 4, 16)],
            ], **{"aria-label": "Circle sizes: 1, 4, and 16 reports"}),
        ]),
        dcc.Graph(id="crisis-map", className="map-graph", responsive=True,
                  config={"displayModeBar": False, "scrollZoom": False}),
    ]),
    html.Section(className="posts-section", children=[
        html.Div(className="posts-toolbar", children=[
            html.H2("Recent posts", id="posts-heading"),
            html.Div(className="state-filter", role="group", **{"aria-labelledby": "state-filter-label"}, children=[
                html.Label("Filter posts by state", id="state-filter-label", htmlFor="state-dropdown", className="sr-only"),
                dcc.Dropdown(id="state-dropdown", placeholder="All states", clearable=True),
            ]),
        ]),
        html.Div(id="posts-table"),
    ]),
    dcc.Interval(id="interval-component", interval=2000, n_intervals=0),
])


@server.get("/activity")
def activity():
    return {"mode": PIPELINE_MODE or "dashboard", **activity_snapshot()}


@app.callback(Output("pipeline-activity", "children"), Input("interval-component", "n_intervals"))
def update_activity(n_intervals):
    if PIPELINE_MODE != "live":
        return None
    status = activity_snapshot()
    collector = status.get('collector', {})
    phase = status.get('phase', 'starting')
    stale = activity_is_stale(status)
    message = None
    if collector.get('state') == 'paused':
        message = ('Collection paused. Analysis is delayed.' if stale else
                   'Collection paused. Analysis is waiting to retry.' if phase == 'error' else
                   'Collection paused. Processing saved posts.' if phase == 'processing' else
                   'Collection paused.')
    elif stale:
        message = "Live updates are delayed."
    elif phase == 'error':
        message = ("Analysis is paused. The usage limit has been reached."
                   if status.get('jev_max_calls') and status.get('jev_calls', 0) >= status['jev_max_calls']
                   else "Live updates are temporarily paused.")
    elif collector and collector.get('state') == 'backpressure':
        message = "Analysis is behind. New reports are delayed."
    elif collector and collector.get('state') != 'connected':
        message = "Live feed disconnected. Reconnecting."
    elif (collector.get('source_lag_seconds') or 0) > 60:
        message = "Live feed is catching up. New reports may be delayed."
    elif collector.get('oldest_pending_seconds', 0) >= 30:
        message = "Analysis is behind. New reports are delayed."
    elif collector.get('gap_events', 0):
        message = "Some earlier posts could not be recovered."
    def count(value):
        return value if type(value) is int and value >= 0 else None

    # Queue depth includes the leased batch until its save/acknowledgement succeeds.
    # Never present a stale collector snapshot as a current count.
    queued = count(collector.get('queue_depth')) if collector.get('state') != 'unavailable' else None
    # Acknowledgement is persistent and advances once per finished batch. The
    # processor's attempt counters can include retries and unfinished work.
    processed = count(collector.get('acknowledged')) if collector.get('state') != 'unavailable' else None
    total, checked = count(status.get('batch_received')), count(status.get('batch_processed'))
    batch_label, batch_value = 'Batch', '—'
    if not stale:
        if phase in ('processing', 'error') and total and checked is not None:
            batch_label = 'Batch paused' if phase == 'error' else 'Processing batch'
            batch_value = f'{min(checked, total):,} / {total:,}'
        elif phase == 'waiting':
            batch_value = 'Idle'
        elif phase == 'collecting':
            batch_value = 'Starting'
    return html.Div(className='activity-content', children=[
        html.Div(className='activity-counts', children=[
            html.Span(['Processed ', html.Strong(f'{processed:,}' if processed is not None else '—')],
                      title='Total completed since collection began, including posts filtered out.'),
            html.Span(['Queued ', html.Strong(f'{queued:,}' if queued is not None else '—')],
                      title='Posts awaiting completion, including the current batch.'),
            html.Span([f'{batch_label} ', html.Strong(batch_value)],
                      title='Posts checked in the current batch. Failed reviews remain queued.'),
        ], **{'aria-live': 'off'}),
        html.Div(message, className='activity-label warning', role='status',
                 **{'aria-live': 'polite'}) if message else None,
    ])


CHART_COLORS = {
    "Flood": "#2563eb", "Wildfire": "#c45f25", "Hurricane": "#7352a2",
    "Earthquake": "#927237", "Tsunami": "#087e8b", "Heatwave": "#b24949",
    "Cold Snap": "#357c9f", "Landslide": "#5d7868", "Pandemic": "#925979",
    "Volcanic Eruption": "#9f4935", "Solar Flare": "#a66b20",
}


def style_figure(fig):
    fig.update_layout(template="plotly_white", title=None,
                      font={"family": "Arial, sans-serif", "size": 12, "color": "#475569"},
                      paper_bgcolor="white", plot_bgcolor="white",
                      margin={"l": 18, "r": 18, "t": 12, "b": 40},
                      legend={"title_text": "", "orientation": "h", "y": -0.06, "x": 0},
                      uirevision="constant")
    return fig


@app.callback(
    Output('state-dropdown', 'options'),
    Input('interval-component', 'n_intervals')
)
def update_dropdown_options(n_intervals):
    try:
        df = load_dashboard_counts()
        return [{'label': state, 'value': state} for state in sorted(df['state'].dropna().unique()) if state]
    except Exception as e:
        print(f"Error updating dropdown: {e}")
        return []

def map_points_from_posts(posts):
    """Count saved records per resolved location without averaging different cities."""
    required = {"state", "city", "disasters"}
    if not required.issubset(posts.columns):
        raise ValueError("Post data is missing required map columns")
    points = {}
    states_by_name = {name.casefold(): name for name in state_coordinates}

    def clean(value):
        return "" if pd.isna(value) else str(value).strip()

    for row in us_records(posts).to_dict("records"):
        raw_state = clean(row.get("state"))
        state = state_to_full_name.get(raw_state.upper(), states_by_name.get(raw_state.casefold()))
        if not state:
            continue
        labels = row.get("disasters")
        if isinstance(labels, str):
            try:
                labels = ast.literal_eval(labels)
            except (ValueError, SyntaxError):
                labels = [labels] if labels.strip() and not labels.lstrip().startswith("[") else []
        if not isinstance(labels, list) or not labels or not isinstance(labels[0], str):
            continue
        # Match the existing state's first-disaster aggregation convention.
        disaster = labels[0]
        city = clean(row.get("city"))
        try:
            lat, lon = float(row.get("latitude")), float(row.get("longitude"))
            valid_coords = math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180
        except (TypeError, ValueError):
            valid_coords = False
        if city and valid_coords:
            location = f"{city}, {state}"
            precision = "City-level location"
        else:
            city = ""
            lat, lon = state_coordinates[state]
            location = state
            precision = "State centroid (approximate)"
        key = (state, city.casefold(), disaster, lat, lon)
        if key not in points:
            points[key] = dict(location=location, state=state, city=city, disaster=disaster,
                               lat=lat, lon=lon, precision=precision, count=0)
        points[key]["count"] += 1
    return sorted(points.values(), key=lambda point: (-point["count"], point["location"], point["disaster"]))


@app.callback(Output('crisis-map', 'figure'), Input('interval-component', 'n_intervals'))
def update_crisis_map(n_intervals):
    fig = go.Figure()
    try:
        # One atomic CSV snapshot gives actual counts for each city/state location.
        points = map_points_from_posts(load_dashboard_posts())
        for disaster in sorted({point["disaster"] for point in points}):
            group = [point for point in points if point["disaster"] == disaster]
            fig.add_trace(go.Scattergeo(
                lat=[point["lat"] for point in group], lon=[point["lon"] for point in group],
                text=[point["location"] for point in group], name=disaster, mode="markers",
                customdata=[[
                    point["count"], point["precision"],
                    "Display size capped; count is exact" if point["count"] > MAP_SIZE_CAP_RECORDS else "",
                ] for point in group],
                marker={
                    "size": [marker_diameter(point["count"]) for point in group],
                    "sizemode": "diameter", "sizeref": 1, "sizemin": 0,
                    "color": CHART_COLORS.get(disaster, "#526277"), "opacity": 0.75,
                    "line": {"color": "white", "width": 1},
                },
                hovertemplate=("<b>%{text}</b><br>%{customdata[0]:,d} reports"
                               "<br>%{customdata[1]}<br>%{customdata[2]}<extra>%{fullData.name}</extra>"),
            ))
        if not points:
            fig.add_annotation(text="No reports yet", x=0.5, y=0.5,
                               xref="paper", yref="paper", showarrow=False)
    except (OSError, ValueError, KeyError, pd.errors.ParserError):
        server.logger.exception("Could not load map locations")
        fig.add_annotation(text="Map unavailable. Retrying automatically.", x=0.5, y=0.5,
                           xref="paper", yref="paper", showarrow=False)
    fig.update_layout(
        geo=dict(scope="usa", projection_type="albers usa", showland=True,
                 landcolor="#f1f5f9", bgcolor="white", subunitcolor="#cbd5e1",
                 coastlinewidth=0.5, countrywidth=0.5, subunitwidth=0.5,
                 showlakes=True, lakecolor="white", showsubunits=True, showcountries=True, resolution=50),
        legend={"itemsizing": "constant"},
    )
    return style_figure(fig)

@app.callback(
    Output('posts-table', 'children'),
    [Input('state-dropdown', 'value'), Input('interval-component', 'n_intervals')]
)
def update_table(selected_state, n_intervals):
    try:
        posts = load_dashboard_posts()
        if selected_state:
            posts = posts[posts["state"] == selected_state]
        if posts.empty:
            message = ("No posts for this state yet. Choose another state."
                       if selected_state else "No reports yet. New posts will appear here.")
            return html.P(message,
                          className="empty-state")
        posts = posts.assign(_posted=pd.to_datetime(posts["created_at"], format="mixed", errors="coerce", utc=True))
        posts = posts.sort_values("_posted", ascending=False, kind="stable").head(30)

        def clean(value):
            return "" if pd.isna(value) else str(value)

        rows = []
        for _, row in posts.iterrows():
            synthetic = clean(row.get("author")) == "synthetic-demo"
            uri = clean(row.get("uri"))
            source = "Example" if synthetic else "Bluesky"
            if not synthetic and uri.startswith("at://"):
                pieces = uri[5:].split("/")
                if len(pieces) == 3 and pieces[1] == "app.bsky.feed.post":
                    source = html.A("View post", href=f"https://bsky.app/profile/{quote(pieces[0], safe=':')}/post/{quote(pieces[2], safe='')}",
                                    target="_blank", rel="noopener noreferrer")
            labels = clean(row.get("disasters"))
            try:
                parsed = ast.literal_eval(labels)
                if isinstance(parsed, list):
                    labels = ", ".join(str(item) for item in parsed)
            except (ValueError, SyntaxError):
                pass
            location = ", ".join(value for value in (clean(row.get("city")), clean(row.get("state"))) if value)
            location = location or "Unknown location"
            posted = row["_posted"].strftime("%b %d, %H:%M UTC") if pd.notna(row["_posted"]) else "Unknown date"
            metadata = [html.Span("Example")] if synthetic else [html.Span(posted), source]
            rows.append(html.Li(html.Article(className="report", children=[
                html.Div(className="report-context", children=[
                    html.H3(location, className="report-location"),
                    html.P(labels, className="report-type"),
                ]),
                html.Div(className="report-content", children=[
                    html.P(clean(row.get("text")), className="post-text"),
                    html.Div(metadata, className="post-meta"),
                ]),
            ])))
        return html.Ul(rows, className="reports-list", **{"aria-labelledby": "posts-heading"})
    except (OSError, ValueError, KeyError):
        return html.P("Posts are unavailable. Retrying automatically.", className="empty-state")

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=False, port=8051)
