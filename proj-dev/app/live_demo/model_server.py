from flask import Flask, request, jsonify
from gazetteer import load_gazetteer, build_location_dict, lookup_city_state_country, standardize_row
from entity_extraction import extract_ent_sent, clean_text
import spacy
import os

# Get the absolute path to the project root directory
APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Initialize spaCy and gazetteer with correct paths
nlp = spacy.load(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "disaster_ner"))
gazetteer_df = load_gazetteer(os.path.join(APP_DIR, "data", "US.txt"))
location_dict = build_location_dict(gazetteer_df)

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

@app.route('/extract_entities', methods=['POST'])
def extract_entities():
    data = request.json
    text = data.get('text', '')
    cleaned_text = clean_text(text)
    ent_sent = extract_ent_sent(cleaned_text)
    
    # Convert any sets to lists for JSON serialization
    ent_sent = convert_sets_to_lists(ent_sent)
    
    # Add location standardization
    ent_sent.update(standardize_row({'locations': ent_sent['locations']}, gazetteer_df, location_dict))
    
    return jsonify(ent_sent)

if __name__ == '__main__':
    app.run()