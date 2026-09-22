import ast
import os
import sys
import gc
import time
import logging
import psutil
from supabase import create_client, Client
from dotenv import load_dotenv
from typing import Dict, Any, List
from functools import lru_cache
from flask import Flask, request, jsonify

from entity_extraction import extract_ent_sent, load_nlp
from gazetteer import US_STATE_NAMES
from location_context import location_candidates, state_code

### Location standardization setup
load_dotenv()

url: str = os.environ.get('SUPABASE_URL')
key: str = os.environ.get("SUPABASE_KEY")
if not url or not key:
    raise RuntimeError("Set SUPABASE_URL and SUPABASE_KEY; see .env.example and README.md.")
supabase: Client = create_client(url, key)

app = Flask(__name__)

GAZETTEER_FIELDS = "name, featureCode, stateCode, countryCode, latitude, longitude, alternate_list"


def exact_aliases(value):
    """The restored column stores Python list literals; older imports used CSV tokens."""
    if not value:
        return set()
    try:
        aliases = ast.literal_eval(value)
    except (ValueError, SyntaxError):
        aliases = value.split(",") if "," in value and not value.lstrip().startswith("[") else []
    if not isinstance(aliases, list):
        return set()
    return {alias.strip().casefold() for alias in aliases if isinstance(alias, str)}


@lru_cache(maxsize=2048)
def lookup_city_state_country(loc_text: str, state_hint=None):
    """Resolve exact names/aliases, constrained by an explicit state when available."""
    norm = loc_text.strip()
    code = state_code(norm)
    empty = dict(city=None, state=None, region=norm, country=None, latitude=None, longitude=None)
    # Treat user text as a literal place name, never an ILIKE wildcard pattern.
    if not norm or any(char in norm for char in "%_*\\"):
        return empty

    def query():
        return supabase.table("gazetteer").select(GAZETTEER_FIELDS).eq("countryCode", "US")

    def cities():
        result = query().ilike("featureCode", "PPL%")
        if state_hint:
            result = result.eq("stateCode", state_hint)
        return result.order("population", desc=True, nullsfirst=False).order("geonameid")

    if code:
        records = query().eq("featureCode", "ADM1").eq("stateCode", code).limit(1).execute().data
    else:
        # ILIKE without wildcards preserves mixed-case names such as McAllen.
        records = cities().ilike("name", norm).limit(1).execute().data
        if not records and len(norm) > 2:
            candidates = cities().ilike("alternate_list", f"%{norm}%").limit(25).execute().data
            records = [record for record in candidates if norm.casefold() in exact_aliases(record.get("alternate_list"))]
    if not records:
        return empty
    record = records[0]
    state = US_STATE_NAMES.get(record.get("stateCode"))
    if not state or record.get("countryCode") != "US":
        return empty
    return {
        "city": None if record.get("featureCode") == "ADM1" else record.get("name"),
        "state": state, "region": None, "country": "US",
        "latitude": record.get("latitude"), "longitude": record.get("longitude"),
    }


def standardize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    row["locations"] should be a list of raw location strings.
    Returns a dict with 'city','state','region','country','all_locations'.
    """
    locs = row.get("locations") or []
    results: List[Dict[str, Any]] = []

    seen = set()
    for loc, place, hint in location_candidates(locs, row.get("text", "")):
        match = lookup_city_state_country(state_code(place) or place.casefold(), hint)
        identity = tuple(match.get(key) for key in ("city", "state", "latitude", "longitude"))
        if match.get("state") and identity not in seen:
            seen.add(identity)
            results.append({"location": loc, **match})

    if not results:
        return {
            "city": None,
            "state": None,
            "region": None,
            "country": None,
            "latitude": None,
            "longitude": None,
            "all_locations": []
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

###########################
# Initialization Function #
###########################

def initialize_globals():
    """
    Load the shared custom spaCy pipeline once.
    """
    global nlp

    logger.info("Initializing model server...")
    process = psutil.Process(os.getpid())
    logger.info(f"Memory usage before loading data: {process.memory_info().rss / 1024 / 1024:.2f} MB")

    try:
        nlp = load_nlp()
        logger.info("Custom spaCy pipeline loaded.")
    except Exception as exc:
        logger.error("Could not load custom spaCy pipeline: %s", exc)
        nlp = None

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

@app.route('/ready', methods=['GET'])
def readiness_check():
    """Require both the custom model and a readable, nonempty gazetteer."""
    if nlp is None:
        return jsonify({'status': 'unavailable', 'component': 'model'}), 503
    try:
        response = supabase.table("gazetteer").select(
            "geonameid, name, featureCode, stateCode, countryCode, latitude, longitude, alternate_list, population"
        ).limit(1).execute()
        if not response.data:
            return jsonify({'status': 'unavailable', 'component': 'gazetteer', 'reason': 'empty or unreadable'}), 503
    except Exception:
        logger.error("Gazetteer readiness failed; check credentials, SELECT permissions, and required columns.")
        return jsonify({'status': 'unavailable', 'component': 'gazetteer'}), 503
    return jsonify({'status': 'healthy', 'details': {'spaCy': 'loaded', 'gazetteer': 'readable'}})

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

    if nlp is None:
        return jsonify({'error': 'Custom NLP model unavailable; check /health and README.md.'}), 503
    ent_sent = convert_sets_to_lists(extract_ent_sent(text))

    # Attempt location standardization if gazetteer is loaded
    if ent_sent['disasters'] and ent_sent['locations']:
        try:
            loc_series = standardize_row({'locations': ent_sent['locations'], 'text': text})
            # Update ent_sent with the standardization keys
            for key, val in loc_series.items():
                ent_sent[key] = val


            # De-duplicate the 'locations' list if present
            if 'locations' in ent_sent and isinstance(ent_sent['locations'], list):
                ent_sent['locations'] = sorted(set(ent_sent['locations']))
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

    elapsed = time.time() - start_time
    logger.info(f"extract_entities completed in {elapsed:.2f}s")

    return jsonify(ent_sent)

################
# Main Routine #
################

if __name__ == '__main__':
    # Only do the global initialization if we directly run this file
    initialize_globals()

    model_port = int(os.environ.get("MODEL_PORT", "5000"))
    model_threads = int(os.environ.get("MODEL_THREADS", "4"))
    logger.info("Starting model server on port %s with Waitress", model_port)
    try:
        from waitress import serve
        serve(app, host="127.0.0.1", port=model_port, threads=model_threads)
    except ImportError:
        logger.warning("Waitress not installed, falling back to Flask dev server.")
        app.run(host="127.0.0.1", port=model_port, threaded=True)
    except Exception as e:
        logger.critical(f"Server failed to start: {e}")
        sys.exit(1)
