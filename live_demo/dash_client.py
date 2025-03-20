from dash import Dash, dcc, html, Input, Output, callback
import pandas as pd
import plotly.express as px

# Load the data (would need to be a server query in a real app)
df = pd.read_csv('crisis_counts.csv')
posts_df = pd.read_csv('filtered_posts.csv')

# Create the Dash app
app = Dash(__name__)

app.layout = html.Div([
    html.H1("Crisis Counts Heatmap"),
    dcc.Graph(id='graph'),
    html.H2("Identified Crisis Posts"),
    dcc.Dropdown(
        id='location-dropdown',
        placeholder="Select a location",
    ),
    html.Div(id='posts-table')
])

@app.callback(
    Output('location-dropdown', 'options'),
    Input('interval-component', 'n_intervals')
)
def update_dropdown_options(n_intervals):
    df = pd.read_csv('crisis_counts.csv')
    return [{'label': loc, 'value': loc} for loc in df['location'].unique()]

@app.callback(
    Output('graph', 'figure'),
    Input('interval-component', 'n_intervals')
)
def update_graph(n_intervals):
    # Update the df with new data, will need to be a server query in a real app
    df = pd.read_csv('crisis_counts.csv')
    
    fig = px.scatter_geo(
        df, 
        lat='latitude', 
        lon='longitude', 
        size='count', 
        projection='equirectangular',
        hover_name='disaster_type',
        hover_data={'location': True,
                    'count': True, 
                    'avg_sentiment': True,
                    'severity': True,
                    'latitude': False,
                    'longitude': False},
        color='avg_sentiment',
        color_continuous_scale='Reds',
    )
    return fig

# Add an interval component to trigger the graph update
app.layout.children.append(
    dcc.Interval(
        id='interval-component',
        interval=5*1000,  # in milliseconds (e.g., 60 seconds)
        n_intervals=0
    )
)

@app.callback(
    Output('posts-table', 'children'),
    [Input('location-dropdown', 'value'), Input('interval-component', 'n_intervals')]
)
def update_table(selected_location, n_intervals):
    if selected_location is None:
        return html.Div()
    
    # Update the post_df with new data, will need to be a server query in a real app
    posts_df = pd.read_csv('filtered_posts.csv')

    filtered_posts = posts_df[posts_df['location'] == selected_location]
    
    columns_to_display = ['author', 'created_at', 'text', 'sentiment', 'disaster_type']
    return html.Table([
        html.Thead(html.Tr([html.Th(col) for col in columns_to_display])),
        html.Tbody([
            html.Tr([html.Td(filtered_posts.iloc[i][col]) for col in columns_to_display])
            for i in range(len(filtered_posts))
        ])
    ])

if __name__ == '__main__':
    app.run(debug=True)