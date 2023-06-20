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

households = ['Household 1', 'Household 2', 'Household 3', 'Household 4']
entities = ['voltage', 'current', 'power', 'energy', 'tde']

data_arrays = {}
current_timestamp = time.time()

for household_index, household in enumerate(households, start=1):
    household_data = {}
    for entity in entities:
        entity_data = []
        api_entity = f"sensor.athom_smart_plug_v2_{entity}_{household_index}"   #entity
        api_url = f"{api_url_base}{api_entity}"
        response = requests.get(api_url, headers=headers)
        data = response.json()
        entity_data = [(current_timestamp, float(data['state']))]   #timestamp
        household_data[entity] = entity_data
    data_arrays[household] = household_data

def aggregate_data(data_arrays):
    aggregated_data = {}
    num_households = len(households)
    current_timestamp = time.time()

    voltage_sum = sum([data_arrays[h]['voltage'][-1][1] for h in households])
    current_sum = sum([data_arrays[h]['current'][-1][1] for h in households])
    power_sum = sum([data_arrays[h]['power'][-1][1] for h in households])
    energy_sum = sum([data_arrays[h]['energy'][-1][1] for h in households])
    tde_sum = sum([data_arrays[h]['tde'][-1][1] for h in households])

    aggregated_data['Household 1'] = data_arrays['Household 1'].copy()
    aggregated_data['Household 1']['voltage'].append((current_timestamp, voltage_sum / num_households))
    aggregated_data['Household 1']['current'].append((current_timestamp, current_sum))
    aggregated_data['Household 1']['power'].append((current_timestamp, power_sum))
    aggregated_data['Household 1']['energy'].append((current_timestamp, energy_sum))
    aggregated_data['Household 1']['tde'].append((current_timestamp, tde_sum))

    return aggregated_data

@app.route('/')
def simulation():
    data = aggregate_data(data_arrays)
    selected_entities = entities 
    return render_template('simulation.html', households=['Household 1'], entities=entities, data=data, selected_entities=selected_entities, len=len, dash_app=dash_app)

@app.route('/schematic')
def schematic():
    data = aggregate_data(data_arrays)
    selected_entities = entities 
    return render_template('schematic.html', households=['Household 1'], entities=entities, data=data, selected_entities=selected_entities, len=len, dash_app=dash_app)

@dash_app.callback(
    dash.dependencies.Output('trend-chart', 'figure'),
    [dash.dependencies.Input('trend-dropdown', 'value')]
)

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
    aggregated_data = aggregate_data(data_arrays)
    return aggregated_data

if __name__ == '__main__':
    app.run(debug=True)