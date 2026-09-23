from dash import Dash, dcc, html, Input, Output
import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go
import os
import ast
from datetime import datetime, timezone
from urllib.parse import quote

from pipeline_status import read_status
from gazetteer import US_STATE_NAMES
from us_scope import us_records
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
        status = read_status(DATA_DIR)
        if activity_is_stale(status) or status.get("phase") == "error":
            return {"status": "unavailable", "component": "collector"}, 503
    return {"status": "healthy", "mode": PIPELINE_MODE or "dashboard"}

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


MODE_LABELS = {"fixture": "Fixture demo", "demo": "Model demo", "live": "Live Bluesky"}
MODE_NOTES = {
    "fixture": "Synthetic post and predefined model response. Live NLP is not running.",
    "demo": "Real NLP and Supabase. Showing a synthetic example for rehearsal.",
    "live": "Real NLP and Supabase. New Bluesky posts are checked in batches; counts include the startup example.",
}
MODE_SUMMARIES = {
    "fixture": "Synthetic example · Live NLP is not running",
    "demo": "Synthetic example · Processed by the real model",
    "live": "Live posts and one labeled startup example · Unverified reports",
}

app.title = "Crisis Analysis"
app.layout = html.Main(className="app-shell", children=[
    html.Header(className="page-header", children=[
        html.Div([
            html.H1("Crisis Analysis"),
            html.P("Potential US crisis reports from public social posts.", className="subtitle"),
        ]),
        html.Span(MODE_LABELS.get(PIPELINE_MODE, "Dashboard"), className="mode-label"),
    ]),
    html.Section(className="activity-section", children=[
        html.Div(id="pipeline-activity", role="status", **{"aria-live": "polite"}),
        html.P(MODE_SUMMARIES.get(PIPELINE_MODE, "Showing the latest saved reports."), className="mode-note"),
    ]),
    html.Div(className="workspace", children=[
        html.Section(className="map-section", children=[
            html.Div(className="section-heading", children=[
                html.H2("Report locations"),
                html.Span("United States", className="secondary-label"),
            ]),
            dcc.Graph(id="crisis-map", className="map-graph", responsive=True,
                      config={"displayModeBar": False, "scrollZoom": False}),
            html.Div(className="map-size-key", children=[
                html.Span("Report records", className="section-note"),
                *[html.Span(className="size-key-item", children=[
                    html.Span(className="size-key-circle", style={
                        "width": f"{marker_diameter(count):g}px", "height": f"{marker_diameter(count):g}px",
                    }, **{"aria-hidden": "true"}),
                    html.Span(str(count)),
                ]) for count in (1, 4, 16)],
            ], **{"aria-label": "Circle size examples: 1, 4, and 16 report records"}),
            html.P("Circle area shows report counts, not affected area. Sizes cap at 64 records; hover for exact counts.", className="section-note"),
        ]),
        html.Aside(className="summary-section", children=[
            html.H2("Reports by state"),
            dcc.Graph(id="state-chart", className="state-graph", responsive=True,
                      config={"displayModeBar": False}),
            html.H2("Overview", className="overview-title"),
            html.Div(id="stats-table"),
            html.P("Resolved locations only. A city and its state count once.", className="section-note"),
        ]),
    ]),
    html.Section(className="posts-section", children=[
        html.Div(className="posts-toolbar", children=[
            html.Div([html.H2("Recent posts"),
                      html.P("Latest 30 US location records", className="section-note")]),
            html.Div(className="state-filter", children=[
                html.Label("Filter by state", htmlFor="state-dropdown"),
                dcc.Dropdown(id="state-dropdown", placeholder="All states", clearable=True),
            ]),
        ]),
        html.Div(id="posts-table", className="table-scroll", tabIndex=0,
                 **{"aria-label": "Recent crisis posts"}),
    ]),
    html.Footer([
        html.Span("Research prototype · Human review required"),
        html.Details([
            html.Summary("About the data"),
            html.P(MODE_NOTES.get(PIPELINE_MODE, "Showing the latest saved reports.")),
            html.P("Only locations resolved to the 50 US states or DC are shown. Foreign and unresolved locations are skipped. Counts are not verified incidents. Match labels explain the evidence, not statistical confidence. The dashboard refreshes every 5 seconds."),
            html.P("Circles count saved post/location records on a fixed scale. State-only points use approximate centroids. Repeated posts across batches can count again."),
        ]),
    ]),
    dcc.Interval(id="interval-component", interval=2000, n_intervals=0),
])


@server.get("/activity")
def activity():
    return {"mode": PIPELINE_MODE or "dashboard", **read_status(DATA_DIR)}


@app.callback(Output("pipeline-activity", "children"), Input("interval-component", "n_intervals"))
def update_activity(n_intervals):
    if PIPELINE_MODE != "live":
        return html.Span("Example ready" if PIPELINE_MODE in ("fixture", "demo") else "Saved reports",
                         className="activity-label")
    status = read_status(DATA_DIR)
    phase = status.get("phase", "starting")
    labels = {"starting": "Starting collection", "collecting": "Collecting posts",
              "processing": "Analyzing posts", "waiting": "Waiting for the next batch",
              "error": "Collection needs attention"}
    updated = status.get("updated_at")
    try:
        last_update = datetime.fromisoformat(updated)
        if activity_is_stale(status):
            phase = "stalled"
        time_label = last_update.strftime("%H:%M:%S UTC")
    except (TypeError, ValueError):
        time_label = "Waiting for first update"
    parts = [
        html.Span(labels.get(phase, "Updates delayed"),
                  className="activity-label warning" if phase in ("error", "stalled") else "activity-label"),
        html.Span(f"{status.get('posts_received', 0):,} posts collected"),
        html.Span(f"{status.get('posts_processed', 0):,} analyzed"),
        html.Span(f"Updated {time_label}" if updated else time_label, className="activity-time"),
    ]
    if status.get("model_errors", 0):
        parts.append(html.Span(f"{status['model_errors']:,} analysis errors", className="warning"))
    if status.get("relevance_mode") == "jev":
        parts.append(html.Span(f"{status.get('relevance_excluded', 0):,} records filtered for relevance"))
        if status.get("location_checked", 0):
            parts.append(html.Span(f"{status.get('location_resolved', 0):,} of {status['location_checked']:,} ambiguous locations resolved"))
        if status.get("location_errors", 0):
            parts.append(html.Span(f"{status['location_errors']:,} location checks unavailable", className="warning"))
        if status.get("relevance_errors", 0):
            parts.append(html.Span(f"{status['relevance_errors']:,} relevance checks unavailable", className="warning"))
    if phase == "error" and status.get("last_error"):
        parts.append(html.Span(status["last_error"], className="warning"))
    return parts


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


def parse_cities_list(cities_str):
    """Safely parse a string representation of a list of cities."""
    if not cities_str or pd.isna(cities_str):
        return []

    try:
        if isinstance(cities_str, str):
            cities_list = ast.literal_eval(cities_str)
            if isinstance(cities_list, list):
                return cities_list
    except (ValueError, SyntaxError):
        # If there's an error, just return empty list
        pass

    return []

@app.callback(
    Output('state-dropdown', 'options'),
    Input('interval-component', 'n_intervals')
)
def update_dropdown_options(n_intervals):
    try:
        # Load crisis data with explicit column names
        try:
            df = pd.read_csv(DATA_DIR / 'crisis_counts.csv',
                           quotechar='"',  # Use double quotes for quoted fields
                           escapechar='\\', # Use backslash as escape character
                           names=['country', 'state', 'disasters', 'count', 'avg_sentiment', 'cities', 'severity'],
                           header=0)  # First row is header
        except Exception as e:
            print(f"Error with standard CSV reader, trying alternative: {e}")
            # Try alternative reading approach with Python's csv module
            import csv

            with open(DATA_DIR / 'crisis_counts.csv', 'r') as f:
                reader = csv.reader(f, quotechar='"', escapechar='\\')
                headers = next(reader)  # Get header row
                data = []
                for row in reader:
                    if len(row) >= 7:  # Ensure we have at least 7 columns
                        data.append(row[:7])  # Take only the first 7 columns

            # Convert to DataFrame
            df = pd.DataFrame(data, columns=['country', 'state', 'disasters', 'count', 'avg_sentiment', 'cities', 'severity'])

        df = us_records(df)
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
        points = map_points_from_posts(pd.read_csv(DATA_DIR / "filtered_posts.csv"))
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
                hovertemplate=("<b>%{text}</b><br>%{customdata[0]:,d} report records"
                               "<br>%{customdata[1]}<br>%{customdata[2]}<extra>%{fullData.name}</extra>"),
            ))
        if not points:
            fig.add_annotation(text="No resolved locations yet", x=0.5, y=0.5,
                               xref="paper", yref="paper", showarrow=False)
    except (OSError, ValueError, KeyError, pd.errors.ParserError):
        server.logger.exception("Could not load map locations")
        fig.add_annotation(text="Map unavailable. Retrying on the next refresh.", x=0.5, y=0.5,
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
    Output('state-chart', 'figure'),
    Input('interval-component', 'n_intervals')
)
def update_state_chart(n_intervals):
    try:
        # Load crisis data with explicit column names
        try:
            df = pd.read_csv(DATA_DIR / 'crisis_counts.csv',
                            quotechar='"',  # Use double quotes for quoted fields
                            escapechar='\\', # Use backslash as escape character
                            names=['country', 'state', 'disasters', 'count', 'avg_sentiment', 'cities', 'severity'],
                            header=0)  # First row is header
        except Exception as e:
            print(f"Error with standard CSV reader, trying alternative: {e}")
            # Try alternative reading approach with Python's csv module
            import csv

            with open(DATA_DIR / 'crisis_counts.csv', 'r') as f:
                reader = csv.reader(f, quotechar='"', escapechar='\\')
                headers = next(reader)  # Get header row
                data = []
                for row in reader:
                    if len(row) >= 7:  # Ensure we have at least 7 columns
                        data.append(row[:7])  # Take only the first 7 columns

            # Convert to DataFrame
            df = pd.DataFrame(data, columns=['country', 'state', 'disasters', 'count', 'avg_sentiment', 'cities', 'severity'])

        df = us_records(df)
        # Convert numeric columns
        df['count'] = pd.to_numeric(df['count'], errors='coerce').fillna(1).astype(int)

        if df.empty:
            return px.bar(title="No data available")

        # Group by state and disaster type
        state_disaster_counts = df.groupby(['state', 'disasters']).agg(
            count=('count', 'sum')
        ).reset_index()

        # Create the bar chart
        fig = px.bar(
            state_disaster_counts,
            x='state',
            y='count',
            color='disasters',
            color_discrete_map=CHART_COLORS,
            title="Disaster Reports by State",
            labels={'count': 'Location records', 'state': 'State', 'disasters': 'Disaster type'}
        )
        fig.update_layout(showlegend=False)
        fig.update_xaxes(title=None)
        fig.update_yaxes(rangemode="tozero", gridcolor="#eef2f7", tickformat="d")
        return style_figure(fig)
    except Exception as e:
        print(f"Error updating state chart: {e}")
        return px.bar(title="Error loading data")

@app.callback(
    Output('posts-table', 'children'),
    [Input('state-dropdown', 'value'), Input('interval-component', 'n_intervals')]
)
def update_table(selected_state, n_intervals):
    try:
        posts = us_records(pd.read_csv(DATA_DIR / "filtered_posts.csv"))
        if selected_state:
            posts = posts[posts["state"] == selected_state]
        if posts.empty:
            message = ("No matching posts for this state yet. Try another state or clear the filter."
                       if selected_state else "No US crisis reports have resolved to a location yet.")
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
            location_detail = clean(row.get("location_detail"))
            if not location:
                location = clean(row.get("location_mentions")) or "Unresolved"
                location_detail = location_detail or "No supported US match"
            location_content = [html.Div(location)]
            if location_detail:
                location_content.append(html.Div(location_detail, className="section-note"))
            review = clean(row.get("location_review"))
            if review:
                location_content.append(html.Div(review, className="section-note"))
            posted = row["_posted"].strftime("%b %d, %H:%M UTC") if pd.notna(row["_posted"]) else "Unknown date"
            metadata = [html.Span("Example")] if synthetic else [html.Span(posted), source]
            rows.append(html.Tr([
                html.Td([html.P(clean(row.get("text")), className="post-text"),
                         html.Div(metadata, className="post-meta")], className="post-cell"),
                html.Td(location_content),
                html.Td([labels, html.Div("Relevance screened · Unverified", className="section-note")]
                        if clean(row.get("relevance_status")) == "passed" else labels),
                html.Td(clean(row.get("sentiment"))),
            ], className="example-row" if synthetic else ""))
        return html.Table([
            html.Thead(html.Tr([html.Th(label, scope="col") for label in ("Post", "Location", "Disaster", "Sentiment")])),
            html.Tbody(rows),
        ], className="posts-table")
    except (OSError, ValueError, KeyError):
        return html.P("Posts are temporarily unavailable. Retrying on the next refresh.", className="empty-state")

@app.callback(
    Output('stats-table', 'children'),
    Input('interval-component', 'n_intervals')
)
def update_stats(n_intervals):
    try:
        # Load crisis data with explicit column names
        try:
            df = pd.read_csv(DATA_DIR / 'crisis_counts.csv',
                            quotechar='"',  # Use double quotes for quoted fields
                            escapechar='\\', # Use backslash as escape character
                            names=['country', 'state', 'disasters', 'count', 'avg_sentiment', 'cities', 'severity'],
                            header=0)  # First row is header
        except Exception as e:
            print(f"Error with standard CSV reader, trying alternative: {e}")
            # Try alternative reading approach with Python's csv module
            import csv

            with open(DATA_DIR / 'crisis_counts.csv', 'r') as f:
                reader = csv.reader(f, quotechar='"', escapechar='\\')
                headers = next(reader)  # Get header row
                data = []
                for row in reader:
                    if len(row) >= 7:  # Ensure we have at least 7 columns
                        data.append(row[:7])  # Take only the first 7 columns

            # Convert to DataFrame
            df = pd.DataFrame(data, columns=['country', 'state', 'disasters', 'count', 'avg_sentiment', 'cities', 'severity'])

        df = us_records(df)
        # Convert numeric columns
        df['count'] = pd.to_numeric(df['count'], errors='coerce').fillna(1).astype(int)
        df['avg_sentiment'] = pd.to_numeric(df['avg_sentiment'], errors='coerce').fillna(0)

        if df.empty:
            return html.Div("No statistics available.")

        # Calculate statistics
        total_disasters = len(df['disasters'].unique())
        total_states = len(df['state'].unique())

        # Count cities - safely parse the cities column
        total_cities = 0
        all_cities = set()

        for cities_str in df['cities']:
            cities = parse_cities_list(cities_str)
            all_cities.update(cities)

        total_cities = len(all_cities)

        avg_sentiment = df['avg_sentiment'].mean()
        total_reports = df['count'].sum()

        return html.Table([
            html.Tr([html.Th("Location records", scope="row"), html.Td(total_reports)]),
            html.Tr([html.Th("Disaster types", scope="row"), html.Td(total_disasters)]),
            html.Tr([html.Th("States", scope="row"), html.Td(total_states)]),
            html.Tr([html.Th("Cities", scope="row"), html.Td(total_cities)]),
            html.Tr([html.Th("Average sentiment", scope="row"), html.Td(f"{avg_sentiment:.2f}")])
        ], className="stats-table")
    except Exception as e:
        print(f"Error updating stats: {e}")
        return html.P("Statistics are temporarily unavailable. Retrying on the next refresh.", className="empty-state")

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=False, port=8051)
