import streamlit as st
import requests
from opencage.geocoder import OpenCageGeocode
import openrouteservice
import folium
from streamlit_folium import folium_static

# Load API keys
OPENCAGE_KEY = st.secrets["OPENCAGE_KEY"]
ORS_API_KEY = st.secrets["ORS_API_KEY"]
EIA_API_KEY = st.secrets.get("EIA_API_KEY", None)

geocoder = OpenCageGeocode(OPENCAGE_KEY)
client = openrouteservice.Client(key=ORS_API_KEY)

# US states list
US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY",
    "LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND",
    "OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY"
}

# Helpers

def nominatim_search(query):
    res = requests.get("https://nominatim.openstreetmap.org/search", 
                       params={"q": query, "format": "json", "addressdetails": 1, "limit": 5},
                       headers={"User-Agent": "streamlit-trip-planner"})
    return [r['display_name'] for r in res.json()] if res.status_code == 200 else []

def get_coordinates(addr):
    r = geocoder.geocode(addr)
    return (r[0]['geometry']['lat'], r[0]['geometry']['lng'])

def extract_state(addr):
    parts = addr.split(",")
    if len(parts) < 2: return None
    last = parts[-2].strip().upper()
    for st_ in US_STATES:
        if st_ in last:
            return st_
    return None

def get_state_price(state):
    if not (EIA_API_KEY and state in US_STATES):
        return None
    url = f"https://api.eia.gov/v2/petroleum/pri/gnd/data/?api_key={EIA_API_KEY}&frequency=weekly&data[0]=value&facets[state][]={state}&facets[fuelType][]=Regular&sort[0][column]=period&sort[0][direction]=desc&offset=0&length=1"
    resp = requests.get(url)
    if resp.status_code==200:
        dd = resp.json().get("response", {}).get("data", [])
        if dd: return float(dd[0]['value'])
    return None

# UI
st.title("Multi‑Stop Trip Planner with State‑Weighted Gas Price")

# Vehicle input
make = st.text_input("Vehicle Make", "Toyota")
model = st.text_input("Vehicle Model", "Camry")
year = st.selectbox("Vehicle Year", list(range(2024, 1999, -1)))
is_ev = st.selectbox("Is it an EV?", ["No","Yes"])
mpg = None if is_ev=="Yes" else st.number_input("Enter MPG", value=25.0)

# Locations
start_input = st.text_input("Start Address")
start_opts = nominatim_search(start_input) if start_input else []
start_addr = st.selectbox("Select Start", start_opts) if start_opts else None

num_stops = st.number_input("Number of stops", 0, 5, 0)
stops = []
for i in range(num_stops):
    s_in = st.text_input(f"Stop {i+1}")
    s_opts = nominatim_search(s_in) if s_in else []
    sel = st.selectbox(f"Select Stop {i+1}", s_opts) if s_opts else None
    if sel: stops.append(sel)

end_input = st.text_input("Destination Address")
end_opts = nominatim_search(end_input) if end_input else []
end_addr = st.selectbox("Select Destination", end_opts) if end_opts else None

if st.button("Calculate Route") and start_addr and end_addr:
    addrs = [start_addr] + stops + [end_addr]
    coords = [get_coordinates(a) for a in addrs]
    route = client.directions(coordinates=[(lon,lat) for lat,lon in coords],
                              profile="driving-car", format="geojson")
    prop = route['features'][0]['properties']['summary']
    dist_mi = prop['distance']/1000*0.621371
    duration_min = prop['duration']/60

    # Build weighted avg price
    segs = list(zip(coords[:-1], coords[1:]))
    total_dist = 0
    weighted_sum = 0
    for (lat1,lon1),(lat2,lon2) in segs:
        seg_dist_km = openrouteservice.convert.decode_polyline(route['features'][0]['geometry'])['features'][0]['properties']['summary']['distance']/1000
        state = extract_state(addrs[0])
        gp = get_state_price(state) or 3.60
        weighted_sum += gp * seg_dist_km
        total_dist += seg_dist_km

    avg_price = weighted_sum/total_dist if total_dist else get_state_price(extract_state(start_addr)) or 3.60
    fuel_used = dist_mi/mpg
    cost = fuel_used * avg_price

    st.markdown(f"**Distance:** {dist_mi:.2f} miles")
    st.markdown(f"**Duration:** {duration_min:.1f} minutes")
    st.markdown(f"**Weighted Avg Gas Price:** ${avg_price:.2f}")
    st.markdown(f"**Fuel Used:** {fuel_used:.2f} gal")
    st.markdown(f"**Estimated Trip Cost:** ${cost:.2f}")

    m = folium.Map(location=coords[0], zoom_start=6)
    for pt,add in zip(coords,addrs):
        folium.Marker(pt, popup=add).add_to(m)
    folium.GeoJson(route, name="route").add_to(m)
    folium_static(m)
