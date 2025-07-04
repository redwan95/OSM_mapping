import streamlit as st
import requests
import re
from opencage.geocoder import OpenCageGeocode
import openrouteservice
import folium
from streamlit_folium import folium_static
from xml.etree import ElementTree as ET

# --- API KEYS ---
OPENCAGE_KEY = st.secrets["OPENCAGE_KEY"]
ORS_API_KEY = st.secrets["ORS_API_KEY"]

# --- Initialize Clients ---
geocoder = OpenCageGeocode(OPENCAGE_KEY)
client = openrouteservice.Client(key=ORS_API_KEY)

st.title("⛽ Trip Cost Estimator with Vehicle MPG Lookup")

# --- Fetch vehicle makes ---
@st.cache_data(ttl=86400)
def get_makes():
    url = "https://www.fueleconomy.gov/ws/rest/vehicle/menu/make?year=2023"  # fixed year for list of makes
    res = requests.get(url)
    if res.status_code != 200:
        return []
    root = ET.fromstring(res.content)
    makes = [child.text for child in root.findall(".//value")]
    return makes

# --- Fetch models based on make and year ---
@st.cache_data(ttl=86400)
def get_models(year, make):
    url = f"https://www.fueleconomy.gov/ws/rest/vehicle/menu/model?year={year}&make={make}"
    res = requests.get(url)
    if res.status_code != 200:
        return []
    root = ET.fromstring(res.content)
    models = [child.text for child in root.findall(".//value")]
    return models

# --- Fetch years based on make and model ---
@st.cache_data(ttl=86400)
def get_years(make, model):
    url = f"https://www.fueleconomy.gov/ws/rest/vehicle/menu/year?make={make}&model={model}"
    res = requests.get(url)
    if res.status_code != 200:
        return []
    root = ET.fromstring(res.content)
    years = [int(child.text) for child in root.findall(".//value")]
    years.sort(reverse=True)
    return years

# --- Fetch MPG given make, model, year ---
@st.cache_data(ttl=3600)
def get_vehicle_mpg(make, model, year):
    try:
        options_url = f"https://www.fueleconomy.gov/ws/rest/vehicle/menu/options?year={year}&make={make}&model={model}"
        res = requests.get(options_url)
        if res.status_code != 200:
            return None
        root = ET.fromstring(res.content)
        vehicle_id = root.find('.//value')
        if vehicle_id is None:
            return None
        vehicle_id = vehicle_id.text
        mpg_url = f"https://www.fueleconomy.gov/ws/rest/vehicle/{vehicle_id}"
        mpg_res = requests.get(mpg_url)
        mpg_root = ET.fromstring(mpg_res.content)
        mpg = mpg_root.findtext("comb08")
        if mpg:
            return float(mpg)
        return None
    except:
        return None

# --- Vehicle input UI ---
st.header("Vehicle Information")

makes = get_makes()
selected_make = st.selectbox("Select Vehicle Make", options=makes)

if selected_make:
    current_year = 2023
    years_for_make = get_years(selected_make, "")  # For initial load pass empty model to get years?
    # Instead, to get years, we need a model — so we do models first

    # Load models for current year (fallback)
    models_for_make = get_models(current_year, selected_make)
    selected_model = st.selectbox("Select Vehicle Model", options=models_for_make)

    selected_year = None
    if selected_model:
        years_for_make_model = get_years(selected_make, selected_model)
        if years_for_make_model:
            selected_year = st.selectbox("Select Vehicle Year", options=years_for_make_model)
        else:
            # fallback year selection if no years found
            selected_year = st.number_input("Enter Vehicle Year", min_value=1984, max_value=2025, value=current_year)

    mpg = None
    if selected_make and selected_model and selected_year:
        mpg = get_vehicle_mpg(selected_make, selected_model, selected_year)
        if mpg:
            st.success(f"Estimated MPG for your vehicle: {mpg}")
        else:
            st.warning("Could not find MPG automatically, please enter manually below.")
            mpg = st.number_input("Enter Vehicle MPG manually", min_value=5.0, value=25.0)
else:
    mpg = st.number_input("Enter Vehicle MPG manually", min_value=5.0, value=25.0)

# --- Fuel Grade Selection ---
fuel_grade = st.selectbox("Select Fuel Grade", ["Regular", "Mid-Grade", "Premium", "Diesel"])

# --- Address Autocomplete ---
def nominatim_search(query):
    if not query:
        return []
    params = {"q": query, "format": "json", "addressdetails": 1, "limit": 5}
    headers = {"User-Agent": "streamlit-app"}
    r = requests.get("https://nominatim.openstreetmap.org/search", params=params, headers=headers)
    if r.status_code == 200:
        return [res["display_name"] for res in r.json()]
    return []

# --- Input Locations ---
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

# --- Geocoding ---
def get_coordinates(address):
    try:
        results = geocoder.geocode(address)
        if results:
            lat = results[0]["geometry"]["lat"]
            lng = results[0]["geometry"]["lng"]
            return lat, lng
    except:
        return None

def extract_full_state_name(address):
    try:
        results = geocoder.geocode(address)
        if results:
            components = results[0].get("components", {})
            return components.get("state")
    except:
        return None

# --- Scrape AAA Fuel Prices (Regex Only) ---
def fetch_aaa_fuel_price(state_name, grade="Regular"):
    grade_column_map = {
        "Regular": 1,
        "Mid-Grade": 2,
        "Premium": 3,
        "Diesel": 4
    }
    col_idx = grade_column_map.get(grade)
    if col_idx is None:
        return None

    try:
        url = "https://gasprices.aaa.com/state-gas-price-averages/"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None

        rows = re.findall(r"<tr>(.*?)</tr>", response.text, re.DOTALL)
        for row in rows:
            cols = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
            if len(cols) >= 5:
                state = re.sub(r"<.*?>", "", cols[0]).strip()
                if state.lower() == state_name.lower():
                    price_text = re.sub(r"[^\d.]", "", cols[col_idx])
                    return float(price_text)
        return None
    except Exception as e:
        print(f"Scraping failed: {e}")
        return None

def get_average_fuel_price(addresses, fuel_grade):
    detected_states = []
    for addr in addresses:
        state = extract_full_state_name(addr)
        if state and state not in detected_states:
            detected_states.append(state)

    st.write(f"Detected states in route: {detected_states}")
    prices = [fetch_aaa_fuel_price(state, fuel_grade) for state in detected_states]
    prices = [p for p in prices if p is not None]

    if prices:
        return sum(prices) / len(prices)
    else:
        return None

# --- Calculate Trip ---
if st.button("Calculate Trip") and start and end:
    all_addresses = [start] + stops + [end]
    coords = [get_coordinates(addr) for addr in all_addresses]

    if None in coords:
        st.error("Could not geocode one or more locations.")
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

            st.subheader("📊 Trip Summary")
            st.write(f"Distance: {dist_km:.2f} km / {dist_miles:.2f} miles")
            st.write(f"Duration: {duration_min:.1f} minutes")
            st.write(f"Fuel Used: {fuel_used:.2f} gallons")
            st.write(f"Avg. Gas Price ({fuel_grade}): ${avg_price:.2f}/gal")
            st.write(f"Estimated Trip Cost: ${trip_cost:.2f}")

            m = folium.Map(location=coords[0], zoom_start=6)
            for addr, c in zip(all_addresses, coords):
                folium.Marker(location=c, popup=addr).add_to(m)
            folium.GeoJson(route).add_to(m)
            folium_static(m)

        except Exception as e:
            st.error(f"Routing failed: {e}")
