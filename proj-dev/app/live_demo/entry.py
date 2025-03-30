import pandas as pd
from entity_extraction import clean_text
import requests
import os
import json

def extract_entities(text):
    try:
        response = requests.post('http://127.0.0.1:5000/extract_entities', json={'text': text})
        response.raise_for_status()  # Raise for HTTP errors
        return response.json()
    except requests.exceptions.HTTPError as e:
        print(f"HTTP error in extract_entities: {e}")
        # Return empty values as fallback
        return {
            'disasters': [],
            'locations': [],
            'sentiment': 'Neutral',
            'polarity': 0.0,
            'city': None, 
            'state': None,
            'region': None,
            'country': None
        }
    except requests.exceptions.RequestException as e:
        print(f"Request error in extract_entities: {e}")
        # Return empty values as fallback
        return {
            'disasters': [],
            'locations': [],
            'sentiment': 'Neutral',
            'polarity': 0.0,
            'city': None, 
            'state': None,
            'region': None,
            'country': None
        }
    except json.JSONDecodeError as e:
        print(f"JSON decode error in extract_entities: {e}")
        # Return empty values as fallback
        return {
            'disasters': [],
            'locations': [],
            'sentiment': 'Neutral',
            'polarity': 0.0,
            'city': None, 
            'state': None,
            'region': None,
            'country': None
        }
    except Exception as e:
        print(f"Unexpected error in extract_entities: {e}")
        # Return empty values as fallback
        return {
            'disasters': [],
            'locations': [],
            'sentiment': 'Neutral',
            'polarity': 0.0,
            'city': None, 
            'state': None,
            'region': None,
            'country': None
        }

def scrape_posts(post_limit=50):
    try:
        response = requests.post('http://127.0.0.1:5001/scrape_posts', json={'post_limit': post_limit})
        response.raise_for_status()  # Raise for HTTP errors
        data = response.json()
        posts = data.get('posts', [])
        if not posts:
            print("Warning: Scraper returned no posts")
        return posts
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to scraper server: {e}")
        return []
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from scraper: {e}")
        return []
    except Exception as e:
        print(f"Unexpected error in scrape_posts: {e}")
        return []

def filter_posts(df: pd.DataFrame):
    df = df[df['text'].notnull()]  # Filter out empty posts
    df = df.drop_duplicates(subset=['text'])  # Remove duplicate posts

    df['text'] = df['text'].astype(str)
    df['preprocessed_text'] = df['text'].apply(clean_text) # Use clean_text from entity_extraction

    # Extract entities, sentiment, and location info using pandas Series approach
    df.loc[:, ["disasters", "locations", "sentiment", "polarity", "city", "state", "region", "country"]] = df["preprocessed_text"].apply(
        lambda x: pd.Series(extract_entities(x))
    )
    
    # Filter out posts without disasters or locations
    df = df[df['disasters'].apply(len) > 0]
    df = df[df['locations'].apply(len) > 0]

    return df

def calculate_crisis_counts(df: pd.DataFrame):
    # Drop rows without state information
    df = df.dropna(subset=["state"])
    
    # Explode disasters and group by country, state, and disaster type
    exploded = df.explode("disasters")
    counts = (exploded.groupby(["country", "state", "disasters"])
        .agg(
            count=('disasters', 'size'),  # Count number of disaster reports
            avg_sentiment=('polarity', 'mean'),
            cities=('city', lambda x: list(set(x.dropna())))
        )
        .reset_index()
        .sort_values("count", ascending=False)
        .round({'avg_sentiment': 2})
    )
    
    # Calculate severity based on count
    counts_mean = counts['count'].mean()
    counts_std = counts['count'].std()
    counts['severity'] = (counts['count'] - counts_mean) / counts_std
    
    return counts

def main(post_limit=50):
    posts = scrape_posts(post_limit)

    if not posts:
        print("No posts to process. Skipping this run.")
        return
    
    # Load collected posts
    try:
        df = pd.DataFrame(posts)
    except Exception as e:
        print(f"Error creating DataFrame: {e}")
        return

    print(f'Scraped {len(df)} posts')
    
    try:
        filtered_df = filter_posts(df)
        print(f'Processed and identified {len(filtered_df)} crisis posts')
    except Exception as e:
        print(f"Error filtering posts: {e}")
        return

    if filtered_df.empty:
        print("No crisis posts found. Skipping this run.")
        return
    
    # Save filtered posts
    try:
        filtered_posts_output_file = 'filtered_posts.csv'
        if os.path.exists(filtered_posts_output_file):
            existing_df = pd.read_csv(filtered_posts_output_file)
            combined_df = pd.concat([existing_df, filtered_df])
            combined_df.to_csv(filtered_posts_output_file, index=False)
        else:
            filtered_df.to_csv('filtered_posts.csv', index=False)
    except Exception as e:
        print(f"Error saving filtered posts: {e}")
    
    try:
        counts = calculate_crisis_counts(filtered_df)
    except Exception as e:
        print(f"Error calculating crisis counts: {e}")
        return

    # Save crisis counts
    try:
        crisis_counts_output_file = 'crisis_counts.csv'
        if os.path.exists(crisis_counts_output_file):
            existing_df = pd.read_csv(crisis_counts_output_file)
            combined_df = pd.concat([existing_df, counts])
            combined_df.to_csv(crisis_counts_output_file, index=False)
        else:
            counts.to_csv(crisis_counts_output_file, index=False)
    except Exception as e:
        print(f"Error saving crisis counts: {e}")

if __name__ == '__main__':
    post_limit = 100
    while True:
        try:
            main(post_limit)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")