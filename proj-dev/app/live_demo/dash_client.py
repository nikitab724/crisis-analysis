from dash import Dash, dcc, html, Input, Output, callback
import pandas as pd
import plotly.express as px

# Load the data (would need to be a server query in a real app)
df = pd.read_csv('crisis_counts.csv')
posts_df = pd.read_csv('filtered_posts.csv')

# Create the Dash app
app = Dash(__name__)

app.layout = html.Div([
    html.H1("Disaster Monitoring Dashboard"),
    html.Div([
        html.H2("Disaster Heatmap"),
        dcc.Graph(id='heatmap'),
        html.H2("Recent Disaster Posts"),
        dcc.Dropdown(
            id='location-dropdown',
            placeholder="Select a location",
        ),
        html.Div(id='posts-table'),
        html.H2("Disaster Statistics"),
        html.Div(id='stats-table')
    ])
])

@app.callback(
    Output('location-dropdown', 'options'),
    Input('interval-component', 'n_intervals')
)
def update_dropdown_options(n_intervals):
    df = pd.read_csv('crisis_counts.csv')
    return [{'label': loc, 'value': loc} for loc in df['locations'].unique()]

@app.callback(
    Output('heatmap', 'figure'),
    Input('interval-component', 'n_intervals')
)
def update_heatmap(n_intervals):
    df = pd.read_csv('crisis_counts.csv')
    
    fig = px.scatter_geo(
        df, 
        lat='latitude', 
        lon='longitude', 
        size='count', 
        projection='equirectangular',
        hover_name='disasters',
        hover_data={'locations': True,
                   'count': True, 
                   'avg_sentiment': True,
                   'severity': True,
                   'latitude': False,
                   'longitude': False},
        color='avg_sentiment',
        color_continuous_scale='Reds',
    )
    fig.update_layout(
        title="Disaster Reports by Location",
        geo=dict(
            showframe=False,
            showcoastlines=True,
            projection_type='equirectangular'
        )
    )
    return fig

@app.callback(
    Output('posts-table', 'children'),
    [Input('location-dropdown', 'value'), Input('interval-component', 'n_intervals')]
)
def update_table(selected_location, n_intervals):
    if selected_location is None:
        return html.Div()
    
    posts_df = pd.read_csv('filtered_posts.csv')
    filtered_posts = posts_df[posts_df['locations'].apply(lambda x: selected_location in x)]
    
    columns_to_display = ['text', 'disasters', 'sentiment', 'polarity', 'city', 'state']
    return html.Table([
        html.Thead(html.Tr([html.Th(col) for col in columns_to_display])),
        html.Tbody([
            html.Tr([html.Td(filtered_posts.iloc[i][col]) for col in columns_to_display])
            for i in range(len(filtered_posts))
        ])
    ])

@app.callback(
    Output('stats-table', 'children'),
    Input('interval-component', 'n_intervals')
)
def update_stats(n_intervals):
    df = pd.read_csv('crisis_counts.csv')
    
    # Calculate statistics
    total_disasters = len(df['disasters'].unique())
    total_locations = len(df['locations'].unique())
    avg_severity = df['severity'].mean()
    
    return html.Table([
        html.Tr([html.Th("Total Unique Disasters"), html.Td(total_disasters)]),
        html.Tr([html.Th("Total Locations"), html.Td(total_locations)]),
        html.Tr([html.Th("Average Severity"), html.Td(f"{avg_severity:.2f}")])
    ])

# Add an interval component to trigger updates
app.layout.children.append(
    dcc.Interval(
        id='interval-component',
        interval=5*1000,  # in milliseconds (5 seconds)
        n_intervals=0
    )
)

if __name__ == '__main__':
    app.run(debug=True)