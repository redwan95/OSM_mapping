import streamlit as st
import requests
import re
from opencage.geocoder import OpenCageGeocode
import openrouteservice
import folium
from streamlit_folium import folium_static

# --- API KEYS ---
OPENCAGE_KEY = st.secrets["OPENCAGE_KEY"]
ORS_API_KEY = st.secrets["ORS_API_KEY"]

# --- Init clients ---
geocoder = OpenCageGeocode(OPENCAGE_KEY)
client = openrouteservice.Client(key=ORS_API_KEY)

# --- State abbreviation to full name map ---
STATE_ABBR_TO_FULL = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming"
}

# --- Streamlit UI ---

st.title("🚘 Trip Cost Estimator with Multiple Stops & State-Averaged Fuel Price")

# Vehicle inputs
make = st.text_input("Vehicle Make", "Toyota")
model = st.text_input("Vehicle Model", "Camry")
year = st.selectbox("Vehicle Year", list(range(2024, 1999, -1)))
is_ev = st.selectbox("Is this an EV?", ["No", "Yes"])

# MPG input or estimation (basic, can be improved)
if is_ev == "Yes":
    mpg = 1000  # placeholder large value to simulate low fuel consumption
else:
    mpg = st.number_input("Vehicle MPG (miles per gallon)", min_value=5.0, value=25.0)

# Location inputs
def nominatim_search(query):
    if not query:
        return []
    params = {"q": query, "format": "json", "addressdetails": 1, "limit": 5}
    headers = {"User-Agent": "streamlit-app"}
    r = requests.get("https://nominatim.openstreetmap.org/search", params=params, headers=headers)
    if r.status_code == 200:
        return [res["display_name"] for res in r.json()]
    return []

start_input = st.text_input("Start Location")
start_opts = nominatim_search(start_input) if start_input else []
start = st.selectbox("Select Start Location", options=start_opts) if start_opts else None

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
end = st.selectbox("Select End Location", options=end_opts) if end_opts else None

# --- Helper Functions ---
def get_coordinates(address):
    result = geocoder.geocode(address)
    if result:
        return result[0]["geometry"]["lat"], result[0]["geometry"]["lng"]
    return None

def extract_state_from_geocode(address):
    try:
        result = geocoder.geocode(address)
        components = result[0].get('components', {})
        state_code = components.get('state_code', '').upper()
        if state_code in STATE_ABBR_TO_FULL:
            return state_code
    except Exception:
        pass
    return None

def fetch_aaa_price(state_abbr):
    try:
        full_state_name = STATE_ABBR_TO_FULL.get(state_abbr.upper())
        if not full_state_name:
            return None
        url = "https://gasprices.aaa.com/state-gas-price-averages/"
        response = requests.get(url)
        if response.status_code != 200:
            return None

        pattern = re.compile(r'<td>([^<]+)</td>\s*<td>\$([0-9]+\.[0-9]+)</td>')
        matches = pattern.findall(response.text)

        for state, price in matches:
            if state.strip() == full_state_name:
                return float(price)
    except Exception:
        return None

def get_average_fuel_price(addresses):
    states = []
    for addr in addresses:
        state = extract_state_from_geocode(addr)
        if state and state not in states:
            states.append(state)

    st.write(f"Detected states in route: {states}")

    prices = [fetch_aaa_price(state) for state in states]
    prices = [p for p in prices if p is not None]

    if prices:
        avg_price = sum(prices) / len(prices)
        return avg_price
    return None

# --- Calculate & display results ---
if st.button("Calculate Trip") and start and end:
    addresses = [start] + stops + [end]
    coords = [get_coordinates(addr) for addr in addresses]
    if None in coords:
        st.error("Could not get coordinates for one or more locations.")
    else:
        ors_coords = [(lon, lat) for lat, lon in coords]

        try:
            route = client.directions(
                coordinates=ors_coords,
                profile='driving-car',
                format='geojson'
            )

            summary = route["features"][0]["properties"]["summary"]
            dist_km = summary["distance"] / 1000
            dist_mi = dist_km * 0.621371
            duration_min = summary["duration"] / 60
            fuel_used = dist_mi / mpg if mpg > 0 else 0

            avg_price = get_average_fuel_price(addresses)
            if avg_price:
                trip_cost = fuel_used * avg_price
            else:
                avg_price = 3.60  # fallback price
                trip_cost = fuel_used * avg_price
                st.warning("⚠️ Could not fetch state fuel prices. Using fallback price $3.60/gal")

            st.subheader("📊 Trip Summary")
            st.write(f"Distance: {dist_km:.1f} km / {dist_mi:.1f} miles")
            st.write(f"Duration: {duration_min:.1f} minutes")
            st.write(f"Fuel Used: {fuel_used:.2f} gallons")
            st.write(f"Average Fuel Price: ${avg_price:.2f}/gal")
            st.write(f"Estimated Trip Cost: ${trip_cost:.2f}")

            # Display map
            m = folium.Map(location=coords[0], zoom_start=6)
            for addr, coord in zip(addresses, coords):
                folium.Marker(coord, popup=addr).add_to(m)
            folium.GeoJson(route).add_to(m)
            folium_static(m)

        except Exception as e:
            st.error(f"Error calculating route: {e}")
