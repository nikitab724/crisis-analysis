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

pattern = re.compile(
    r"(?P<hashtag>\#[A-Za-z0-9_]+)"           # e.g. #RockIsland
    r"|(?P<mention>@[A-Za-z0-9_]+)"           # remove entire @-mention
    r"|(?P<url>\w+://\S+)"                    # remove entire url
    r"|(?P<remove>[^\w\s,])"                  # remove any other char that's not word char, whitespace, or comma
)

def split_camel_case(text: str) -> str:
    """
    Insert a space before an uppercase char that follows a lowercase char.
    e.g. 'RockIsland' -> 'Rock Island'
    """
    return re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', text)

def replace_func(match: re.Match) -> str:
    """
    - If hashtag is matched, split its camel case part and add a comma afterward.
    - If mention or url is matched, replace with space.
    - If remove is matched (any disallowed char), replace with a space.
    """
    if match.group('hashtag'):
        # Remove the '#' and split the remainder
        hashtag_text = match.group('hashtag')[1:]  # skip '#'
        splitted = split_camel_case(hashtag_text)
        return splitted + ","  # keep a trailing comma
    
    if match.group('mention') or match.group('url') or match.group('remove'):
        return " "
    
    # fallback
    return match.group(0)

def clean_text(text: str) -> str:
    """
    Cleans the text by:
    - Removing or transforming selected tokens (@mentions, URLs, certain punctuation)
    - Normalizing extra spaces.
    - Preserving commas and splitting camel case only in hashtags.
    """
    cleaned = pattern.sub(replace_func, text)
    # Normalize spaces
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
    #print("entity extraction text: ", text)
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
            location = ent.text.strip("# ")
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
