import requests
import plotly.graph_objs as go
import pandas as pd
from flask import Flask, render_template, jsonify
import dash
from dash import dcc, html
import time

app = Flask(__name__)
dash_app = dash.Dash(__name__, server=app, url_base_pathname='/trend/')
dash_app.layout = html.Div([])

api_url_base = 'https://9j0ph1l4vjsb4pyu1gnt0ennbnqapvik.ui.nabu.casa/api/states/'
headers = {'Authorization': 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJhNjhjMzg1YWQ3MTA0YmVlOGU5MTM2MTJmNTBhMTg4ZCIsImlhdCI6MTY3ODkyNTI0NSwiZXhwIjoxOTk0Mjg1MjQ1fQ.eLdOdYA5MCdQIQW84ZqJ2ZyXzhy2deOsqG1NRjW7Y5g'}

households = ['household_1', 'household_2', 'household_3', 'household_4']
entities = ['voltage', 'current', 'power', 'energy', 'tde']

data_arrays = {}

for household_index, household in enumerate(households, start=1):
    household_data = {}
    for entity in entities:
        entity_data = []
        api_entity = f"sensor.athom_smart_plug_v2_{entity}_{household_index}"
        api_url = f"{api_url_base}{api_entity}"
        response = requests.get(api_url, headers=headers)
        data = response.json()
        entity_data = [float(data['state'])]
        household_data[entity] = entity_data
    data_arrays[household] = household_data

@app.route('/')
def simulation():
    data = {}
    for household in households:
        household_data = {}
        for entity in entities:
            entity_data = data_arrays[household][entity]
            household_data[entity] = entity_data
        data[household] = household_data
    selected_entities = entities 
    return render_template('simulation.html', households=households, entities=entities, data=data, selected_entities=selected_entities, len=len, dash_app=dash_app)

@dash_app.callback(
    dash.dependencies.Output('trend-chart', 'figure'),
    [dash.dependencies.Input('trend-dropdown', 'value')]
)
def update_trend(selected_entities):
    data = []
    for entity in selected_entities:
        for household in households:
            entity_data = data_arrays[household][entity]
            trace = go.Scatter(
                x=list(range(1, len(entity_data) + 1)),
                y=entity_data,
                mode='lines',
                name=household + ' ' + entity
            )
            data.append(trace)

    layout = go.Layout(
        title='Selected Entities Trend',
        xaxis=dict(title='Time'),
        yaxis=dict(title='Value'),
        margin=dict(l=50, r=50, b=50, t=50),
        legend=dict(orientation='h', xanchor='center', x=0.5, y=-0.1),
    )

    fig = go.Figure(data=data, layout=layout)
    return fig.to_dict()

@dash_app.server.route('/trend/')
def trend():
    selected_entities = entities.copy()
    trend_dropdown = dcc.Dropdown(
        id='trend-dropdown',
        options=[{'label': entity.capitalize(), 'value': entity} for entity in entities],
        value=selected_entities,
        multi=True
    )
    trend_chart = dcc.Graph(id='trend-chart', figure=update_trend(selected_entities))

    return html.Div([
        html.H1('Selected Entities Trend'),
        trend_dropdown,
        trend_chart
    ])

import time

@app.route('/fetch_data')
def fetch_data():
    global data_arrays
    current_timestamp = time.time()
    for household_index, household in enumerate(households, start=1):
        for entity in entities:
            api_entity = f"sensor.athom_smart_plug_v2_{entity}_{household_index}"
            api_url = f"{api_url_base}{api_entity}"
            response = requests.get(api_url, headers=headers)
            data = response.json()
            data_arrays[household][entity].append((current_timestamp, float(data['state'])))
    return data_arrays

if __name__ == '__main__':
    app.run(debug=True)
