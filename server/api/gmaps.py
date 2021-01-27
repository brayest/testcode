import googlemaps
import os

gmaps = googlemaps.Client(key=os.environ.get("GOOGLE_MAPS_API_KEY", "AIza"))
# AIza is hardcoded in googlemaps API as testing key
