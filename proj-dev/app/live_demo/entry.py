import pandas as pd
from entity_extraction import clean_text
import requests
import os
import json
import numpy as np
import time

def extract_entities(text):
    """
    A direct call to the model_server's /extract_entities endpoint.
    Raises an exception if there's any HTTP/network error or if
    the server responds with 4xx/5xx status.
    """
    response = requests.post(
        'http://127.0.0.1:5000/extract_entities',
        json={'text': text},
        timeout=10
    )
    response.raise_for_status()  # Will raise a requests.HTTPError if status not 200
    return response.json()

def default_entity_data():
    """Return default entity data when extraction fails"""
    return {
        'disasters': [],
        'locations': [],
        'sentiment': 'Neutral',
        'polarity': 0.0,
        'city': None,
        'state': None,
        'region': None,
        'country': None,
        'all_locations': None
    }

def get_scraped_posts(limit=50):
    url = "http://127.0.0.1:5001/scrape"
    params = {"limit": limit}
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        return data.get("posts", [])
    except requests.exceptions.RequestException as e:
        return {"Request Error": str(e)}
    except Exception as e:
        return {"Error": str(e)}

def filter_posts(df: pd.DataFrame):
    # Create a copy of the DataFrame to avoid SettingWithCopyWarning
    df = df.copy()
    
    # Remove duplicate posts based on text content
    df = df.drop_duplicates(subset=['text'])

    # Drop rows where text is empty (has zero length)
    df = df[df['text'].str.len() > 0]
    
    # Define required columns for consistency
    required_columns = [
        'author', 'created_at', 'post_id', 'text', 'uri',
        'disasters', 'sentiment', 'polarity', 
        'city', 'state', 'region', 'country', 'location'
    ]
    
    # Process each row individually to avoid entity_data errors
    processed_rows = []
    
    for idx, row in df.iterrows():
        try:
            # Extract entities with error handling
            entity_result = extract_entities(row['text'])

            if not entity_result or not isinstance(entity_result, dict):
                # If there's no valid entity data, skip
                continue

            disasters = entity_result.get('disasters', [])
            locations = entity_result.get('locations', [])
            sentiment = entity_result.get('sentiment', 'Neutral')
            polarity = entity_result.get('polarity', 0.0)

            # Then check if you want to skip if empty
            if not disasters or not locations:
                continue
            
            #print("disasters: ", disasters)
            
            #top level row
            top_row = {
                        'author': row.get('author', ''),
                        'created_at': row.get('created_at', ''),
                        'post_id': row.get('post_id', ''),
                        'text': row.get('text', ''),
                        'uri': row.get('uri', ''),
                        'disasters': disasters,
                        'sentiment': sentiment,
                        'polarity': polarity,
                        'city': entity_result.get('city', ''),
                        'state': entity_result.get('state', ''),
                        'region': entity_result.get('region', ''),
                        'country': entity_result.get('country', 'US'),
                        'location': entity_result.get('city', '')
                    }
            processed_rows.append(top_row)
            #print("top row added: ", processed_rows)
            # Get standardized location info
            all_locations = entity_result.get('all_locations', [])
            
            #print(entity_result)
            # If we have location details, create rows for each location
            if all_locations and isinstance(all_locations, list) and len(all_locations) > 0:
                for loc_info in all_locations:
                    if not isinstance(loc_info, dict) or not loc_info.get('state'):
                        continue
                        
                    # Create a new row with required fields
                    new_row = {
                        'author': row.get('author', ''),
                        'created_at': row.get('created_at', ''),
                        'post_id': row.get('post_id', ''),
                        'text': row.get('text', ''),
                        'uri': row.get('uri', ''),
                        'disasters': disasters,
                        'sentiment': sentiment,
                        'polarity': polarity,
                        'city': loc_info.get('city', ''),
                        'state': loc_info.get('state', ''),
                        'region': loc_info.get('region', ''),
                        'country': loc_info.get('country', 'US'),
                        'location': loc_info.get('location', '')
                    }
                    
                    processed_rows.append(new_row)
            
            #print(processed_rows)
        except Exception as e:
            print(f"Error processing row {idx}: {e}")
            continue

    result_df = pd.DataFrame(processed_rows)
                
    return result_df

def calculate_crisis_counts(df, existing_counts_file=None):
    # Drop rows without state information
    df = df.dropna(subset=["state"])
    
    if df.empty:
        # If no new data, return existing counts or empty DataFrame
        if existing_counts_file and os.path.exists(existing_counts_file):
            try:
                return pd.read_csv(existing_counts_file)
            except:
                return pd.DataFrame()
        else:
            return pd.DataFrame()
    
    # Make a copy to avoid modifying the original dataframe
    df_copy = df.copy()
    
    # Ensure disasters is a string if it's a list
    if 'disasters' in df_copy.columns:
        # Convert list to string only for grouping
        df_copy['disaster_str'] = df_copy['disasters'].apply(
            lambda x: x[0] if isinstance(x, list) and len(x) > 0 else 
                    (x if isinstance(x, str) else 'Unknown')
        )
    
    # Process new data - use disaster_str for grouping
    exploded_new = df_copy.copy()
    
    # Group by country, state, and disaster type
    new_counts = (exploded_new.groupby(["country", "state", "disaster_str"])
        .agg(
            count=('disaster_str', 'size'),
            avg_sentiment=('polarity', 'mean'),
            cities=('city', lambda x: list(set([c for c in x if pd.notnull(c)])))
        )
        .reset_index()
        .rename(columns={'disaster_str': 'disasters'})
        .round({'avg_sentiment': 2})
    )
    
    # Handle existing counts file if it exists
    if existing_counts_file and os.path.exists(existing_counts_file) and os.path.getsize(existing_counts_file) > 0:
        try:
            existing_counts = pd.read_csv(existing_counts_file)
            
            if not existing_counts.empty:
                # Convert string representation of cities lists back to actual lists
                try:
                    existing_counts['cities'] = existing_counts['cities'].apply(
                        lambda x: eval(x) if isinstance(x, str) else (x if isinstance(x, list) else [])
                    )
                except:
                    # If there's an error with the cities column, just use an empty list
                    existing_counts['cities'] = [[]] * len(existing_counts)
                
                # Combine with new counts
                combined = pd.concat([existing_counts, new_counts])
                
                # Re-aggregate by country, state, and disaster type
                counts = combined.groupby(["country", "state", "disasters"]).agg({
                    'count': 'sum',
                    'avg_sentiment': 'mean',
                    'cities': lambda x: list(set([item for sublist in x for item in sublist if item]))
                }).reset_index()
                
                # Sort and round
                counts = counts.sort_values("count", ascending=False).round({'avg_sentiment': 2})
            else:
                counts = new_counts
        except Exception as e:
            print(f"Error processing existing counts: {e}")
            counts = new_counts
    else:
        counts = new_counts
    
    # Calculate severity based on count
    if not counts.empty:
        counts_mean = counts['count'].mean()
        counts_std = counts['count'].std() or 1  # Avoid division by zero
        counts['severity'] = (counts['count'] - counts_mean) / counts_std
    
    return counts

def reset_csv_files():
    """Check and reset CSV files if corrupt"""
    
    # Define expected columns for each file
    expected_columns = {
        'filtered_posts.csv': [
            'author', 'created_at', 'post_id', 'text', 'uri', 'preprocessed_text',
            'disasters', 'locations', 'sentiment', 'polarity', 
            'city', 'state', 'region', 'country', 'location'
        ],
        'crisis_counts.csv': [
            'country', 'state', 'disasters', 'count', 'avg_sentiment', 'cities', 'severity'
        ]
    }
    
    for file_path, columns in expected_columns.items():
        if os.path.exists(file_path):
            try:
                # Try to verify the file is valid
                with open(file_path, 'r') as f:
                    header = f.readline()
                    if not header or ',' not in header:
                        print(f"Corrupted or empty file detected: {file_path}, resetting")
                        os.remove(file_path)
                        continue
                
                # Verify it's a valid CSV by trying to read it
                df = pd.read_csv(file_path)
                
                if df.empty:
                    print(f"Empty CSV file detected: {file_path}, resetting")
                    os.remove(file_path)
                    continue
                
                # Check if columns match expected columns
                missing_columns = [col for col in columns if col not in df.columns]
                if missing_columns:
                    print(f"Missing columns in {file_path}: {missing_columns}")
                    
                    # Try to fix by adding missing columns with default values
                    for col in missing_columns:
                        if col in ['disasters', 'locations', 'cities']:
                            df[col] = [[]] * len(df)
                        elif col in ['polarity', 'count', 'avg_sentiment', 'severity']:
                            df[col] = 0.0
                        elif col in ['sentiment']:
                            df[col] = 'Neutral'
                        else:
                            df[col] = ''
                    
                    # Save fixed file
                    df.to_csv(file_path, index=False)
                    print(f"Fixed column structure in {file_path}")
                
            except Exception as e:
                print(f"Error verifying {file_path}, resetting: {e}")
                os.remove(file_path)
                print(f"Removed corrupted file: {file_path}")

def main(post_limit=50):
    reset_csv_files()
    posts = get_scraped_posts(post_limit)

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
        
        # For appending, handle existing file properly
        if os.path.exists(filtered_posts_output_file) and os.path.getsize(filtered_posts_output_file) > 0:
            try:
                # Try to read existing file
                existing_df = pd.read_csv(filtered_posts_output_file)
                
                # Ensure column consistency
                for col in filtered_df.columns:
                    if col not in existing_df.columns:
                        if col in ['disasters', 'locations', 'cities']:
                            existing_df[col] = [[]] * len(existing_df)
                        elif col in ['polarity']:
                            existing_df[col] = 0.0
                        elif col in ['sentiment']:
                            existing_df[col] = 'Neutral'
                        else:
                            existing_df[col] = ''
                
                for col in existing_df.columns:
                    if col not in filtered_df.columns:
                        if col in ['disasters', 'locations', 'cities']:
                            filtered_df[col] = [[]] * len(filtered_df)
                        elif col in ['polarity']:
                            filtered_df[col] = 0.0
                        elif col in ['sentiment']:
                            filtered_df[col] = 'Neutral'
                        else:
                            filtered_df[col] = ''
                
                # Combine and save
                combined_df = pd.concat([existing_df, filtered_df])
                combined_df.to_csv(filtered_posts_output_file, index=False)
                print(f"Successfully appended {len(filtered_df)} records to {filtered_posts_output_file}")
                
            except Exception as e:
                print(f"Error reading existing filtered posts, creating new file: {e}")
                filtered_df.to_csv(filtered_posts_output_file, index=False)
        else:
            # Create new file
            filtered_df.to_csv(filtered_posts_output_file, index=False)
            print(f"Created new file {filtered_posts_output_file} with {len(filtered_df)} records")
    except Exception as e:
        print(f"Error saving filtered posts: {e}")
    
    try:
        # Calculate crisis counts
        crisis_counts_output_file = 'crisis_counts.csv'
        counts = calculate_crisis_counts(filtered_df, crisis_counts_output_file)
        
        if counts is not None and not counts.empty:
            counts.to_csv(crisis_counts_output_file, index=False)
            print(f"Successfully updated crisis counts with {len(counts)} records")
        else:
            print("No crisis counts to save")
    except Exception as e:
        print(f"Error calculating or saving crisis counts: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    post_limit = 100
    while True:
        try:
            main(post_limit)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")