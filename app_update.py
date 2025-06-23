import streamlit as st
import requests
from opencage.geocoder import OpenCageGeocode
import openrouteservice
import folium
from streamlit_folium import folium_static

# --- Load API Keys from Streamlit secrets ---
OPENCAGE_KEY = st.secrets["OPENCAGE_KEY"]
ORS_API_KEY = st.secrets["ORS_API_KEY"]

# --- Initialize clients ---
geocoder = OpenCageGeocode(OPENCAGE_KEY)
client = openrouteservice.Client(key=ORS_API_KEY)

# --- Functions ---
def nominatim_search(query):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": query, "format": "json", "addressdetails": 1, "limit": 5}
    headers = {"User-Agent": "streamlit-trip-planner"}
    res = requests.get(url, params=params, headers=headers)
    return [r['display_name'] for r in res.json()] if res.status_code == 200 else []

def get_coordinates(address):
    result = geocoder.geocode(address)
    return (result[0]['geometry']['lat'], result[0]['geometry']['lng'])

def get_average_gas_price_us():
    # Try AAA API or EIA API or fallback to static average
    # Here we use a simple free API for demo; replace with your key/service if needed

    # Example: Using AAA Public API (replace YOUR_API_KEY if available)
    # aaa_api_url = "https://gaspricesapi.aaa.com/api/..."

    # For demonstration, we use EIA weekly average retail gasoline price:
    eia_api_key = st.secrets.get("EIA_API_KEY", None)
    if eia_api_key:
        url = f"https://api.eia.gov/v2/petroleum/pri/gnd/data/?api_key={eia_api_key}&frequency=weekly&data[0]=value&facets[fuelType][]=Regular&sort[0][column]=period&sort[0][direction]=desc&offset=0&length=1"
        try:
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                val = data['response']['data'][0]['value']
                return float(val)
        except:
            pass

    # Fallback average price (USD per gallon)
    return 3.60

def get_vehicle_mpg(make, model, year):
    try:
        url = f"https://www.fueleconomy.gov/ws/rest/vehicle/menu/options?year={year}&make={make}&model={model}"
        res = requests.get(url)
        if res.status_code != 200:
            return None
        from xml.etree import ElementTree as ET
        root = ET.fromstring(res.content)
        vehicle_id = root.find('.//value')
        if vehicle_id is None:
            return None
        vehicle_id = vehicle_id.text
        mpg_url = f"https://www.fueleconomy.gov/ws/rest/vehicle/{vehicle_id}"
        mpg_res = requests.get(mpg_url)
        mpg_root = ET.fromstring(mpg_res.content)
        return float(mpg_root.findtext("comb08"))
    except:
        return None

# --- UI ---
st.title("Multi-Stop Trip Planner with Average US Gas Price")

col1, col2 = st.columns(2)
with col1:
    make = st.text_input("Vehicle Make", value="Toyota")
    model = st.text_input("Vehicle Model", value="Camry")
with col2:
    year = st.selectbox("Vehicle Year", list(range(2024, 1999, -1)))
    is_ev = st.selectbox("Is it an EV?", ["No", "Yes"])

mpg = None if is_ev == "Yes" else get_vehicle_mpg(make, model, year)
if mpg:
    st.success(f"Detected MPG: {mpg}")
else:
    mpg = st.number_input("Enter Estimated MPG", min_value=5.0, value=25.0)

start_input = st.text_input("Start Address")
start_options = nominatim_search(start_input) if start_input else []
start_address = st.selectbox("Select Start Address", options=start_options) if start_options else None

stops = []
num_stops = st.number_input("Number of Stops", min_value=0, max_value=5, value=0)
for i in range(num_stops):
    stop_input = st.text_input(f"Stop {i+1}")
    stop_options = nominatim_search(stop_input) if stop_input else []
    stop_address = st.selectbox(f"Select Stop {i+1}", options=stop_options) if stop_options else None
    if stop_address:
        stops.append(stop_address)

end_input = st.text_input("Destination Address")
end_options = nominatim_search(end_input) if end_input else []
end_address = st.selectbox("Select Destination Address", options=end_options) if end_options else None

if st.button("Calculate Route") and start_address and end_address:
    try:
        all_points = [start_address] + stops + [end_address]
        coords = [get_coordinates(addr) for addr in all_points]
        ors_coords = [(lon, lat) for lat, lon in coords]

        route = client.directions(
            coordinates=ors_coords,
            profile='driving-car',
            format='geojson'
        )

        distance_km = route['features'][0]['properties']['summary']['distance'] / 1000
        distance_miles = distance_km * 0.621371
        duration_min = route['features'][0]['properties']['summary']['duration'] / 60

        fuel_used = distance_miles / mpg if mpg else 0

        avg_gas_price = get_average_gas_price_us()
        trip_cost = fuel_used * avg_gas_price

        st.markdown(f"**Distance:** {distance_km:.2f} km / {distance_miles:.2f} miles")
        st.markdown(f"**Duration:** {duration_min:.1f} minutes")
        st.markdown(f"**Fuel Used:** {fuel_used:.2f} gallons")
        st.markdown(f"**Average US Gas Price:** ${avg_gas_price:.2f} per gallon")
        st.markdown(f"**Estimated Trip Cost:** ${trip_cost:.2f}")

        m = folium.Map(location=coords[0], zoom_start=6)
        for i, coord in enumerate(coords):
            folium.Marker(coord, popup=all_points[i]).add_to(m)
        folium.GeoJson(route, name="Route").add_to(m)
        folium_static(m)

    except Exception as e:
        st.error(f"Error: {e}")
