from flask import Flask, request, jsonify
from gazetteer import load_gazetteer, build_location_dict, lookup_city_state_country, standardize_row
from entity_extraction import extract_ent_sent, clean_text
import spacy
import os
import gc
import time
import logging
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('model_server.log')
    ]
)
logger = logging.getLogger('model_server')

# Get the absolute path to the project root directory
APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Initialize with reduced memory usage
try:
    # Log memory usage before loading models
    logger.info("Starting model server initialization")
    import psutil
    process = psutil.Process(os.getpid())
    logger.info(f"Memory usage before loading models: {process.memory_info().rss / 1024 / 1024:.2f} MB")
    
    # Load spaCy model with optimizations
    logger.info("Loading spaCy model")
    nlp = None
    try:
        # Try to load the model with optimized settings
        spacy_model_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "disaster_ner")
        nlp = spacy.load(spacy_model_path, disable=['ner_trf'])  # Disable transformer components if any
    except Exception as e:
        logger.error(f"Error loading spaCy model: {e}")
        # Try with simpler model as fallback
        try:
            nlp = spacy.load("en_core_web_sm")
            logger.warning("Using fallback 'en_core_web_sm' model")
        except:
            logger.critical("Could not load any spaCy model. Entity extraction will be limited.")
    
    # Force garbage collection
    gc.collect()
    
    # Load gazetteer with optimizations
    logger.info("Loading gazetteer")
    gazetteer_df = None
    location_dict = None
    try:
        gazetteer_path = os.path.join(APP_DIR, "data", "US.txt")
        logger.info(f"Gazetteer path: {gazetteer_path}")
        
        # Check if file exists
        if not os.path.exists(gazetteer_path):
            logger.error(f"Gazetteer file not found: {gazetteer_path}")
            raise FileNotFoundError(f"Gazetteer file not found: {gazetteer_path}")
        
        # Load with optimized settings - only keep necessary columns
        gazetteer_df = load_gazetteer(gazetteer_path)
        
        # Build location dictionary
        location_dict = build_location_dict(gazetteer_df)
        
        logger.info(f"Loaded gazetteer with {len(gazetteer_df)} locations and {len(location_dict)} dictionary entries")
    except Exception as e:
        logger.error(f"Error loading gazetteer: {e}")
    
    # Force garbage collection again
    gc.collect()
    
    if process:
        logger.info(f"Memory usage after loading models: {process.memory_info().rss / 1024 / 1024:.2f} MB")
    
except Exception as e:
    logger.critical(f"Fatal error during initialization: {e}")
    sys.exit(1)

app = Flask(__name__)

def convert_sets_to_lists(obj):
    """Convert any sets in the object to lists for JSON serialization."""
    if isinstance(obj, set):
        return list(obj)
    elif isinstance(obj, dict):
        return {k: convert_sets_to_lists(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_sets_to_lists(item) for item in obj]
    else:
        return obj

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    status = {
        'status': 'healthy' if nlp and gazetteer_df is not None and location_dict is not None else 'degraded',
        'spacy_model': 'loaded' if nlp else 'missing',
        'gazetteer': 'loaded' if gazetteer_df is not None else 'missing',
        'location_dict': 'loaded' if location_dict is not None else 'missing'
    }
    return jsonify(status)

@app.route('/extract_entities', methods=['POST'])
def extract_entities():
    start_time = time.time()
    
    try:
        data = request.json
        text = data.get('text', '')
        
        if not text:
            return jsonify({'error': 'No text provided'}), 400
        
        logger.info(f"Processing text of length {len(text)}")
        
        # Clean the text
        cleaned_text = clean_text(text)
        
        # Extract entities and sentiment
        if nlp:
            ent_sent = extract_ent_sent(cleaned_text)
            # Convert any sets to lists for JSON serialization
            ent_sent = convert_sets_to_lists(ent_sent)
        else:
            # Fallback if NLP model not available
            logger.warning("Using fallback entity extraction (no NLP model)")
            ent_sent = {"disasters": [], "locations": [], "sentiment": "Neutral", "polarity": 0.0}
        
        # Add location standardization if gazetteer is available
        if gazetteer_df is not None and location_dict is not None:
            try:
                location_series = standardize_row({'locations': ent_sent['locations']}, gazetteer_df, location_dict)
                
                # Update with location information
                for key, value in location_series.items():
                    ent_sent[key] = value
                    
                # Ensure locations list has no duplicates
                if 'locations' in ent_sent and isinstance(ent_sent['locations'], list):
                    ent_sent['locations'] = list(set(ent_sent['locations']))
            except Exception as e:
                logger.error(f"Error in location standardization: {e}")
                # Add empty location data
                ent_sent.update({
                    "city": None,
                    "state": None,
                    "region": None,
                    "country": None,
                    "all_locations": []
                })
        else:
            logger.warning("Skipping location standardization (no gazetteer)")
            # Add empty location data
            ent_sent.update({
                "city": None,
                "state": None,
                "region": None,
                "country": None,
                "all_locations": []
            })
        
        # Log processing time
        elapsed = time.time() - start_time
        logger.info(f"Processed in {elapsed:.2f} seconds")
        
        return jsonify(ent_sent)
        
    except Exception as e:
        logger.error(f"Error in extract_entities: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({
            'error': str(e),
            'disasters': [],
            'locations': [],
            'sentiment': 'Neutral',
            'polarity': 0.0,
            'city': None,
            'state': None, 
            'region': None,
            'country': None,
            'all_locations': []
        }), 500

if __name__ == '__main__':
    try:
        # Use production server
        import waitress
        logger.info("Starting model server with waitress on port 5000")
        from waitress import serve
        serve(app, port=5000, threads=4)
    except ImportError:
        # Fall back to Flask's development server
        logger.info("Waitress not available, using Flask development server on port 5000")
        app.run(port=5000, threaded=True)
    except Exception as e:
        logger.critical(f"Error starting server: {e}")
        sys.exit(1)