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

df = pd.read_csv('https://raw.githubusercontent.com/plotly/Figure-Friday/main/2024/week-32/irish-pay-gap.csv')
df['Report Link'] = df['Report Link'].apply(lambda x: f'[Report]({x})')
df['Company'] = df.apply(lambda row: f'[{row["Company Name"]}]({row["Company Site"]})', axis=1)
df.rename(columns={'Q1 Men': 'Q1 Male'}, inplace=True)

numeric_columns = [
   'Mean Hourly Gap', 'Median Hourly Gap', 'Mean Bonus Gap', 'Median Bonus Gap', 'Mean Hourly Gap Part Time',
   'Median Hourly Gap Part Time', 'Mean Hourly Gap Part Temp', 'Median Hourly Gap Part Temp', 'Percentage Bonus Paid Female',
   'Percentage Bonus Paid Male', 'Percentage BIK Paid Female', 'Percentage BIK Paid Male', 'Q1 Female', 'Q1 Male', 'Q2 Female',
   'Q2 Male', 'Q3 Female', 'Q3 Male', 'Q4 Female', 'Q4 Male', 'Percentage Employees Female', 'Percentage Employees Male'
]

key = '72aeb073b8634354b6820656ddd13018'
geocoder = OpenCageGeocode(key)

query = u'North Carolina'
results = geocoder.geocode(query)

print(u'%f;%f;%s;%s' % (results[0]['geometry']['lat'],
                        results[0]['geometry']['lng'],
                        results[0]['components']['country_code'],
                        results[0]['annotations']['timezone']['name']))

initial_location = results[0]['geometry']

tweet_text_title = html.H3("Tweet Text",className="bg-secondary text-white p-2 mb-4")

tweet_text = html.P("PHOTOS: Deadly wildfires rage in California")

tweet_info_title = html.H3("Tweet Info",className="bg-secondary text-white p-2 mb-4")

tweet_info = html.P("IS A DISASTER")

tweet_info2 = html.P("IS NOT HUMANITARIAN")

tweet_info3 = html.P("SEVERITY: Severe")

title_string = "Extracted Tweet Location"

map_title = html.H3(title_string,className="bg-secondary text-white p-2 mb-4")

map = dl.Map(center=initial_location, zoom=4, style={'width': '50%', 'height': '500px'}, children=[
        dl.TileLayer(),  # Adds the map tiles
        dl.Marker(position=initial_location)  # Initial marker (Dublin)
    ], id="map")


company_dropdown = html.Div(
    [
        dbc.Label("Select a Company", html_for="company_dropdown"),
        dcc.Dropdown(
            id="company-dropdown",
            options=sorted(df["Company Name"].unique()),
            value='Ryanair',
            clearable=False,
            maxHeight=600,
            optionHeight=50
        ),
    ],  className="mb-4",
)

year_radio = html.Div(
    [
        dbc.Label("Select Year", html_for="date-checklist"),
        dbc.RadioItems(
            options=[2023, 2022],
            value=2023,
            id="year-radio",
        ),
    ],
    className="mb-4",
)

control_panel = dbc.Card(
    dbc.CardBody(
        [year_radio, company_dropdown ],
        className="bg-light",
    ),
    className="mb-4"
)

heading = html.H1("Crisis Analysis Single Tweet View",className="bg-secondary text-white p-2 mb-4")

about_card = dcc.Markdown(
    """
    This is a demo of our crisis analysis model. The UI and model are in progress.
    """)

data_card = dcc.Markdown(
    """
    Starting from 2022, Gender Pay Gap Reporting is a regulatory requirement that mandates employers in Ireland with
     more than 250 employees to publish information on their gender pay gap.
     
     [Data source](https://paygap.ie/)
     
     [Data source GitHub](https://github.com/zenbuffy/irishGenderPayGap/tree/main)
     
     This site was created for Plotly's Figure Friday challenge. For additional data visualizations of this dataset and
      to join the conversation, visit the [Plotly Community Forum](https://community.plotly.com/t/figure-friday-2024-week-32/86401)
    """
)

info = dbc.Accordion([
    dbc.AccordionItem(about_card, title="About Crisis Analysis", ),
    dbc.AccordionItem(data_card, title="Data Source")
],  start_collapsed=True)

def make_grid():
    grid = dag.AgGrid(
        id="grid",
        rowData=df.to_dict("records"),
        columnDefs=[
          {"field": "Company", "cellRenderer": "markdown", "linkTarget": "_blank",  "initialWidth":250, "pinned": "left" },
          {"field": "Report Link", "cellRenderer": "markdown", "linkTarget": "_blank", "floatingFilter": False},
          {"field": "Report Year" }] +
        [{"field": c} for c in numeric_columns],
        defaultColDef={"filter": True, "floatingFilter": True,  "wrapHeaderText": True, "autoHeaderHeight": True, "initialWidth": 125 },
        dashGridOptions={},
        filterModel={'Report Year': {'filterType': 'number', 'type': 'equals', 'filter': 2023}},
        rowClassRules = {"bg-secondary text-dark bg-opacity-25": "params.node.rowPinned === 'top' | params.node.rowPinned === 'bottom'"},
        style={"height": 600, "width": "100%"}
    )
    return grid


app.layout = dbc.Container(
    [
        dcc.Store(id="store-selected", data={}),
        heading,
        tweet_text_title,
        tweet_text,
        tweet_info_title,
        tweet_info,
        tweet_info2,
        tweet_info3,
        map_title,
        map
    ],
    fluid=True,
)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
    
