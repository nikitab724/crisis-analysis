import locationtagger
from geopy.geocoders import Nominatim

def extract_location(text):
    """Extract location information from text"""
    locations = locationtagger.find_locations(text=text)
    
    # Return the first location found (which is the most likely match)
    if locations.cities:
        return locations.cities[0]
    elif locations.regions:
        return locations.regions[0]
    elif locations.countries:
        return locations.countries[0]
    else:
        return None
    
def get_lat_lon(location):
    """Get latitude and longitude for a location"""
    geolocator = Nominatim(user_agent="geoapi")
    try:
        loc = geolocator.geocode(location)
        return loc.latitude, loc.longitude
    except:
        return None, None
    
if __name__ == '__main__':
    text = "There is a fire in California"
    print(extract_location(text))