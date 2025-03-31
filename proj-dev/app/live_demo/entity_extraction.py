import pandas as pd
import spacy
import glob
import os
import re
from collections import Counter 
from collections import defaultdict
import numpy as np
from spacy.lang.en import English
from spacy.lookups import Lookups
from spacy.pipeline import EntityRuler
from spacytextblob.spacytextblob import SpacyTextBlob
import json
import sklearn
import matplotlib.pyplot as plt

# data preprocessing

pattern = re.compile(r'''
    (?P<hashtag>\#)(?P<hashword>[A-Za-z0-9_]+)    # e.g. #RockIsland => keep 'RockIsland'
  | (?P<mention>@[A-Za-z0-9_]+)                   # remove entire @-mention
  | (?P<url>\w+://\S+)                            # remove entire url
  | (?P<non_alnum>[^0-9A-Za-z \t])                # remove any other non-alphanumeric
''', re.VERBOSE)

def replace_func(match: re.Match) -> str:
    """
    If we matched a hashtag (#...), keep only the word part.
    For mention, URL, or non-alphanumeric, replace with a space.
    """
    # If we matched a hashtag
    if match.group('hashtag'):
        # Keep the 'hashword' group (the text after '#')
        return match.group('hashword') + ","
    
    # If we matched a mention, URL, or non-alphanumeric, replace entire match with space
    return ' '

def split_camel_case(text: str) -> str:
    """
    Insert a space before an uppercase char that follows a lowercase char.
    e.g. 'RockIsland' -> 'Rock Island'
    If you also want to handle multiple capitals, refine the pattern accordingly.
    """
    # We only add a space between a lowercase letter and an uppercase letter
    # Example: "NorthSouth" -> "North South"
    # If you want "NASAMission" -> "NASA Mission", you'd need a bigger pattern.
    return re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', text)

def clean_text(text: str) -> str:
    """
    Replace unwanted parts of 'text' using the pattern above.
    Then split and rejoin to normalize spaces.
    """
    # Use the replacement function
    cleaned = pattern.sub(replace_func, text)
    cleaned = split_camel_case(cleaned)
    # Normalize extra spaces
    return ' '.join(cleaned.split())

nlp = spacy.load("../disaster_ner")

def test_model(text):
    doc = nlp(text)
    for ent in doc.ents:
        print(f"Entity lemma: {ent.lemma_.lower()} | Ent text: {ent.text} | Label: {ent.label_} | Canonical label: {ent.ent_id_}")
    print(f"Polarity: {doc._.blob.polarity}, Subjectivity: {doc._.blob.subjectivity}")
#print(df1.loc[0, "tweet_text"])

#extract entities and sentiment from tweet text

headers = ["Negative", "Neutral", "Positive"]
def extract_ent_sent(text):
    #print(text)
    doc = nlp(clean_text(text))
    disasters = set()  # Use set to deduplicate identical disasters
    locations = set()  # Use set to deduplicate identical locations
    sentiment = headers[1]
    score = doc._.blob.polarity
    
    for ent in doc.ents:
        if ent.label_ == "DISASTER":
            disaster_id = ent.ent_id_ if ent.ent_id_ else ent.text
            disasters.add(disaster_id)  # Use add() for set
        elif ent.label_ in ["GPE", "LOC", "FAC"]:
            location = ent.text.strip("# ").lower()
            if location.endswith("'s"):
                location = location[:-2]
            elif location.endswith("'s"):
                location = location[:-2]
            locations.add(location)  # Use add() for set
    
    #print("locations in ent sent: ", locations)

    if score >= 0.1:
        sentiment = headers[2]
    elif score < 0:
        sentiment = headers[0]
    else:
        sentiment = headers[1]

    return {"disasters": list(disasters), "locations": list(locations), "sentiment": sentiment, "polarity": score}
