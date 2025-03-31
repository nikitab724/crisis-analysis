#!/usr/bin/env python3

import requests
import pandas as pd
import os
import json
import time
from entry import filter_posts, extract_entities, reset_csv_files, calculate_crisis_counts
from entry import main as entry_main

def send_test_tweet(text):
    """Send a test tweet to the scraper server and return the post data."""
    try:
        response = requests.post(
            'http://127.0.0.1:5001/test_tweet',
            json={'text': text},
            timeout=10
        )
        response.raise_for_status()
        result = response.json()
        return result.get('posts', [])
    except Exception as e:
        print(f"Error sending test tweet: {e}")
        return []

def process_test_tweet(text):
    """Process a single test tweet through the pipeline."""
    # Get the paths to output files
    base_dir = os.path.dirname(os.path.abspath(__file__))
    filtered_posts_file = os.path.join(base_dir, "filtered_posts.csv")
    crisis_counts_file = os.path.join(base_dir, "crisis_counts.csv")
    
    # Make backup of existing files if they exist
    backup_files = {}
    for file_path in [filtered_posts_file, crisis_counts_file]:
        if os.path.exists(file_path):
            backup_path = file_path + ".backup"
            print(f"Backing up {file_path} to {backup_path}")
            try:
                with open(file_path, 'r') as src, open(backup_path, 'w') as dst:
                    dst.write(src.read())
                backup_files[file_path] = backup_path
            except Exception as e:
                print(f"Error backing up {file_path}: {e}")
    
    # Send the test tweet
    print(f"Sending test tweet: '{text}'")
    posts = send_test_tweet(text)
    
    if not posts:
        print("Error: No posts returned from test tweet.")
        return
    
    print(f"Test tweet sent successfully!")
    
    # Now call main() with only our test post data
    # The hack here is to temporarily override the scrape_posts function
    from entry import scrape_posts as original_scrape_posts
    
    # Define a replacement function that only returns our test post
    def mock_scrape_posts(post_limit=None):
        print("Using mock scraper with test tweet only")
        return posts
    
    # Monkey patch the original function
    import entry
    entry.scrape_posts = mock_scrape_posts
    
    try:
        # Call main with our test files - note: in current entry.py it uses hardcoded filenames
        print("Processing test tweet through the full pipeline...")
        # Check if main accepts post_limit parameter
        import inspect
        sig = inspect.signature(entry_main)
        if 'post_limit' in sig.parameters:
            entry_main(post_limit=1)
        else:
            # Fall back to the default parameters
            entry_main()
        
        # Check results
        if os.path.exists(filtered_posts_file):
            try:
                df = pd.read_csv(filtered_posts_file)
                print(f"\nResults: {len(df)} rows in filtered posts file")
                
                if len(df) > 1:
                    print("\nWARNING: Multiple rows were generated from a single test tweet!")
                    
                    # Check if rows are identical
                    if df.duplicated().any():
                        print("FOUND EXACT DUPLICATES in the output!")
                    
                    # Show differences between rows
                    print("\nDifferences between rows:")
                    first_row = df.iloc[0]
                    for i in range(1, len(df)):
                        diff_cols = []
                        for col in df.columns:
                            if str(first_row[col]) != str(df.iloc[i][col]):
                                diff_cols.append(col)
                        
                        if diff_cols:
                            print(f"Row {i+1} differs from row 1 in columns: {', '.join(diff_cols)}")
                            for col in diff_cols:
                                print(f"  {col}: '{first_row[col]}' vs '{df.iloc[i][col]}'")
                        else:
                            print(f"Row {i+1} is IDENTICAL to row 1")
                
                print("\nProcessed tweet data:")
                print(df)
            except Exception as e:
                print(f"Error reading results: {e}")
        else:
            print("No results file was created. Check for errors in the processing.")
    
    finally:
        # Restore the original function
        entry.scrape_posts = original_scrape_posts
        
        # Restore backup files if they exist
        for original_path, backup_path in backup_files.items():
            print(f"Restoring {original_path} from {backup_path}")
            try:
                with open(backup_path, 'r') as src, open(original_path, 'w') as dst:
                    dst.write(src.read())
            except Exception as e:
                print(f"Error restoring {original_path}: {e}")

def main():
    print("Test Tweet Processor")
    print("===================")
    
    test_text = input("Enter test tweet text (or press Enter for default test): ")
    if not test_text:
        test_text = "Test tweet about a flood in Canada. Canada is experiencing severe flooding."
        print(f"Using default test: '{test_text}'")
    
    process_test_tweet(test_text)

if __name__ == "__main__":
    main() 