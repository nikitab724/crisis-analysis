import pandas as pd
from preprocess_text import preprocess_text
from location_extraction import extract_location, get_lat_lon
import requests
import os

def predict_crisis(text):
    response = requests.post('http://127.0.0.1:5000/predict_crisis', json={'text': text})
    return response.json().get('crisis_prediction')

def predict_sentiment(text):
    response = requests.post('http://127.0.0.1:5000/predict_sentiment', json={'text': text})
    return response.json().get('sentiment_prediction')

def predict_crisis_type(text):
    response = requests.post('http://127.0.0.1:5000/predict_crisis_type', json={'text': text})
    return response.json().get('crisis_type_prediction')

def scrape_posts(post_limit=50):
    response = requests.post('http://127.0.0.1:5001/scrape_posts', json={'post_limit': post_limit})
    return response.json().get('posts')

def filter_posts(df: pd.DataFrame):
    df = df[df['text'].notnull()]  # Filter out empty posts
    df = df.drop_duplicates(subset=['text'])  # Remove duplicate posts

    df['text'] = df['text'].astype(str)
    df['preprocessed_text'] = df['text'].apply(preprocess_text) # Preprocess post text

    df['prediction'] = df['preprocessed_text'].apply(predict_crisis)
    df = df[df['prediction'] == 'Crisis']  # Filter out non-crisis posts

    df['location'] = df['preprocessed_text'].apply(extract_location)
    df = df[df['location'].notnull()]  # Filter out posts without location

    df['sentiment'] = df['preprocessed_text'].apply(predict_sentiment)
    df = df[df['sentiment'] != 0]  # Filter out neutral sentiment posts

    df['disaster_type'] = df['preprocessed_text'].apply(predict_crisis_type)

    return df

def calculate_crisis_counts(df: pd.DataFrame):
    exploded = df.explode('disaster_type').explode('location')
    counts = (exploded.groupby(['disaster_type', 'location'])
        .agg(
            count=('disaster_type', 'size'),
            avg_sentiment=('sentiment', 'mean')
        )
        .reset_index()
        .sort_values('count', ascending=False)
        .round({'avg_sentiment': 2})
    )
    counts_mean = counts['count'].mean()
    counts_std = counts['count'].std()
    counts['severity'] = (counts['count'] - counts_mean) / counts_std
    counts['latitude'], counts['longitude'] = zip(*counts['location'].apply(get_lat_lon))
    counts = counts.dropna(subset=['latitude', 'longitude'])
    return counts

def main(post_limit=50):
    posts = scrape_posts(post_limit)

    # Load collected posts
    try:
        df = pd.DataFrame(posts)
    except Exception as e:
        print(f"Error: {e}")
        return

    print(f'Scraped {len(df)} posts')
    filtered_df = filter_posts(df)
    print(f'Processed and identified {len(filtered_df)} crisis posts')

    if filtered_df.empty:
        return # Return if no crisis posts found
    
    # Save filtered posts
    filtered_posts_output_file = 'filtered_posts.csv'
    if os.path.exists(filtered_posts_output_file):
        existing_df = pd.read_csv(filtered_posts_output_file)
        combined_df = pd.concat([existing_df, filtered_df])
        combined_df.to_csv(filtered_posts_output_file, index=False)
    else:
        filtered_df.to_csv('filtered_posts.csv', index=False) 

    counts = calculate_crisis_counts(filtered_df)

    # Save crisis counts
    crisis_counts_output_file = 'crisis_counts.csv'
    if os.path.exists(crisis_counts_output_file):
        existing_df = pd.read_csv(crisis_counts_output_file)
        combined_df = pd.concat([existing_df, counts])
        combined_df = combined_df.groupby(['disaster_type', 'location']).agg(
            count=('count', 'sum'),
            avg_sentiment=('avg_sentiment', 'mean'),
            severity=('severity', 'mean'),
            latitude=('latitude', 'first'),
            longitude=('longitude', 'first')
        ).reset_index()
        combined_df.to_csv(crisis_counts_output_file, index=False)
    else:
        counts.to_csv(crisis_counts_output_file, index=False)

if __name__ == '__main__':
    post_limit = 100
    while True:
        try:
            main(post_limit)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")





