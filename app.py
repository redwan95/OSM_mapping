
import streamlit as st
import requests
from opencage.geocoder import OpenCageGeocode
import openrouteservice
import folium
from streamlit_folium import folium_static

# 🔐 API keys from Streamlit secrets
OPENCAGE_KEY = st.secrets["OPENCAGE_KEY"]
ORS_API_KEY = st.secrets["ORS_API_KEY"]

# Clients
geocoder = OpenCageGeocode(OPENCAGE_KEY)
client = openrouteservice.Client(key=ORS_API_KEY)

# 🌐 Function to fetch address suggestions using OpenStreetMap Nominatim
def nominatim_search(query):
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": query,
        "format": "json",
        "addressdetails": 1,
        "limit": 5,
    }
    headers = {"User-Agent": "streamlit-trip-planner-demo"}
    try:
        res = requests.get(url, params=params, headers=headers)
        if res.status_code == 200:
            return [r['display_name'] for r in res.json()]
    except:
        return []
    return []

st.title("Trip Planner with OSM Autocomplete")

# 📍 Input with OSM autocomplete
start_query = st.text_input("Type Start Address")
start_options = nominatim_search(start_query) if start_query else []
start_address = st.selectbox("Select Start Address", start_options) if start_options else None

end_query = st.text_input("Type Destination Address")
end_options = nominatim_search(end_query) if end_query else []
end_address = st.selectbox("Select Destination Address", end_options) if end_options else None

# Vehicle info
vehicle_mpg = st.number_input("Vehicle MPG", min_value=5, max_value=100, value=25)
gas_price = st.number_input("Gas Price (USD/gallon)", min_value=0.0, value=3.70)

# 🧠 Route Calculation
if st.button("Calculate Route") and start_address and end_address:
    try:
        # Geocode both
        start_result = geocoder.geocode(start_address)
        end_result = geocoder.geocode(end_address)
        start_coords = (start_result[0]['geometry']['lat'], start_result[0]['geometry']['lng'])
        end_coords = (end_result[0]['geometry']['lat'], end_result[0]['geometry']['lng'])

        # Directions
        route = client.directions(
            coordinates=[(start_coords[1], start_coords[0]), (end_coords[1], end_coords[0])],
            profile='driving-car',
            format='geojson'
        )

        # Metrics
        dist_km = route['features'][0]['properties']['summary']['distance'] / 1000
        dist_mi = dist_km * 0.621371
        duration = route['features'][0]['properties']['summary']['duration'] / 60
        fuel = dist_mi / vehicle_mpg
        cost = fuel * gas_price

        # Output summary
        st.success(f"Distance: {dist_km:.2f} km / {dist_mi:.2f} mi")
        st.info(f"Duration: {duration:.1f} minutes")
        st.info(f"Fuel needed: {fuel:.2f} gallons")
        st.info(f"Trip cost: ${cost:.2f}")

        # Map
        m = folium.Map(location=start_coords, zoom_start=6)
        folium.Marker(start_coords, popup="Start", icon=folium.Icon(color="green")).add_to(m)
        folium.Marker(end_coords, popup="Destination", icon=folium.Icon(color="red")).add_to(m)
        folium.GeoJson(route, name="Route").add_to(m)
        folium_static(m)

    except Exception as e:
        st.error(f"Error calculating route: {e}")
