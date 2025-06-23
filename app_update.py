import streamlit as st
import requests
from opencage.geocoder import OpenCageGeocode
import openrouteservice
import folium
from streamlit_folium import folium_static

# Load API keys
OPENCAGE_KEY = st.secrets["OPENCAGE_KEY"]
ORS_API_KEY = st.secrets["ORS_API_KEY"]
EIA_API_KEY = st.secrets.get("EIA_API_KEY")

geocoder = OpenCageGeocode(OPENCAGE_KEY)
client = openrouteservice.Client(key=ORS_API_KEY)

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS",
    "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY",
    "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY"
}

def nominatim_search(query):
    res = requests.get("https://nominatim.openstreetmap.org/search",
                       params={"q": query, "format": "json", "addressdetails": 1, "limit": 5},
                       headers={"User-Agent": "streamlit-trip-planner"})
    return [r['display_name'] for r in res.json()] if res.status_code == 200 else []

def get_coordinates(addr):
    r = geocoder.geocode(addr)
    return (r[0]['geometry']['lat'], r[0]['geometry']['lng'])

def reverse_geocode_state(lat, lon):
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {"lat": lat, "lon": lon, "format": "json", "zoom": 5, "addressdetails": 1}
    res = requests.get(url, headers={"User-Agent": "streamlit-trip-planner"}, params=params)
    if res.status_code == 200:
        try:
            return res.json()['address']['state']
        except:
            return None
    return None

def state_to_abbr(state_name):
    try:
        from us.states import lookup
        return lookup(state_name).abbr
    except:
        return None

def get_state_price(state_abbr):
    if not (EIA_API_KEY and state_abbr in US_STATES):
        return None
    url = f"https://api.eia.gov/v2/petroleum/pri/gnd/data/?api_key={EIA_API_KEY}&frequency=weekly&data[0]=value&facets[state][]={state_abbr}&facets[fuelType][]=Regular&sort[0][column]=period&sort[0][direction]=desc&offset=0&length=1"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json().get("response", {}).get("data", [])
        if data:
            return float(data[0]['value'])
    return None

# UI
st.title("🚗 Multi‑Stop Trip Planner with State‑Weighted Fuel Price")

# Vehicle info
col1, col2 = st.columns(2)
with col1:
    mpg = st.number_input("Enter Estimated MPG", min_value=5.0, value=25.0)
with col2:
    is_ev = st.selectbox("Is this an EV?", ["No", "Yes"])
    if is_ev == "Yes":
        mpg = 0

# Locations
start_input = st.text_input("Start Address")
start_opts = nominatim_search(start_input) if start_input else []
start_addr = st.selectbox("Select Start", start_opts) if start_opts else None

stops = []
num_stops = st.number_input("Number of Stops", 0, 5, 0)
for i in range(num_stops):
    s_in = st.text_input(f"Stop {i+1}")
    s_opts = nominatim_search(s_in) if s_in else []
    stop = st.selectbox(f"Select Stop {i+1}", s_opts) if s_opts else None
    if stop:
        stops.append(stop)

end_input = st.text_input("Destination Address")
end_opts = nominatim_search(end_input) if end_input else []
end_addr = st.selectbox("Select Destination", end_opts) if end_opts else None

# Calculate
if st.button("Calculate Route") and start_addr and end_addr:
    try:
        all_addresses = [start_addr] + stops + [end_addr]
        coords = [get_coordinates(addr) for addr in all_addresses]
        ors_coords = [(lon, lat) for lat, lon in coords]
        route = client.directions(coordinates=ors_coords, profile="driving-car", format="geojson")

        segments = list(zip(coords[:-1], coords[1:]))
        state_prices = {}
        weighted_price_sum = 0
        total_segment_km = 0

        for (lat1, lon1), (lat2, lon2) in segments:
            mid_lat = (lat1 + lat2) / 2
            mid_lon = (lon1 + lon2) / 2
            state_name = reverse_geocode_state(mid_lat, mid_lon)
            state_abbr = state_name[:2].upper() if state_name else None
            if state_abbr and state_abbr not in state_prices:
                price = get_state_price(state_abbr)
                if price:
                    state_prices[state_abbr] = price
            else:
                price = state_prices.get(state_abbr, 3.60)

            # Approximate distance between two points (Haversine not needed here for demo)
            seg_dist = client.directions(coordinates=[(lon1, lat1), (lon2, lat2)], profile='driving-car', format='geojson')['features'][0]['properties']['summary']['distance'] / 1000
            weighted_price_sum += seg_dist * price
            total_segment_km += seg_dist

        avg_price = weighted_price_sum / total_segment_km if total_segment_km else 3.60

        # Final trip data
        total_km = route['features'][0]['properties']['summary']['distance'] / 1000
        total_miles = total_km * 0.621371
        duration = route['features'][0]['properties']['summary']['duration'] / 60
        fuel_used = total_miles / mpg if mpg else 0
        cost = fuel_used * avg_price

        st.markdown(f"**Total Distance:** {total_km:.2f} km / {total_miles:.2f} miles")
        st.markdown(f"**Duration:** {duration:.1f} minutes")
        st.markdown(f"**Weighted Avg Fuel Price:** ${avg_price:.2f}/gal")
        st.markdown(f"**Fuel Used:** {fuel_used:.2f} gal")
        st.markdown(f"**Estimated Trip Cost:** ${cost:.2f}")

        m = folium.Map(location=coords[0], zoom_start=6)
        for pt, label in zip(coords, all_addresses):
            folium.Marker(pt, popup=label).add_to(m)
        folium.GeoJson(route, name="Route").add_to(m)
        folium_static(m)

    except Exception as e:
        st.error(f"❌ Error occurred: {e}")
