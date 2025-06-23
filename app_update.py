import streamlit as st
import requests
from opencage.geocoder import OpenCageGeocode
import openrouteservice
import folium
from streamlit_folium import folium_static

# --- Load API keys from secrets ---
OPENCAGE_KEY = st.secrets["OPENCAGE_KEY"]
ORS_API_KEY = st.secrets["ORS_API_KEY"]
EIA_API_KEY = st.secrets.get("EIA_API_KEY", None)

# --- API clients ---
geocoder = OpenCageGeocode(OPENCAGE_KEY)
client = openrouteservice.Client(key=ORS_API_KEY)

# --- US states abbreviation set ---
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY",
    "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND",
    "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"
}

# --- Helper Functions ---
def nominatim_search(query):
    params = {"q": query, "format": "json", "addressdetails": 1, "limit": 5}
    headers = {"User-Agent": "streamlit-trip-planner"}
    r = requests.get("https://nominatim.openstreetmap.org/search", params=params, headers=headers)
    return [res["display_name"] for res in r.json()] if r.status_code == 200 else []

def get_coordinates(address):
    result = geocoder.geocode(address)
    return result[0]["geometry"]["lat"], result[0]["geometry"]["lng"]

def extract_state(address):
    parts = address.split(",")
    for part in reversed(parts):
        segment = part.strip().upper()
        for state in US_STATES:
            if state in segment:
                return state
    return None

def get_state_price(state_abbr):
    if not EIA_API_KEY or state_abbr not in US_STATES:
        st.write(f"Skipping fuel lookup for invalid/missing state: {state_abbr}")
        return None
    url = (
        f"https://api.eia.gov/v2/petroleum/pri/gnd/data/"
        f"?api_key={EIA_API_KEY}&frequency=weekly&data[0]=value"
        f"&facets[state][]={state_abbr}&facets[fuelType][]=Regular"
        f"&sort[0][column]=period&sort[0][direction]=desc&offset=0&length=1"
    )
    res = requests.get(url)
    st.write(f"EIA API response for {state_abbr}: {res.status_code}")
    try:
        if res.status_code == 200:
            data = res.json()
            price_data = data.get("response", {}).get("data", [])
            if price_data:
                return float(price_data[0]["value"])
    except Exception as e:
        st.error(f"Error parsing fuel price for {state_abbr}: {e}")
    return None

def get_average_fuel_price(states):
    prices = []
    for state in states:
        price = get_state_price(state)
        if price:
            prices.append(price)
    if prices:
        avg = sum(prices) / len(prices)
        return avg
    return None

def get_vehicle_mpg(make, model, year):
    try:
        import xml.etree.ElementTree as ET
        res = requests.get(f"https://www.fueleconomy.gov/ws/rest/vehicle/menu/options?year={year}&make={make}&model={model}")
        root = ET.fromstring(res.content)
        vehicle_id = root.find(".//value").text
        mpg_res = requests.get(f"https://www.fueleconomy.gov/ws/rest/vehicle/{vehicle_id}")
        mpg_root = ET.fromstring(mpg_res.content)
        return float(mpg_root.findtext("comb08"))
    except:
        return None

# --- Streamlit UI ---
st.title("Multi-Stop Trip Planner with Fuel Cost (State Avg)")

make = st.text_input("Vehicle Make", "Toyota")
model = st.text_input("Vehicle Model", "Camry")
year = st.selectbox("Vehicle Year", list(range(2024, 1999, -1)))
is_ev = st.selectbox("Is it an EV?", ["No", "Yes"])

mpg = None if is_ev == "Yes" else get_vehicle_mpg(make, model, year)
if mpg:
    st.success(f"Estimated MPG (combined): {mpg:.1f}")
else:
    mpg = st.number_input("Enter Manual MPG", min_value=5.0, value=25.0)

start_input = st.text_input("Start Location")
start_options = nominatim_search(start_input) if start_input else []
start = st.selectbox("Select Start", options=start_options) if start_options else None

num_stops = st.number_input("Number of Stops", 0, 5, 0)
stops = []
for i in range(num_stops):
    stop_input = st.text_input(f"Stop {i+1}")
    stop_opts = nominatim_search(stop_input) if stop_input else []
    stop_sel = st.selectbox(f"Select Stop {i+1}", stop_opts) if stop_opts else None
    if stop_sel:
        stops.append(stop_sel)

end_input = st.text_input("End Location")
end_options = nominatim_search(end_input) if end_input else []
end = st.selectbox("Select End", options=end_options) if end_options else None

if st.button("Calculate Trip") and start and end:
    try:
        route_addresses = [start] + stops + [end]
        coordinates = [get_coordinates(addr) for addr in route_addresses]
        ors_coords = [(lon, lat) for lat, lon in coordinates]

        route = client.directions(
            coordinates=ors_coords,
            profile='driving-car',
            format='geojson'
        )

        summary = route['features'][0]['properties']['summary']
        dist_km = summary['distance'] / 1000
        dist_miles = dist_km * 0.621371
        dur_minutes = summary['duration'] / 60
        fuel_used = dist_miles / mpg

        states = [extract_state(addr) for addr in route_addresses]
        st.write(f"Detected States in Route: {states}")
        avg_price = get_average_fuel_price(states)
        if avg_price:
            trip_cost = fuel_used * avg_price
        else:
            avg_price = 3.60
            trip_cost = fuel_used * avg_price
            st.warning("Could not fetch state fuel prices. Using fallback: $3.60/gal")

        st.markdown(f"**Distance:** {dist_km:.1f} km / {dist_miles:.1f} mi")
        st.markdown(f"**Duration:** {dur_minutes:.1f} minutes")
        st.markdown(f"**Fuel Used:** {fuel_used:.2f} gallons")
        st.markdown(f"**Avg Fuel Price:** ${avg_price:.2f}/gal")
        st.markdown(f"**Estimated Trip Cost:** ${trip_cost:.2f}")

        m = folium.Map(location=coordinates[0], zoom_start=6)
        for addr, coord in zip(route_addresses, coordinates):
            folium.Marker(coord, popup=addr).add_to(m)
        folium.GeoJson(route).add_to(m)
        folium_static(m)

    except Exception as e:
        st.error(f"Error calculating route: {e}")
