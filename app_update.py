import streamlit as st
import requests
from opencage.geocoder import OpenCageGeocode
import openrouteservice
import folium
from streamlit_folium import folium_static

# Load API Keys
OPENCAGE_KEY = st.secrets["OPENCAGE_KEY"]
ORS_API_KEY = st.secrets["ORS_API_KEY"]
EIA_API_KEY = st.secrets.get("EIA_API_KEY", None)

geocoder = OpenCageGeocode(OPENCAGE_KEY)
client = openrouteservice.Client(key=ORS_API_KEY)

US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY",
    "LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND",
    "OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY"
}

def nominatim_search(query):
    params = {"q": query, "format": "json", "addressdetails": 1, "limit": 5}
    headers = {"User-Agent": "streamlit-trip-planner"}
    res = requests.get("https://nominatim.openstreetmap.org/search", params=params, headers=headers)
    return [r['display_name'] for r in res.json()] if res.status_code == 200 else []

def get_coords(address):
    r = geocoder.geocode(address)
    return (r[0]['geometry']['lat'], r[0]['geometry']['lng'])

def extract_state(address):
    parts = address.split(",")
    if len(parts) < 2: return None
    seg = parts[-2].strip().upper()
    for s in US_STATES:
        if s in seg:
            return s
    return None

def get_state_price(state_abbr):
    if not EIA_API_KEY or state_abbr not in US_STATES:
        return None
    url = (
      f"https://api.eia.gov/v2/petroleum/pri/gnd/data/"
      f"?api_key={EIA_API_KEY}&frequency=weekly&data[0]=value"
      f"&facets[state][]={state_abbr}"
      f"&facets[fuelType][]=Regular"
      f"&sort[0][column]=period&sort[0][direction]=desc"
      f"&offset=0&length=1"
    )
    res = requests.get(url)
    if res.status_code == 200:
        d = res.json()
        arr = d.get('response', {}).get('data', [])
        if arr:
            return float(arr[0]['value'])
    return None

def avg_price_for_route(addresses):
    prices = []
    for addr in addresses:
        st_abbr = extract_state(addr)
        price = get_state_price(st_abbr) if st_abbr else None
        if price:
            prices.append(price)
    return sum(prices)/len(prices) if prices else None

def get_vehicle_mpg(make, model, year):
    try:
        xml = requests.get(f"https://www.fueleconomy.gov/ws/rest/vehicle/menu/options?year={year}&make={make}&model={model}")
        if xml.status_code != 200: return None
        import xml.etree.ElementTree as ET
        vid = ET.fromstring(xml.content).find('.//value')
        if vid is None: return None
        vid = vid.text
        detail = requests.get(f"https://www.fueleconomy.gov/ws/rest/vehicle/{vid}")
        return float(ET.fromstring(detail.content).findtext("comb08"))
    except: return None

# UI
st.title("Multi‑Stop Trip Planner with State‑Based Fuel Cost")

make = st.text_input("Vehicle Make", "Toyota")
model = st.text_input("Vehicle Model", "Camry")
year = st.selectbox("Year", list(range(2024, 1999, -1)))
is_ev = st.selectbox("EV?", ["No", "Yes"])

mpg = None if is_ev=="Yes" else get_vehicle_mpg(make, model, year)
if mpg:
    st.success(f"Detected MPG: {mpg:.1f}")
else:
    mpg = st.number_input("Manual MPG", min_value=5.0, value=25.0)

start_opts = nominatim_search(st.text_input("Start Address"))
start_addr = st.selectbox("Choose Start", start_opts) if start_opts else None

stops = []
for i in range(st.number_input("Number of Stops", 0, 5, 0)):
    opts = nominatim_search(st.text_input(f"Stop {i+1}"))
    addr = st.selectbox(f"Choose Stop {i+1}", opts) if opts else None
    if addr: stops.append(addr)

end_opts = nominatim_search(st.text_input("Destination Address"))
end_addr = st.selectbox("Choose Destination", end_opts) if end_opts else None

if st.button("Calculate") and start_addr and end_addr:
    addrs = [start_addr] + stops + [end_addr]
    coords = [get_coords(a) for a in addrs]
    
    route = client.directions(
        coordinates=[(lon, lat) for lat, lon in coords],
        profile='driving-car',
        format='geojson'
    )
    summary = route['features'][0]['properties']['summary']
    dist_km = summary['distance']/1000
    dist_mi = dist_km*0.621371
    dur_min = summary['duration']/60

    fuel = dist_mi/mpg
    avg_price = avg_price_for_route(addrs)
    if not avg_price:
        st.warning("Could not fetch fuel prices; using fallback $3.60")
        avg_price = 3.60
    cost = fuel * avg_price

    st.markdown(f"**Distance:** {dist_km:.1f} km / {dist_mi:.1f} mi")
    st.markdown(f"**Duration:** {dur_min:.1f} min")
    st.markdown(f"**Fuel:** {fuel:.1f} gal")
    st.markdown(f"**Avg Fuel Price:** ${avg_price:.2f}/gal")
    st.markdown(f"**Trip Cost:** **${cost:.2f}**")

    m = folium.Map(location=coords[0], zoom_start=6)
    for name, coord in zip(addrs, coords):
        folium.Marker(coord, popup=name).add_to(m)
    folium.GeoJson(route).add_to(m)
    folium_static(m)
