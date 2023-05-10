import requests
import pandas as pd
from flask import Flask, render_template, jsonify, request
import dash
from dash import dcc, html
import time
from datetime import datetime

app = Flask(__name__)
dash_app = dash.Dash(__name__, server=app, url_base_pathname='/trend/')
dash_app.layout = html.Div([])

api_url_base = 'https://9j0ph1l4vjsb4pyu1gnt0ennbnqapvik.ui.nabu.casa/api/states/'
api_url_base_hist = 'https://9j0ph1l4vjsb4pyu1gnt0ennbnqapvik.ui.nabu.casa/api/history/period/{start_timestamp}+00:00?end_time={end_timestamp}%2B00%3A00&filter_entity_id='
headers = {'Authorization': 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJhNjhjMzg1YWQ3MTA0YmVlOGU5MTM2MTJmNTBhMTg4ZCIsImlhdCI6MTY3ODkyNTI0NSwiZXhwIjoxOTk0Mjg1MjQ1fQ.eLdOdYA5MCdQIQW84ZqJ2ZyXzhy2deOsqG1NRjW7Y5g'}

api_url_solar_history = 'https://homeassistant.kevin-lee.co.uk:8392/api/history/period/{start_timestamp}+00:00?end_time={end_timestamp}%2B00%3A00&filter_entity_id=sensor.delta_max_030030_dc_input'
api_url_solar = 'https://homeassistant.kevin-lee.co.uk:8392/api/states/sensor.delta_max_030030_dc_input'
headers_solar = {'Authorization': 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiIxM2ZhZWYzMmZmNDM0MmU0OWExNzI3YjRlNmZhODVhNSIsImlhdCI6MTY4MjU3OTQ1OSwiZXhwIjoxOTk3OTM5NDU5fQ.rJIREJwCrGllLoq97O8sZ_2PbPfWkVIMvrFDb6m3VIo'}

households = ['Household 1', 'Household 2', 'Household 3', 'Household 4', 'Household 5', 'Household 6', 'Household 7']
multipliers = [1, 1.03, 0.97, 1.06, 0.94, 1.1, 0.90]
entities = ['voltage', 'current', 'power', 'energy', 'tde', 'Solar PV']

data_arrays = {household: {entity: [] for entity in entities} for household in households}

def fetch_data():
    global data_arrays
    current_timestamp = time.time()
    raw_data = {entity: [] for entity in entities if entity != 'Solar PV'}

    for plug_index in range(1, 5):
        for entity in entities:
            if entity != 'Solar PV':
                api_entity = f"sensor.athom_smart_plug_v2_{entity}_{plug_index}"
                api_url = f"{api_url_base}{api_entity}"
                response = requests.get(api_url, headers=headers)
                data = response.json()
                if 'state' in data:
                    raw_data[entity].append(float(data['state']))

    # Fetch solar data
    response_solar = requests.get(api_url_solar, headers=headers_solar)
    data_solar = response_solar.json()
    if 'state' in data_solar:
        try:
            solar_value = float(data_solar['state'])
        except ValueError:  # Catch the exception when the value is 'unavailable' and set it to 0
            solar_value = 0
    else:
        solar_value = 0

    data_arrays['Household 1'] = aggregate_data(data_arrays['Household 1'], raw_data, current_timestamp)

    # Include solar data in data_arrays
    for household in households:
        data_arrays[household]['Solar PV'].append((current_timestamp, solar_value))

    generate_additional_households(data_arrays, False, False)
    return data_arrays

def aggregate_data(household_data, raw_data, current_timestamp):
    aggregated_data = {entity: [] for entity in entities}

    for entity in entities:
        if entity == 'voltage':
            voltage_sum = sum(raw_data[entity])
            aggregated_data[entity] = household_data[entity] + [(current_timestamp, voltage_sum / 4)]
        elif entity in('current', 'power', 'energy', 'tde'):
            entity_sum = sum(raw_data[entity])
            aggregated_data[entity] = household_data[entity] + [(current_timestamp, entity_sum)]
    return aggregated_data

def generate_additional_households(data_arrays, historical=False, historical_data_arrays=None):
    source_data_arrays = historical_data_arrays if historical else data_arrays
    for household_index, (household, multiplier) in enumerate(zip(households[1:], multipliers[1:]), start=2):
        derived_data = {}
        for entity in entities:
            # Apply the multiplier to each data point of Household 1
            entity_data = [(timestamp, value * multiplier) for (timestamp, value) in source_data_arrays['Household 1'][entity]]
            derived_data[entity] = entity_data
        data_arrays[household] = derived_data
    return data_arrays

def fetch_history_data(start_date, end_date):
    global data_arrays
    raw_data = {entity: [] for entity in entities if entity != 'Solar PV'}
    start_timestamp = start_date.strftime('%Y-%m-%dT%H:%M:%S')
    end_timestamp = end_date.strftime('%Y-%m-%dT%H:%M:%S')
    
    for plug_index in range(1, 5):
        for entity in entities:
            if entity != 'Solar PV':
                api_entity = f"sensor.athom_smart_plug_v2_{entity}_{plug_index}"
                api_url = api_url_base_hist.format(start_timestamp=start_timestamp, end_timestamp=end_timestamp) + api_entity
                response = requests.get(api_url, headers=headers)
                data = response.json()
                if len(data) > 0:
                    filtered_data = [(entry['last_changed'], float(entry['state'])) for entry in data[0] if 'state' in entry and 'last_changed' in entry and entry['state'].replace('.', '', 1).isdigit()]
                    raw_data[entity].append(filtered_data)

    # Fetch solar historical data
    api_url_solar_history_formatted = api_url_solar_history.format(start_timestamp=start_timestamp, end_timestamp=end_timestamp)
    response_solar_hist = requests.get(api_url_solar_history_formatted, headers=headers_solar)
    data_solar_hist = response_solar_hist.json()
    if len(data_solar_hist) > 0:
        solar_hist_data = []
        for entry in data_solar_hist[0]:
            if 'state' in entry and 'last_changed' in entry:
                try:
                    value = float(entry['state'])
                except ValueError:  # Catch the exception when the value is 'unavailable' and set it to 0
                    value = 0
                solar_hist_data.append((entry['last_changed'], value))
    else:
        solar_hist_data = []

    historical_data_arrays = {household: {entity: [] for entity in entities} for household in households}
    for entity in entities:
        combined_values = []
        if entity != 'Solar PV':
            if raw_data[entity]:  # Check to ensure raw_data[entity] is not empty
                for i in range(len(raw_data[entity][0])):
                    combined_value = sum([plug_data[i][1] for plug_data in raw_data[entity] if i < len(plug_data)])
                    timestamp = raw_data[entity][0][i][0]
                    combined_values.append((timestamp, combined_value))
        elif entity == 'Solar PV':  # Add this condition for 'Solar PV' data
            #if solar_hist_data:  # Check to ensure solar_hist_data is not empty
                combined_values = solar_hist_data

        historical_data_arrays['Household 1'][entity] = combined_values

    # Include solar historical data in historical_data_arrays
    for household in households:
        historical_data_arrays[household]['Solar PV'] = solar_hist_data

    historical_data_arrays = generate_additional_households(historical_data_arrays, historical=True, historical_data_arrays=historical_data_arrays)
    return historical_data_arrays

@app.route('/')
def simulation():
    data = fetch_data()
    selected_entities = entities
    return render_template('simulation.html', households=households, entities=entities, data=data, selected_entities=selected_entities, len=len, dash_app=dash_app)

@app.route('/schematic')
def schematic():
    data = fetch_data()
    selected_entities = entities
    return render_template('schematic.html', households=households, entities=entities, data=data, selected_entities=selected_entities, len=len, dash_app=dash_app)

@app.route('/fetch_data')
def fetch_data_route():
    data = fetch_data()
    return jsonify(data)

@app.route('/history')
def history():
    start_date_str = request.args.get('start_date', default=None, type=str)
    end_date_str = request.args.get('end_date', default=None, type=str)

    if start_date_str and end_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        data = fetch_history_data(start_date, end_date)
    else:
        # Use default dates if start and end dates are not provided
        data = fetch_history_data()

    selected_entities = entities
    return render_template('history.html', households=households, entities=entities, data=data, selected_entities=selected_entities, len=len, dash_app=dash_app)

if __name__ == '__main__':
    app.run(debug=True)