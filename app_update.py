import streamlit as st
import requests
from opencage.geocoder import OpenCageGeocode
import openrouteservice
import folium
from streamlit_folium import folium_static

# --- API Keys ---
OPENCAGE_KEY = st.secrets["OPENCAGE_KEY"]
ORS_API_KEY = st.secrets["ORS_API_KEY"]
EIA_API_KEY = st.secrets.get("EIA_API_KEY", None)

# --- Initialize Services ---
geocoder = OpenCageGeocode(OPENCAGE_KEY)
client = openrouteservice.Client(key=ORS_API_KEY)

# --- US State Codes ---
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

def extract_state_from_geocode(address):
    try:
        result = geocoder.geocode(address)
        components = result[0].get('components', {})
        state_code = components.get('state_code', '').upper()
        if state_code in US_STATES:
            return state_code
    except Exception as e:
        st.warning(f"State detection failed for '{address}': {e}")
    return None

def get_state_price(state_abbr):
    """
    Uses EIA legacy API for state-level regular fuel prices.
    """
    if not EIA_API_KEY or state_abbr not in US_STATES:
        return None
    try:
        series_id = f"PET.EMM_EPMRU_PTE_S{state_abbr}_DPG.W"
        url = f"https://api.eia.gov/series/?api_key={EIA_API_KEY}&series_id={series_id}"
        res = requests.get(url)
        st.write(f"EIA API response for {state_abbr}: {res.status_code}")
        if res.status_code == 200:
            data = res.json()
            value = data['series'][0]['data'][0][1]
            return float(value)
    except Exception as e:
        st.error(f"Error fetching fuel price for {state_abbr}: {e}")
    return None

def get_average_fuel_price(addresses):
    states = list({
        extract_state_from_geocode(addr)
        for addr in addresses
        if extract_state_from_geocode(addr)
    })
    st.write(f"Detected valid states: {states}")
    prices = [get_state_price(state) for state in states if state]
    prices = [p for p in prices if p is not None]
    if prices:
        return sum(prices) / len(prices)
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
st.title("🚗 US Trip Cost Estimator with State Fuel Prices")

make = st.text_input("Vehicle Make", "Toyota")
model = st.text_input("Vehicle Model", "Camry")
year = st.selectbox("Vehicle Year", list(range(2024, 1999, -1)))
is_ev = st.selectbox("Is this an EV?", ["No", "Yes"])

mpg = None if is_ev == "Yes" else get_vehicle_mpg(make, model, year)
if mpg:
    st.success(f"Vehicle MPG (estimated): {mpg:.1f}")
else:
    mpg = st.number_input("Enter MPG manually", min_value=5.0, value=25.0)

start_input = st.text_input("Start Location")
start_opts = nominatim_search(start_input) if start_input else []
start = st.selectbox("Select Start", options=start_opts) if start_opts else None

num_stops = st.number_input("Number of Stops", 0, 5, 0)
stops = []
for i in range(num_stops):
    stop_input = st.text_input(f"Stop {i+1}")
    stop_opts = nominatim_search(stop_input) if stop_input else []
    stop_sel = st.selectbox(f"Select Stop {i+1}", stop_opts) if stop_opts else None
    if stop_sel:
        stops.append(stop_sel)

end_input = st.text_input("End Location")
end_opts = nominatim_search(end_input) if end_input else []
end = st.selectbox("Select End", options=end_opts) if end_opts else None

if st.button("Calculate Trip") and start and end:
    try:
        addresses = [start] + stops + [end]
        coords = [get_coordinates(addr) for addr in addresses]
        ors_coords = [(lon, lat) for lat, lon in coords]

        route = client.directions(
            coordinates=ors_coords,
            profile='driving-car',
            format='geojson'
        )

        summary = route["features"][0]["properties"]["summary"]
        dist_km = summary["distance"] / 1000
        dist_mi = dist_km * 0.621371
        duration_min = summary["duration"] / 60
        fuel_used = dist_mi / mpg

        avg_price = get_average_fuel_price(addresses)
        if avg_price:
            trip_cost = fuel_used * avg_price
        else:
            avg_price = 3.60
            trip_cost = fuel_used * avg_price
            st.warning("⚠️ Could not fetch state prices. Using fallback: $3.60/gal")

        st.subheader("📊 Trip Summary")
        st.write(f"**Distance:** {dist_km:.1f} km / {dist_mi:.1f} mi")
        st.write(f"**Duration:** {duration_min:.1f} minutes")
        st.write(f"**Fuel Used:** {fuel_used:.2f} gallons")
        st.write(f"**Average Fuel Price:** ${avg_price:.2f}/gal")
        st.write(f"**Estimated Trip Cost:** **${trip_cost:.2f}**")

        m = folium.Map(location=coords[0], zoom_start=6)
        for addr, coord in zip(addresses, coords):
            folium.Marker(coord, popup=addr).add_to(m)
        folium.GeoJson(route).add_to(m)
        folium_static(m)

    except Exception as e:
        st.error(f"❌ Error calculating route: {e}")
