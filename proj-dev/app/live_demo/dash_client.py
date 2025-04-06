from dash import Dash, dcc, html, Input, Output, callback
import pandas as pd
import plotly.express as px
import os
import ast  # For safely evaluating string representations of lists
import plotly.graph_objects as go
from gazetteer import load_gazetteer, build_location_dict, lookup_city_state_country, US_STATE_NAMES

# Create the Dash app
app = Dash(__name__)

# Load gazetteer data for city coordinates
APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GAZETTEER_PATH = os.path.join(APP_DIR, "data", "US.txt")

try:
    gazetteer_df = load_gazetteer(GAZETTEER_PATH)
    location_dict = build_location_dict(gazetteer_df)
    print(f"Loaded gazetteer with {len(gazetteer_df)} locations")
except Exception as e:
    print(f"Error loading gazetteer: {e}")
    gazetteer_df = None
    location_dict = None

# Load initial data if available
try:
    if os.path.exists('crisis_counts.csv'):
        df = pd.read_csv('crisis_counts.csv')
    else:
        df = pd.DataFrame()
        
    if os.path.exists('filtered_posts.csv'):
        posts_df = pd.read_csv('filtered_posts.csv')
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

app.layout = html.Div([
    html.H1("Disaster Monitoring Dashboard", style={'textAlign': 'center'}),
    
    html.Div([
        html.Div([
            html.H2("Crisis Map"),
            dcc.Graph(id='crisis-map', style={'height': '70vh'}),
        ], style={'width': '60%', 'display': 'inline-block', 'verticalAlign': 'top'}),
        
        html.Div([
            html.H2("Disaster Distribution by State"),
            dcc.Graph(id='state-chart'),
            html.H2("Disaster Statistics"),
            html.Div(id='stats-table'),
        ], style={'width': '40%', 'display': 'inline-block', 'verticalAlign': 'top', 'paddingLeft': '20px'}),
    ]),
    
    html.Div([
        html.H2("Recent Disaster Posts"),
        dcc.Dropdown(
            id='state-dropdown',
            placeholder="Select a state",
        ),
        html.Div(id='posts-table'),
    ]),
    
    # Add an interval component to trigger updates
    dcc.Interval(
        id='interval-component',
        interval=5*1000,  # in milliseconds (5 seconds)
        n_intervals=0
    )
])

def get_city_coordinates(city_name, state_name):
    """Get latitude and longitude for a city using the gazetteer data."""
    if gazetteer_df is None or location_dict is None:
        return None, None
        
    # Normalize city name
    if not city_name:
        return None, None
        
    city_name = city_name.lower().strip()
    
    # Look up in location_dict
    if city_name not in location_dict:
        return None, None
        
    # Get matching rows
    row_indices = location_dict[city_name]
    if not row_indices:
        return None, None
        
    matches = gazetteer_df.loc[row_indices]
    
    # Filter by state if provided
    if state_name:
        state_abbr = None
        for abbr, name in US_STATE_NAMES.items():
            if name == state_name:
                state_abbr = abbr
                break
                
        if state_abbr:
            state_matches = matches[matches['stateCode'] == state_abbr]
            if not state_matches.empty:
                matches = state_matches
    
    # If no matches, return None
    if matches.empty:
        return None, None
    
    # Get the best match (highest population)
    best_match = matches.sort_values('population', ascending=False).iloc[0]
    
    return best_match['latitude'], best_match['longitude']

def parse_cities_list(cities_str):
    """Safely parse a string representation of a list of cities."""
    if not cities_str or pd.isna(cities_str):
        return []
    
    try:
        if isinstance(cities_str, str):
            # Remove quotes and brackets for cleaner display
            cities_str = cities_str.replace("'", '"')  # Replace single quotes with double quotes
            cities_list = ast.literal_eval(cities_str)
            if isinstance(cities_list, list):
                return cities_list
    except:
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
            df = pd.read_csv('crisis_counts.csv', 
                           quotechar='"',  # Use double quotes for quoted fields
                           escapechar='\\', # Use backslash as escape character
                           names=['country', 'state', 'disasters', 'count', 'avg_sentiment', 'cities', 'severity'],
                           header=0)  # First row is header
        except Exception as e:
            print(f"Error with standard CSV reader, trying alternative: {e}")
            # Try alternative reading approach with Python's csv module
            import csv
            
            with open('crisis_counts.csv', 'r') as f:
                reader = csv.reader(f, quotechar='"', escapechar='\\')
                headers = next(reader)  # Get header row
                data = []
                for row in reader:
                    if len(row) >= 7:  # Ensure we have at least 7 columns
                        data.append(row[:7])  # Take only the first 7 columns
            
            # Convert to DataFrame
            df = pd.DataFrame(data, columns=['country', 'state', 'disasters', 'count', 'avg_sentiment', 'cities', 'severity'])
        
        return [{'label': state, 'value': state} for state in df['state'].unique() if state]
    except Exception as e:
        print(f"Error updating dropdown: {e}")
        return []

@app.callback(
    Output('crisis-map', 'figure'),
    Input('interval-component', 'n_intervals')
)
def update_crisis_map(n_intervals):
    try:
        # Load crisis data with explicit column names
        try:
            df = pd.read_csv('crisis_counts.csv', 
                            quotechar='"',  # Use double quotes for quoted fields
                            escapechar='\\', # Use backslash as escape character
                            names=['country', 'state', 'disasters', 'count', 'avg_sentiment', 'cities', 'severity'],
                            header=0)  # First row is header
        except Exception as e:
            print(f"Error with standard CSV reader, trying alternative: {e}")
            # Try alternative reading approach with Python's csv module
            import csv
            import io
            
            with open('crisis_counts.csv', 'r') as f:
                reader = csv.reader(f, quotechar='"', escapechar='\\')
                headers = next(reader)  # Get header row
                data = []
                for row in reader:
                    if len(row) >= 7:  # Ensure we have at least 7 columns
                        data.append(row[:7])  # Take only the first 7 columns
            
            # Convert to DataFrame
            df = pd.DataFrame(data, columns=['country', 'state', 'disasters', 'count', 'avg_sentiment', 'cities', 'severity'])
        
        # Convert numeric columns
        df['count'] = pd.to_numeric(df['count'], errors='coerce').fillna(1).astype(int)
        df['avg_sentiment'] = pd.to_numeric(df['avg_sentiment'], errors='coerce').fillna(0)
        df['severity'] = pd.to_numeric(df['severity'], errors='coerce').fillna(0)
        
        if df.empty:
            return px.scatter_geo(title="No data available")
        
        # Prepare data for the map - include both state and city markers
        map_data = []
        
        # US state boundaries for the map
        usa_map = go.Figure(data=go.Scattergeo(
            locationmode='USA-states',
            lon = [],
            lat = [],
            text = [],
            mode = 'markers',
            marker_opacity=0,
            showlegend=False
        ))
        
        # Process each crisis record
        for _, row in df.iterrows():
            state_name = row['state']
            state_full = state_to_full_name.get(state_name, state_name)
            
            # Get state coordinates as a fallback
            if state_full in state_coordinates:
                state_lat, state_lon = state_coordinates[state_full]
            else:
                state_lat, state_lon = None, None
                
            # Parse cities list
            cities = parse_cities_list(row['cities'])
            
            # If we have cities, plot each one
            if cities:
                for city in cities:
                    # Try to get city coordinates from gazetteer
                    city_lat, city_lon = get_city_coordinates(city, state_name)
                    
                    # If coordinates found, add city marker
                    if city_lat and city_lon:
                        map_data.append({
                            'state': state_name,
                            'full_state': state_full,
                            'lat': city_lat,
                            'lon': city_lon,
                            'count': row['count'],
                            'disaster': row['disasters'],
                            'city': city,
                            'severity': row['severity'] if 'severity' in row else 1.0,
                            'sentiment': row['avg_sentiment']
                        })
            
            # Always add a state marker as fallback if no cities with coordinates were found
            if not any(d['state'] == state_name for d in map_data) and state_lat and state_lon:
                map_data.append({
                    'state': state_name,
                    'full_state': state_full,
                    'lat': state_lat,
                    'lon': state_lon,
                    'count': row['count'],
                    'disaster': row['disasters'],
                    'city': 'State-level data',
                    'severity': row['severity'] if 'severity' in row else 1.0,
                    'sentiment': row['avg_sentiment']
                })
        
        if not map_data:
            return px.scatter_geo(title="No valid location data available")
            
        map_df = pd.DataFrame(map_data)
        
        # Create the map with city-level markers
        fig = px.scatter_geo(
            map_df,
            lat='lat',
            lon='lon',
            size='count',  # Size by count of reports
            color='disaster',  # Color by disaster type
            hover_name='full_state',
            hover_data={
                'lat': False,
                'lon': False,
                'count': True,
                'city': True,
                'sentiment': True,
                'severity': False
            },
            scope='usa',
            title="Crisis Reports Across the United States",
            size_max=30,  # Maximum marker size
        )
        
        fig.update_layout(
            legend_title_text='Disaster Type',
            geo=dict(
                showland=True,
                landcolor='rgb(217, 217, 217)',
                coastlinewidth=0.5,
                countrywidth=0.5,
                subunitwidth=0.5,
                showlakes=True,
                lakecolor='rgb(255, 255, 255)',
                showsubunits=True,
                showcountries=True,
                resolution=50
            )
        )
        
        return fig
    except Exception as e:
        print(f"Error updating crisis map: {e}")
        import traceback
        traceback.print_exc()
        return px.scatter_geo(title=f"Error loading map data: {str(e)}")

@app.callback(
    Output('state-chart', 'figure'),
    Input('interval-component', 'n_intervals')
)
def update_state_chart(n_intervals):
    try:
        # Load crisis data with explicit column names
        try:
            df = pd.read_csv('crisis_counts.csv', 
                            quotechar='"',  # Use double quotes for quoted fields
                            escapechar='\\', # Use backslash as escape character
                            names=['country', 'state', 'disasters', 'count', 'avg_sentiment', 'cities', 'severity'],
                            header=0)  # First row is header
        except Exception as e:
            print(f"Error with standard CSV reader, trying alternative: {e}")
            # Try alternative reading approach with Python's csv module
            import csv
            
            with open('crisis_counts.csv', 'r') as f:
                reader = csv.reader(f, quotechar='"', escapechar='\\')
                headers = next(reader)  # Get header row
                data = []
                for row in reader:
                    if len(row) >= 7:  # Ensure we have at least 7 columns
                        data.append(row[:7])  # Take only the first 7 columns
            
            # Convert to DataFrame
            df = pd.DataFrame(data, columns=['country', 'state', 'disasters', 'count', 'avg_sentiment', 'cities', 'severity'])
        
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
            title="Disaster Reports by State",
            labels={'count': 'Number of Reports', 'state': 'State', 'disasters': 'Disaster Type'}
        )
        
        return fig
    except Exception as e:
        print(f"Error updating state chart: {e}")
        return px.bar(title="Error loading data")

@app.callback(
    Output('posts-table', 'children'),
    [Input('state-dropdown', 'value'), Input('interval-component', 'n_intervals')]
)
def update_table(selected_state, n_intervals):
    if selected_state is None:
        return html.Div("Select a state to view related posts.")
    
    try:
        # Read filtered_posts.csv with more robust parsing
        try:
            posts_df = pd.read_csv('filtered_posts.csv', 
                                 quotechar='"',
                                 escapechar='\\')
        except Exception as e:
            print(f"Error with standard CSV reader for posts, trying alternative: {e}")
            # Try alternative reading approach with Python's csv module
            import csv
            
            with open('filtered_posts.csv', 'r') as f:
                reader = csv.reader(f, quotechar='"', escapechar='\\')
                headers = next(reader)  # Get header row
                data = []
                for row in reader:
                    # Ensure row has enough columns to match headers
                    while len(row) < len(headers):
                        row.append('')  # Pad with empty strings if needed
                    data.append(row[:len(headers)])  # Take only columns that match headers
            
            # Convert to DataFrame
            posts_df = pd.DataFrame(data, columns=headers)
        
        filtered_posts = posts_df[posts_df['state'] == selected_state]
        
        if filtered_posts.empty:
            return html.Div("No posts found for this state.")
        
        columns_to_display = ['text', 'disasters', 'city', 'state', 'sentiment', 'polarity']
        
        # Function to safely convert any value to string
        def safe_str(val):
            if isinstance(val, (list, dict)):
                return str(val)
            elif isinstance(val, str) and (val.startswith('[') or val.startswith('{')):
                try:
                    # Try to evaluate if it's a string representation of a list/dict
                    return str(eval(val))
                except:
                    return val
            else:
                return str(val)
        
        return html.Table([
            html.Thead(html.Tr([html.Th(col) for col in columns_to_display])),
            html.Tbody([
                html.Tr([html.Td(safe_str(filtered_posts.iloc[i][col])) for col in columns_to_display])
                for i in range(len(filtered_posts))
            ])
        ])
    except Exception as e:
        print(f"Error updating posts table: {e}")
        return html.Div(f"Error loading posts: {e}")

@app.callback(
    Output('stats-table', 'children'),
    Input('interval-component', 'n_intervals')
)
def update_stats(n_intervals):
    try:
        # Load crisis data with explicit column names
        try:
            df = pd.read_csv('crisis_counts.csv', 
                            quotechar='"',  # Use double quotes for quoted fields
                            escapechar='\\', # Use backslash as escape character
                            names=['country', 'state', 'disasters', 'count', 'avg_sentiment', 'cities', 'severity'],
                            header=0)  # First row is header
        except Exception as e:
            print(f"Error with standard CSV reader, trying alternative: {e}")
            # Try alternative reading approach with Python's csv module
            import csv
            
            with open('crisis_counts.csv', 'r') as f:
                reader = csv.reader(f, quotechar='"', escapechar='\\')
                headers = next(reader)  # Get header row
                data = []
                for row in reader:
                    if len(row) >= 7:  # Ensure we have at least 7 columns
                        data.append(row[:7])  # Take only the first 7 columns
            
            # Convert to DataFrame
            df = pd.DataFrame(data, columns=['country', 'state', 'disasters', 'count', 'avg_sentiment', 'cities', 'severity'])
        
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
            html.Tr([html.Th("Total Reports"), html.Td(total_reports)]),
            html.Tr([html.Th("Total Unique Disasters"), html.Td(total_disasters)]),
            html.Tr([html.Th("Total States"), html.Td(total_states)]),
            html.Tr([html.Th("Total Cities"), html.Td(total_cities)]),
            html.Tr([html.Th("Average Sentiment"), html.Td(f"{avg_sentiment:.2f}")])
        ])
    except Exception as e:
        print(f"Error updating stats: {e}")
        return html.Div(f"Error loading statistics: {e}")

if __name__ == '__main__':
    app.run(debug=True, port=8051)