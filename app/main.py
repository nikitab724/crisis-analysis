import pandas as pd
import spacy
from gazetteer import load_gazetteer, build_location_dict, lookup_city_state_country
from entity_extraction import extract_ent_sent, clean_text

nlp = spacy.load("disaster_ner")

gazetteer_df = load_gazetteer("../data/US.txt")
location_dict = build_location_dict(gazetteer_df)

def process_tweet(text):
    """
    Process a single tweet text and return a DataFrame row with:
      - tweet_text
      - disasters (set/list)
      - extracted_locations (list)
      - sentiment (string, e.g., "Positive", "Neutral", "Negative")
      - polarity (float)
      - city, state, region, country (from gazetteer lookup of the first extracted location)
    """

    cleaned_text = clean_text(text)
    
    # Extract entities and sentiment.
    ent_sent = extract_ent_sent(cleaned_text)
    # ent_sent returns a dict with keys: "disasters", "locations", "sentiment", "polarity"

    # Perform a location lookup on the first extracted location (if available)
    if ent_sent["locations"]:
        lookup_result = lookup_city_state_country(ent_sent["locations"][0], gazetteer_df, location_dict)
    else:
        lookup_result = {"city": None, "state": None, "region": None, "country": None}

    # Combine all the information into a result dictionary.
    result = {
        "tweet_text": text,
        "disasters": list(ent_sent["disasters"]),
        "extracted_locations": ent_sent["locations"],
        "sentiment": ent_sent["sentiment"],
        "polarity": ent_sent["polarity"],
        "city": lookup_result.get("city"),
        "state": lookup_result.get("state"),
        "region": lookup_result.get("region"),
        "country": lookup_result.get("country")
    }
    
    # Return as a one-row DataFrame.
    return pd.DataFrame([result])

def process_tweets(texts):
    """
    Process a list of tweet texts and return a DataFrame with one row per tweet.
    """
    dfs = [process_tweet(text) for text in texts]
    return pd.concat(dfs, ignore_index=True)

if __name__ == "__main__":
    # Example usage:
    sample_text = "RT @Gizmodo: Wildfires raging through Salinas! Stay safe!"
    result_df = process_tweet(sample_text)
    print(result_df)