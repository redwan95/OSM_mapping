import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
from opencage.geocoder import OpenCageGeocode
import openrouteservice
import folium
from streamlit_folium import folium_static

# --- API KEYS ---
OPENCAGE_KEY = st.secrets["OPENCAGE_KEY"]
ORS_API_KEY = st.secrets["ORS_API_KEY"]

# --- Initialize API clients ---
geocoder = OpenCageGeocode(OPENCAGE_KEY)
client = openrouteservice.Client(key=ORS_API_KEY)

# --- UI ---
st.title("🚗 Trip Cost Estimator with Real-Time Fuel Prices")

# Vehicle inputs
make = st.text_input("Vehicle Make", "Toyota")
model = st.text_input("Vehicle Model", "Camry")
year = st.selectbox("Vehicle Year", list(range(2024, 1999, -1)))
is_ev = st.selectbox("Is this an EV?", ["No", "Yes"])

fuel_grade = st.selectbox("Fuel Grade Type", ["Regular", "Mid-Grade", "Premium", "Diesel"])

if is_ev == "Yes":
    mpg = 9999  # Simulate EV usage with effectively infinite MPG
else:
    mpg = st.number_input("Vehicle MPG (miles per gallon)", min_value=5.0, value=25.0)

# Autocomplete address helper
def nominatim_search(query):
    if not query:
        return []
    params = {"q": query, "format": "json", "addressdetails": 1, "limit": 5}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        r = requests.get("https://nominatim.openstreetmap.org/search", params=params, headers=headers, timeout=10)
        if r.status_code == 200:
            return [res["display_name"] for res in r.json()]
        return []
    except Exception as e:
        st.error(f"Error in address search: {e}")
        return []

# Input locations
start_input = st.text_input("Start Location")
start_opts = nominatim_search(start_input) if start_input else []
start = st.selectbox("Select Start Location", options=start_opts) if start_opts else None

num_stops = st.number_input("Number of Stops", 0, 5, 0)
stops = []
for i in range(num_stops):
    stop_input = st.text_input(f"Stop {i+1}")
    stop_opts = nominatim_search(stop_input) if stop_input else []
    stop_sel = st.selectbox(f"Select Stop {i+1}", options=stop_opts) if stop_opts else None
    if stop_sel:
        stops.append(stop_sel)

end_input = st.text_input("End Location")
end_opts = nominatim_search(end_input) if end_input else []
end = st.selectbox("Select End Location", options=end_opts) if end_opts else None

# Geocode to lat/lon
def get_coordinates(address):
    try:
        results = geocoder.geocode(address)
        if results:
            lat = results[0]["geometry"]["lat"]
            lng = results[0]["geometry"]["lng"]
            return lat, lng
        return None
    except Exception as e:
        st.error(f"Geocoding failed for {address}: {e}")
        return None

# Extract full state name from address
def extract_full_state_name(address):
    try:
        results = geocoder.geocode(address)
        if results:
            components = results[0].get("components", {})
            return components.get("state")
        return None
    except Exception as e:
        st.error(f"State extraction failed for {address}: {e}")
        return None

# Scrape AAA fuel price by state and grade using BeautifulSoup
def fetch_aaa_fuel_price(full_state_name, grade='Regular'):
    grade_column_map = {
        "Regular": "regular",
        "Mid-Grade": "mid",
        "Premium": "premium",
        "Diesel": "diesel"
    }

    if grade not in grade_column_map:
        st.error(f"Invalid fuel grade: {grade}")
        return None

    try:
        url = "https://gasprices.aaa.com/state-gas-price-averages/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            st.error(f"Failed to fetch AAA page: Status {response.status_code}")
            return None

        soup = BeautifulSoup(response.text, 'html.parser')
        table = soup.find("table")
        if not table:
            st.error("Could not find table on AAA page")
            return None

        rows = table.find_all("tr")[1:]  # Skip header row
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 5:
                continue
            state = cols[0].text.strip()
            if state.lower() == full_state_name.lower():
                price_str = cols[list(grade_column_map.keys()).index(grade) + 1].text.strip()
                price_clean = re.sub(r"[^\d.]", "", price_str)
                return float(price_clean) if price_clean else None
        st.warning(f"No fuel price found for state: {full_state_name}")
        return None
    except Exception as e:
        st.error(f"Error fetching fuel price for {full_state_name}: {e}")
        return None

# Get average fuel price across all states in route
def get_average_fuel_price(addresses, fuel_grade):
    detected_states = []
    for addr in addresses:
        state = extract_full_state_name(addr)
        if state and state not in detected_states:
            detected_states.append(state)

    if not detected_states:
        st.error("No states detected in the route.")
        return None

    st.write(f"Detected states in route: {detected_states}")
    prices = [fetch_aaa_fuel_price(state, fuel_grade) for state in detected_states]
    prices = [p for p in prices if p is not None]

    if prices:
        return sum(prices) / len(prices)
    else:
        st.warning("No fuel prices fetched for any state.")
        return None

# Main route logic
if st.button("Calculate Trip") and start and end:
    all_addresses = [start] + stops + [end]
    coords = [get_coordinates(addr) for addr in all_addresses]

    if None in coords:
        st.error("❌ Could not geocode one or more locations.")
    else:
        ors_coords = [(lng, lat) for lat, lng in coords]

        try:
            route = client.directions(
                coordinates=ors_coords,
                profile='driving-car',
                format='geojson'
            )

            summary = route["features"][0]["properties"]["summary"]
            dist_km = summary["distance"] / 1000
            dist_miles = dist_km * 0.621371
            duration_min = summary["duration"] / 60
            fuel_used = dist_miles / mpg if mpg else 0

            avg_price = get_average_fuel_price(all_addresses, fuel_grade)
            if avg_price:
                trip_cost = fuel_used * avg_price
            else:
                avg_price = 3.60
                trip_cost = fuel_used * avg_price
                st.warning("⚠️ Could not fetch fuel prices. Using fallback $3.60/gal.")

            # Show summary
            st.subheader("📊 Trip Summary")
            st.write(f"Distance: {dist_km:.2f} km / {dist_miles:.2f} miles")
            st.write(f"Duration: {duration_min:.1f} minutes")
            st.write(f"Fuel Used: {fuel_used:.2f} gallons")
            st.write(f"Fuel Grade: {fuel_grade}")
            st.write(f"Avg. Fuel Price: ${avg_price:.2f} per gallon")
            st.write(f"Estimated Trip Cost: ${trip_cost:.2f}")

            # Map
            m = folium.Map(location=coords[0], zoom_start=6)
            for addr, c in zip(all_addresses, coords):
                folium.Marker(location=c, popup=addr).add_to(m)
            folium.GeoJson(route).add_to(m)
            folium_static(m)

        except Exception as e:
            st.error(f"Routing failed: {e}")
