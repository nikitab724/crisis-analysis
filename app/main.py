# Plotly's Figure Friday challenge. See more info here: https://community.plotly.com/t/figure-friday-2024-week-32/86401
import dash
import pandas as pd
from dash import Dash, html, dcc, Input, Output, State, callback, Patch
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import plotly.graph_objects as go
import dash_leaflet as dl
from opencage.geocoder import OpenCageGeocode

app = Dash(external_stylesheets=[dbc.themes.BOOTSTRAP])

df = pd.read_csv('data/crisis_counts.csv')
df = df[df['severity'] > 0.0]

key = ''
geocoder = OpenCageGeocode(key)

mapchildren = [dl.TileLayer()]

for i, row in df.iterrows():
    loc = row['locations']
    result = geocoder.geocode(loc)
    coords = result[0]['geometry']
    severity = row['severity']
    mapchildren.append(dl.CircleMarker(center=coords, radius=severity*3+8, children=[dl.Tooltip(row['disasters'])]))

map = dl.Map(center=[39.01, -98.48], zoom=4, style={'width': '50%', 'height': '500px'}, children=mapchildren, id="map")

heading = html.H1("Crisis Analysis Map View",className="bg-secondary text-white p-2 mb-4")

app.layout = dbc.Container(
    [
        dcc.Store(id="store-selected", data={}),
        heading,
        map
    ],
    fluid=True,
)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
    
