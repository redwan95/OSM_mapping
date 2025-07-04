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

geocoder = OpenCageGeocode(OPENCAGE_KEY)
client = openrouteservice.Client(key=ORS_API_KEY)

st.title("⛽ Trip Cost Estimator with Vehicle MPG Lookup")

# --- Vehicle Selection & MPG Fetch ---
is_ev = st.selectbox("Is this an EV?", ["No", "Yes"])
if is_ev == "Yes":
    mpg = 1000.0
else:
    # Year dropdown
    years = requests.get("https://www.fueleconomy.gov/ws/rest/vehicle/menu/year", headers={"Accept":"application/json"}).json()['menuItem']
    selected_year = st.selectbox("Vehicle Year", options=[int(y['value']) for y in years], index=0)
    # Make dropdown
    makes = requests.get(f"https://www.fueleconomy.gov/ws/rest/vehicle/menu/make?year={selected_year}", headers={"Accept":"application/json"}).json().get('menuItem', [])
    selected_make = st.selectbox("Vehicle Make", options=[m['text'] for m in makes])
    # Model dropdown
    models = requests.get(f"https://www.fueleconomy.gov/ws/rest/vehicle/menu/model?year={selected_year}&make={selected_make}", headers={"Accept":"application/json"}).json().get('menuItem', [])
    selected_model = st.selectbox("Vehicle Model", options=[m['text'] for m in models])
    # Trim/options dropdown
    options = requests.get(
        f"https://www.fueleconomy.gov/ws/rest/vehicle/menu/options?year={selected_year}&make={selected_make}&model={selected_model}",
        headers={"Accept":"application/json"}
    ).json().get('menuItem', [])
    if options:
        selected_opt = st.selectbox("Trim / Option", options=[o['text'] for o in options])
        vehicle_id = next(o['value'] for o in options if o['text']==selected_opt)
        # Fetch vehicle info
        resp = requests.get(f"https://www.fueleconomy.gov/ws/rest/vehicle/{vehicle_id}", headers={"Accept":"application/json"})
        veh = resp.json().get('vehicle', {})
        mpg = float(veh.get('comb08', 0))
        st.write(f"✅ Combined MPG: {mpg:.1f}")
    else:
        st.error("No options found — please select a different model.")
        mpg = st.number_input("Fallback MPG", min_value=5.0, value=25.0)

# --- Fuel Grade & Vehicle Details ---
fuel_grade = st.selectbox("Select Fuel Grade", ["Regular", "Mid-Grade", "Premium", "Diesel"])

# --- Location inputs (autocomplete, geocoding, routing) ---
def nominatim_search(q): ...
start = ...
stops = [...]
end = ...

# --- State-wise AAA fuel pricing (regex scraper) ---
def fetch_aaa_fuel_price(state, grade):
    grade_col = {"Regular":1,"Mid-Grade":2,"Premium":3,"Diesel":4}[grade]
    r = requests.get("https://gasprices.aaa.com/state-gas-price-averages/", headers={"User-Agent":"Mozilla"})
    rows = re.findall(r"<tr>(.*?)</tr>", r.text, re.DOTALL)
    for row in rows:
        cols = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        if len(cols)>=5 and cols[0].strip().lower()==state.lower():
            return float(re.sub(r"[^\d.]","", cols[grade_col]))
    return None

def extract_state(addr):
    res = geocoder.geocode(addr)
    comp = res[0].get("components", {}) if res else {}
    return comp.get("state")

def get_avg_price(addrs):
    sts = [extract_state(a) for a in addrs]
    sts = [s for s in set(sts) if s]
    st.write(f"Detected states: {sts}")
    ps = [fetch_aaa_fuel_price(s,fuel_grade) for s in sts]
    ps = [p for p in ps if p]
    return sum(ps)/len(ps) if ps else None

# --- Compute route & show map & cost ---
if st.button("Calculate Trip") and start and end:
    all_addr = [start]+stops+[end]
    coords = [geocoder.geocode(addr)[0]["geometry"].values() for addr in all_addr]
    if any(c is None for c in coords):
        st.error("Could not geocode all addresses.")
    else:
        ors_coords = [(lng, lat) for lat,lng in coords]
        route = client.directions(coordinates=ors_coords, profile='driving-car', format='geojson')
        summary = route["features"][0]["properties"]["summary"]
        dist_miles = summary["distance"]/1000*0.621371
        fuel = dist_miles/mpg
        avg_p = get_avg_price(all_addr) or 3.60
        trip_cost = fuel * avg_p
        st.subheader("📊 Trip Summary")
        st.write(f"Distance: {dist_miles:.1f} mi | Fuel used: {fuel:.2f} gal | Cost: ${trip_cost:.2f}")
        m=folium.Map(location=coords[0], zoom_start=6)
        for addr,c in zip(all_addr, coords): folium.Marker(location=c, popup=addr).add_to(m)
        folium.GeoJson(route).add_to(m)
        folium_static(m)
