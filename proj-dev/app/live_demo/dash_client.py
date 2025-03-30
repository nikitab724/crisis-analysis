from dash import Dash, dcc, html, Input, Output, callback
import pandas as pd
import plotly.express as px
import os

# Create the Dash app
app = Dash(__name__)

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

app.layout = html.Div([
    html.H1("Disaster Monitoring Dashboard"),
    html.Div([
        html.H2("Disaster Distribution by State"),
        dcc.Graph(id='state-chart'),
        html.H2("Recent Disaster Posts"),
        dcc.Dropdown(
            id='state-dropdown',
            placeholder="Select a state",
        ),
        html.Div(id='posts-table'),
        html.H2("Disaster Statistics"),
        html.Div(id='stats-table')
    ])
])

@app.callback(
    Output('state-dropdown', 'options'),
    Input('interval-component', 'n_intervals')
)
def update_dropdown_options(n_intervals):
    try:
        df = pd.read_csv('crisis_counts.csv')
        return [{'label': state, 'value': state} for state in df['state'].unique() if state]
    except Exception as e:
        print(f"Error updating dropdown: {e}")
        return []

@app.callback(
    Output('state-chart', 'figure'),
    Input('interval-component', 'n_intervals')
)
def update_state_chart(n_intervals):
    try:
        df = pd.read_csv('crisis_counts.csv')
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
        return html.Div()
    
    try:
        posts_df = pd.read_csv('filtered_posts.csv')
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
        df = pd.read_csv('crisis_counts.csv')
        
        if df.empty:
            return html.Div("No statistics available.")
        
        # Calculate statistics
        total_disasters = len(df['disasters'].unique())
        total_states = len(df['state'].unique())
        
        # Safely parse cities - handle string representation of lists
        total_cities = 0
        for cities_str in df['cities']:
            try:
                if isinstance(cities_str, str):
                    cities_list = eval(cities_str)
                    if isinstance(cities_list, list):
                        total_cities += len(cities_list)
            except:
                # Skip if there's an error parsing the cities
                pass
                
        avg_sentiment = df['avg_sentiment'].mean()
        
        return html.Table([
            html.Tr([html.Th("Total Unique Disasters"), html.Td(total_disasters)]),
            html.Tr([html.Th("Total States"), html.Td(total_states)]),
            html.Tr([html.Th("Total Cities"), html.Td(total_cities)]),
            html.Tr([html.Th("Average Sentiment"), html.Td(f"{avg_sentiment:.2f}")])
        ])
    except Exception as e:
        print(f"Error updating stats: {e}")
        return html.Div(f"Error loading statistics: {e}")

# Add an interval component to trigger updates
app.layout.children.append(
    dcc.Interval(
        id='interval-component',
        interval=2*1000,  # in milliseconds (2 seconds)
        n_intervals=0
    )
)

if __name__ == '__main__':
    app.run_server(debug=True, port=8051)