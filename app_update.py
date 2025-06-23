import streamlit as st
import requests
from bs4 import BeautifulSoup
from opencage.geocoder import OpenCageGeocode
import openrouteservice
import folium
from streamlit_folium import folium_static

# --- API Keys ---
OPENCAGE_KEY = st.secrets["OPENCAGE_KEY"]
ORS_API_KEY = st.secrets["ORS_API_KEY"]

# --- Initialize Services ---
geocoder = OpenCageGeocode(OPENCAGE_KEY)
client = openrouteservice.Client(key=ORS_API_KEY)

# --- US State Abbreviations Set ---
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY",
    "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND",
    "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"
}

# --- Streamlit UI ---
st.title("🚘 Trip Cost Estimator with State Fuel Price (AAA)")

# Vehicle details
make = st.text_input("Vehicle Make", "Toyota")
model = st.text_input("Vehicle Model", "Camry")
year = st.selectbox("Vehicle Year", list(range(2024, 1999, -1)))
is_ev = st.selectbox("Is this an EV?", ["No", "Yes"])

# Get MPG
def get_vehicle_mpg(make, model, year):
    try:
        import xml.etree.ElementTree as ET
        r = requests.get(f"https://www.fueleconomy.gov/ws/rest/vehicle/menu/options?year={year}&make={make}&model={model}")
        root = ET.fromstring(r.content)
        vehicle_id = root.find(".//value").text
        mpg_r = requests.get(f"https://www.fueleconomy.gov/ws/rest/vehicle/{vehicle_id}")
        mpg_root = ET.fromstring(mpg_r.content)
        return float(mpg_root.findtext("comb08"))
    except:
        return None

mpg = None if is_ev == "Yes" else get_vehicle_mpg(make, model, year)
if mpg:
    st.success(f"Vehicle MPG (estimated): {mpg:.1f}")
else:
    mpg = st.number_input("Enter MPG manually", min_value=5.0, value=25.0)

# Address inputs
def nominatim_search(query):
    params = {"q": query, "format": "json", "addressdetails": 1, "limit": 5}
    headers = {"User-Agent": "streamlit-app"}
    r = requests.get("https://nominatim.openstreetmap.org/search", params=params, headers=headers)
    return [res["display_name"] for res in r.json()] if r.status_code == 200 else []

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

# --- Helper Functions ---
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

def fetch_aaa_price(state_abbr):
    try:
        url = "https://gasprices.aaa.com/state-gas-price-averages/"
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        table = soup.find('table')
        for row in table.find_all('tr')[1:]:
            cols = row.find_all('td')
            state = cols[0].text.strip()
            price = cols[1].text.strip().replace('$', '')
            if state_abbr in state:
                return float(price)
    except Exception as e:
        st.warning(f"AAA price fetch failed for {state_abbr}: {e}")
    return None

def get_average_fuel_price(addresses):
    states = []
    for addr in addresses:
        state = extract_state_from_geocode(addr)
        if state and state not in states:
            states.append(state)

    st.write(f"Detected states: {states}")
    prices = [fetch_aaa_price(state) for state in states]
    prices = [p for p in prices if p is not None]

    if prices:
        return sum(prices) / len(prices)
    return None

# --- Calculate Trip ---
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
            st.warning("⚠️ Could not fetch state fuel prices. Using fallback $3.60/gal")

        st.subheader("📊 Trip Summary")
        st.write(f"**Distance:** {dist_km:.1f} km / {dist_mi:.1f} mi")
        st.write(f"**Duration:** {duration_min:.1f} minutes")
        st.write(f"**Fuel Used:** {fuel_used:.2f} gallons")
        st.write(f"**Average Fuel Price:** ${avg_price:.2f}/gal")
        st.write(f"**Estimated Trip Cost:** **${trip_cost:.2f}**")

        # Map
        m = folium.Map(location=coords[0], zoom_start=6)
        for addr, coord in zip(addresses, coords):
            folium.Marker(coord, popup=addr).add_to(m)
        folium.GeoJson(route).add_to(m)
        folium_static(m)

    except Exception as e:
        st.error(f"❌ Error calculating route: {e}")
