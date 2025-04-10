import os
import sys
import gc
import time
import logging
import psutil
import pickle


import spacy
from flask import Flask, request, jsonify

from gazetteer import load_gazetteer, build_location_dict, lookup_city_state_country, standardize_row
from entity_extraction import extract_ent_sent, clean_text

######################
# Config and Globals #
######################

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Global references to loaded data
nlp = None
gazetteer_df = None
location_dict = None

APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
#print(APP_DIR)
###########################
# Initialization Function #
###########################

def initialize_globals():
    """
    Load the spaCy model and gazetteer data once, if not already loaded.
    """
    global nlp, gazetteer_df, location_dict
    
    if nlp and gazetteer_df is not None and location_dict is not None:
        logger.info("Globals already initialized, skipping reload.")
        return
    
    logger.info("Initializing model server globals...")
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
    
    # 2) Load gazetteer
    try:
        gazetteer_path = os.path.join(APP_DIR, "data", "US.txt")
        if not os.path.exists(gazetteer_path):
            raise FileNotFoundError(f"Gazetteer file not found at {gazetteer_path}")
        logger.info(f"Loading gazetteer from: {gazetteer_path}")
        
        # Actually load + build dictionary
        loaded_gazetteer = load_gazetteer(gazetteer_path)
        built_dict = build_location_dict(loaded_gazetteer)
        
        # Assign to globals
        gazetteer_df = loaded_gazetteer
        location_dict = built_dict

        logger.info(f"Loaded gazetteer: {len(gazetteer_df)} rows, location_dict keys: {len(location_dict)}")
    except Exception as ex:
        logger.error(f"Error loading gazetteer: {ex}")
        gazetteer_df = None
        location_dict = None

    # Force GC again
    gc.collect()
    
    logger.info(f"Memory usage after loading data: {process.memory_info().rss / 1024 / 1024:.2f} MB")

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
@app.route("/gazetteer_pickle", methods=["GET"])
def get_gazetteer_pickle():
    """Return the gazetteer DataFrame in pickle-serialized form."""
    initialize_globals()
    
    global gazetteer_df
    if gazetteer_df is None:
        return "Gazetteer is not available", 500

    # Convert the DataFrame to a pickled bytes object
    pickled_data = pickle.dumps(gazetteer_df)
    return pickled_data, 200, {
        "Content-Type": "application/octet-stream"
    }

@app.route("/location_dict_pickle", methods=["GET"])
def get_location_dict_pickle():
    """Return the location dictionary in pickle-serialized form."""
    initialize_globals()
    
    global location_dict
    if location_dict is None:
        return "Location dictionary is not available", 500

    pickled_data = pickle.dumps(location_dict)
    return pickled_data, 200, {
        "Content-Type": "application/octet-stream"
    }

@app.route('/health', methods=['GET'])
def health_check():
    """
    Health check endpoint: returns status of the model server's critical components.
    """
    status = {
        'spaCy': 'loaded' if nlp else 'missing',
        'gazetteer': 'loaded' if gazetteer_df is not None else 'missing',
        'location_dict': 'loaded' if location_dict is not None else 'missing'
    }
    # If everything is loaded, we consider it 'healthy'
    overall_state = 'healthy' if (nlp and gazetteer_df is not None and location_dict is not None) else 'degraded'
    return jsonify({'status': overall_state, 'details': status})

@app.route('/extract_entities', methods=['POST'])
def extract_entities():
    """
    Main endpoint to process a text for entity extraction and location standardization.
    """
    start_time = time.time()

    data = request.json or {}
    text = data.get('text', '').strip()
    if not text:
        return jsonify({'error': 'No text provided'}), 400

    logger.info(f"extract_entities called, text length={len(text)}")
    
    # Ensure everything is loaded
    initialize_globals()

    # Clean text
    cleaned = clean_text(text)

    # Extract using spaCy-based logic or fallback
    if nlp:
        ent_sent = extract_ent_sent(cleaned)
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
    if gazetteer_df is not None and location_dict is not None:
        try:
            loc_series = standardize_row({'locations': ent_sent['locations']}, gazetteer_df, location_dict)
            # Update ent_sent with the standardization keys
            for key, val in loc_series.items():
                ent_sent[key] = val
            
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
                "all_locations": []
            })
    else:
        # If gazetteer or location_dict is missing, skip
        ent_sent.update({
            "city": None,
            "state": None,
            "region": None,
            "country": None,
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
