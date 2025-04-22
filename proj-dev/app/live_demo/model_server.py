import os
import sys
import gc
import time
import logging
import psutil
import requests
import os
from supabase import create_client, Client
from dotenv import load_dotenv
from typing import Optional, Dict, Any, List
from functools import lru_cache
from flask import Flask, request, jsonify


import spacy
from flask import Flask, request, jsonify

from entity_extraction import extract_ent_sent, clean_text

### Location standardization setup
load_dotenv()

url: str = os.environ.get('SUPABASE_URL')
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

app = Flask(__name__)

US_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia"
}

state_coordinates = {
    'Alabama': ('32.7794', '-86.8287'),
    'Alaska': ('64.0685', '-152.2782'),
    'Arizona': ('34.2744', '-111.6602'),
    'Arkansas': ('34.8938', '-92.4426'),
    'California': ('37.1841', '-119.4696'),
    'Colorado': ('38.9972', '-105.5478'),
    'Connecticut': ('41.6219', '-72.7273'),
    'Delaware': ('38.9896', '-75.5050'),
    'Florida': ('28.6305', '-82.4497'),
    'Georgia': ('32.6415', '-83.4426'),
    'Hawaii': ('20.2927', '-156.3737'),
    'Idaho': ('44.3509', '-114.6130'),
    'Illinois': ('40.0417', '-89.1965'),
    'Indiana': ('39.8942', '-86.2816'),
    'Iowa': ('42.0751', '-93.4960'),
    'Kansas': ('38.4937', '-98.3804'),
    'Kentucky': ('37.5347', '-85.3021'),
    'Louisiana': ('31.0689', '-91.9968'),
    'Maine': ('45.3695', '-69.2428'),
    'Maryland': ('39.0550', '-76.7909'),
    'Massachusetts': ('42.2596', '-71.8083'),
    'Michigan': ('44.3467', '-85.4102'),
    'Minnesota': ('46.2807', '-94.3053'),
    'Mississippi': ('32.7364', '-89.6678'),
    'Missouri': ('38.3566', '-92.4580'),
    'Montana': ('47.0527', '-109.6333'),
    'Nebraska': ('41.5378', '-99.7951'),
    'Nevada': ('39.3289', '-116.6312'),
    'New Hampshire': ('43.6805', '-71.5811'),
    'New Jersey': ('40.1907', '-74.6728'),
    'New Mexico': ('34.4071', '-106.1126'),
    'New York': ('42.9538', '-75.5268'),
    'North Carolina': ('35.5557', '-79.3877'),
    'North Dakota': ('47.4501', '-100.4659'),
    'Ohio': ('40.2862', '-82.7937'),
    'Oklahoma': ('35.5889', '-97.4943'),
    'Oregon': ('43.9336', '-120.5583'),
    'Pennsylvania': ('40.8781', '-77.7996'),
    'Rhode Island': ('41.6762', '-71.5562'),
    'South Carolina': ('33.9169', '-80.8964'),
    'South Dakota': ('44.4443', '-100.2263'),
    'Tennessee': ('35.8580', '-86.3505'),
    'Texas': ('31.4757', '-99.3312'),
    'Utah': ('39.3055', '-111.6703'),
    'Vermont': ('44.0687', '-72.6658'),
    'Virginia': ('37.5215', '-78.8537'),
    'Washington': ('47.3826', '-120.4472'),
    'West Virginia': ('38.6409', '-80.6227'),
    'Wisconsin': ('44.6243', '-89.9941'),
    'Wyoming': ('42.9957', '-107.5512'),
    'District of Columbia': ('38.9101', '-77.0147')
}

@lru_cache(maxsize=2048)
def lookup_city_state_country(loc_text: str):
    norm = loc_text.strip()
    norm_up = norm.upper()
    norm_title = norm.title()
    norm_lower = norm.lower()

    # ---------- 1) State code / state name ----------
    if norm_up in US_STATE_NAMES or norm_title in US_STATE_NAMES.values():
        # exact ADM1 lookup
        resp = (
            supabase.table("gazetteer")
            .select("name, featureCode, stateCode, countryCode, latitude, longitude")
            .eq("featureCode", "ADM1")
            .or_(f"stateCode.eq.{norm_up},name.eq.{norm_title}")
            .limit(1)
            .execute()
        )
    else:
        resp = (
            supabase.table("gazetteer")
            .select("name, featureCode, stateCode, countryCode, latitude, longitude")
            .eq("name", norm_title)                     # 2) exact city name
            .or_("featureCode.ilike.PPL%")
            .limit(1)
            .execute()
        )

        # ---------- 3) alternate_list token match ----------
        if not resp.data and len(norm) > 2:
            # alternate_list is a comma‑separated list, so anchor with commas
            resp = (
                supabase.table("gazetteer")
                .select("name, featureCode, stateCode, countryCode, latitude, longitude")
                .ilike("alternate_list", f"%,{norm_lower},%")
                .ilike("featureCode", "PPL%")
                .order("population", desc=True)
                .limit(1)
                .execute()
            )

        # ---------- 4) fuzzy fallback (optional) ----------
        if not resp.data and len(norm) > 3:
            resp = (
                supabase.table("gazetteer")
                .select("name, featureCode, stateCode, countryCode, latitude, longitude")
                .ilike("alternate_list", f"%{norm_lower}%")
                .ilike("featureCode", "PPL%")
                .order("population", desc=True)
                .limit(1)
                .execute()
            )

    print(resp.data if resp.data else "No data found")

    city = state = region = place = state_code = country_code = latitude = longitude = None

    if resp.data:
        record = resp.data[0]
        feature = (record.get('featureCode') or "").upper()
        place = record.get('name')
        state_code = record.get('stateCode')
        country_code = record.get('countryCode')
        latitude = record.get('latitude')
        longitude = record.get('longitude')


        if feature == "ADM1":
            if state_code in US_STATE_NAMES:
                state = US_STATE_NAMES.get(state_code)
            else:
                state = state_code
        elif feature.startswith("PPL") or feature.startswith("ADM"):
            city  = place
            state = US_STATE_NAMES.get(state_code) if state_code in US_STATE_NAMES else None
        else:
            city = place


    all_states = {s.lower() for s in US_STATE_NAMES.values()} | {k.lower() for k in US_STATE_NAMES}
    if not state:
        city = None
        if norm.lower() in all_states: #i have no idea what the fuck this is here for but it is and it works
            region = None
        else:
            region = norm.title()
    if region:
        for state_us in US_STATE_NAMES.values():
            if state_us.lower() in region.lower():
                state = state_us
                latitude, longitude = state_coordinates.get(state_us, (None, None))
                break

    return {
        "city": city,
        "state": state,
        "region": region,
        "country": country_code,
        "latitude": latitude,
        "longitude": longitude
    }


def standardize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    row["locations"] should be a list of raw location strings.
    Returns a dict with 'city','state','region','country','all_locations'.
    """
    locs = row.get("locations") or []
    results: List[Dict[str, Any]] = []

    for loc in locs:
        match = lookup_city_state_country(loc)
        if match and match.get("state"):
            results.append({
                "location": loc,
                **match
            })

    if not results:
        return {
            "city": None,
            "state": None,
            "region": None,
            "country": None,
            "latitude": None,
            "longitude": None
        }
    
    first, *rest = results
    return {
        "city": first.get("city"),
        "state": first.get("state"),
        "region": first.get("region"),
        "country": first.get("country"),
        "latitude": first.get("latitude"),
        "longitude": first.get("longitude"),
        "all_locations": rest,
    }


######################
# Config and Globals #
######################

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Global references to loaded data
nlp = None

APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
#print(APP_DIR)
###########################
# Initialization Function #
###########################

def initialize_globals():
    """
    Load the spaCy model and gazetteer data once, if not already loaded.
    """
    global nlp

    logger.info("Initializing model server...")
    process = psutil.Process(os.getpid())
    logger.info(f"Memory usage before loading data: {process.memory_info().rss / 1024 / 1024:.2f} MB")

    # 1) Load spaCy Model
    try:
        nlp_path = os.path.join(os.path.join(APP_DIR, "app", "disaster_ner"))
        logger.info(f"Loading spaCy model from: {nlp_path}")
        nlp = spacy.load(nlp_path)
    except Exception as e:
        logger.error(f"Could not load custom spaCy model from {nlp_path}. Error: {e}")
        logger.info("Falling back to en_core_web_sm (basic model).")
        try:
            nlp = spacy.load("en_core_web_sm")
        except Exception as e2:
            logger.error(f"Could not load fallback 'en_core_web_sm': {e2}")
            nlp = None  # If we can’t load anything, set to None

    # Force garbage collection after loading
    gc.collect() 

######################
# Utility Functions  #
######################

def convert_sets_to_lists(obj):
    """Convert sets in an object (nested) to lists for JSON serialization."""
    if isinstance(obj, set):
        return list(obj)
    elif isinstance(obj, dict):
        return {k: convert_sets_to_lists(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_sets_to_lists(item) for item in obj]
    return obj

###########################
# Flask Endpoint Handlers #
###########################

@app.route('/health', methods=['GET'])
def health_check():
    """
    Health check endpoint: returns status of the model server's critical components.
    """
    status = {
        'spaCy': 'loaded' if nlp else 'missing',
    }
    # If everything is loaded, we consider it 'healthy'
    overall_state = 'healthy' if (nlp is not None) else 'degraded'
    return jsonify({'status': overall_state, 'details': status})

@app.route('/extract_entities', methods=['POST'])
def extract_entities():
    """
    Main endpoint to process a text for entity extraction and location standardization.
    """
    start_time = time.time()

    data = request.json or {}
    text = data.get('text', '')
    if not text:
        return jsonify({'error': 'No text provided'}), 400

    logger.info(f"extract_entities called, text length={len(text)}")
    
    # Ensure everything is loaded
    #initialize_globals()
    # Extract using spaCy-based logic or fallback
    if nlp:
        ent_sent = extract_ent_sent(text)
        ent_sent = convert_sets_to_lists(ent_sent)
    else:
        # If no spaCy loaded, return minimal structure
        ent_sent = {
            "disasters": [],
            "locations": [],
            "sentiment": "Neutral",
            "polarity": 0.0
        }

    #print("locations in ent sent before standardization (model server): ", ent_sent['locations'])

    # Attempt location standardization if gazetteer is loaded
    if ent_sent['disasters'] and ent_sent['locations']:
        print(ent_sent['disasters'], ent_sent['locations'])
        try:
            loc_series = standardize_row({'locations': ent_sent['locations']})
            # Update ent_sent with the standardization keys
            print(loc_series)
            for key, val in loc_series.items():
                ent_sent[key] = val
            

            print("ent sent after standardization:", ent_sent)
            # De-duplicate the 'locations' list if present
            if 'locations' in ent_sent and isinstance(ent_sent['locations'], list):
                ent_sent['locations'] = list(set(ent_sent['locations']))
        except Exception as e:
            logger.error(f"Location standardization error: {e}")
            # Provide fallback
            ent_sent.update({
                "city": None,
                "state": None,
                "region": None,
                "country": None,
                "latitude": None,
                "longitude": None,
                "all_locations": []
            })

    #print("locations in ent sent after standardization (model server): ", ent_sent['city'], ent_sent['all_locations'])
    elapsed = time.time() - start_time
    logger.info(f"extract_entities completed in {elapsed:.2f}s")

    return jsonify(ent_sent)

################
# Main Routine #
################

if __name__ == '__main__':
    # Only do the global initialization if we directly run this file
    initialize_globals()
    
    import waitress
    logger.info("Starting model server on port 5000 with Waitress")
    try:
        from waitress import serve
        serve(app, port=5000, threads=4)
    except ImportError:
        logger.warning("Waitress not installed, falling back to Flask dev server.")
        app.run(port=5000, threaded=True)
    except Exception as e:
        logger.critical(f"Server failed to start: {e}")
        sys.exit(1)
