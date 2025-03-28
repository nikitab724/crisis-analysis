from flask import Flask, request, jsonify
from gazetteer import load_gazetteer, build_location_dict, lookup_city_state_country, standardize_row
from entity_extraction import extract_ent_sent, clean_text
import spacy
import os
import pandas as pd

# Get the absolute path to the app directory
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Initialize spaCy and gazetteer with correct paths
nlp = spacy.load(os.path.join(APP_DIR, "disaster_ner"))
gazetteer_df = load_gazetteer(os.path.join(APP_DIR, "data", "US.txt"))
location_dict = build_location_dict(gazetteer_df)

app = Flask(__name__)

@app.route('/extract_entities', methods=['POST'])
def extract_entities():
    data = request.json
    text = data.get('text', '')
    cleaned_text = clean_text(text)
    ent_sent = extract_ent_sent(cleaned_text)
    
    # Add location standardization
    location_info = standardize_row({'locations': ent_sent['locations']})
    ent_sent.update(location_info)
    
    return jsonify(ent_sent)

if __name__ == '__main__':
    app.run()