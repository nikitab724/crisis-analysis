#!/usr/bin/env python3

import requests
import pandas as pd
import os
import time
import inspect

# Import from your existing pipeline code
from entry import filter_posts, extract_entities, reset_csv_files, calculate_crisis_counts
from entry import main as entry_main

def send_test_tweet(text):
    """
    Send a test 'tweet' (post) to the Flask server's /test_tweet endpoint.
    Must have /test_tweet defined on port 5001. That route should return:
        {
          "posts": [
            {
              "text": "...",
              "created_at": "...",
              "author": "...",
              "uri": "..."
            }
          ]
        }
    If you do NOT have /test_tweet, you can replace this function with a mock
    that returns a local post structure directly (i.e. no requests call).
    """
    try:
        response = requests.post(
            'http://127.0.0.1:5001/test_tweet',
            json={'text': text},
            timeout=10
        )
        response.raise_for_status()
        result = response.json()
        # 'posts' should be a list with exactly one dict
        return result.get('posts', [])
    except Exception as e:
        print(f"Error sending test tweet: {e}")
        return []

def process_test_tweet(text):
    """
    Process a single test tweet through the entire 'entry.py' pipeline:
      1. Backs up existing CSVs (filtered_posts.csv, crisis_counts.csv).
      2. Sends 'text' to /test_tweet => obtains a single post.
      3. Monkey-patches entry.get_scraped_posts (or scrape_posts) so that
         entry_main() only processes that single test post.
      4. Calls entry_main(), then restores the original function and the CSV backups.
    """
    # Paths to output files
    base_dir = os.path.dirname(os.path.abspath(__file__))
    filtered_posts_file = os.path.join(base_dir, "filtered_posts.csv")
    crisis_counts_file = os.path.join(base_dir, "crisis_counts.csv")
    
    # 1) Back up existing CSV files, if they exist
    backup_files = {}
    for file_path in [filtered_posts_file, crisis_counts_file]:
        if os.path.exists(file_path):
            backup_path = file_path + ".backup"
            print(f"Backing up {file_path} -> {backup_path}")
            try:
                with open(file_path, 'r') as src, open(backup_path, 'w') as dst:
                    dst.write(src.read())
                backup_files[file_path] = backup_path
            except Exception as e:
                print(f"Error backing up {file_path}: {e}")
    
    # 2) Send the test tweet to get a single post back
    print(f"Sending test tweet: '{text}'")
    posts = send_test_tweet(text)
    if not posts:
        print("Error: No posts returned. Aborting.")
        return
    
    print(f"Test tweet sent successfully! Received {len(posts)} post(s).")

    # 3) Monkey-patch the scraping function so 'entry_main()' processes only that single post
    import entry
    original_scrape_posts = entry.scrape_posts  # or entry.get_scraped_posts, whichever your 'entry.py' calls
    
    def mock_scrape_posts(limit=None):
        """
        Returns only the single test post from /test_tweet
        (ignoring real scraping).
        """
        print("Using mock scraper that returns the single test tweet only...")
        return posts
    
    entry.scrape_posts = mock_scrape_posts

    try:
        # 4) Call entry_main() to run the pipeline
        print("Processing test tweet through entry_main() pipeline...")
        sig = inspect.signature(entry_main)
        if 'post_limit' in sig.parameters:
            entry_main(post_limit=1)
        else:
            entry_main()

        # Check the results in filtered_posts.csv
        if os.path.exists(filtered_posts_file):
            try:
                df = pd.read_csv(filtered_posts_file)
                print(f"\nfiltered_posts.csv now has {len(df)} rows.")
                if not df.empty:
                    print("Sample rows:")
                    print(df.head(5).to_string(index=False))
                    
                    # If multiple rows were generated, let's see how they differ
                    if len(df) > 1:
                        print("\nWARNING: More than one row was generated from a single test tweet!")
                else:
                    print("No rows found in filtered_posts after processing.")
            except Exception as e:
                print(f"Error reading {filtered_posts_file}: {e}")
        else:
            print("No filtered_posts.csv was created. Check for errors in the pipeline.")
    
    finally:
        # Restore the original scrape function
        entry.scrape_posts = original_scrape_posts
        
        # Restore backup CSV files
        for original_path, backup_path in backup_files.items():
            print(f"Restoring {original_path} from {backup_path}")
            try:
                with open(backup_path, 'r') as src, open(original_path, 'w') as dst:
                    dst.write(src.read())
            except Exception as e:
                print(f"Error restoring {original_path}: {e}")

def main():
    print("=== Test Tweet Processor ===")
    test_text = input("Enter test tweet text (or press Enter for default): ")
    if not test_text.strip():
        test_text = "Test tweet about a flood in Canada. Canada is experiencing severe flooding."
        print(f"Using default test: '{test_text}'")
    
    process_test_tweet(test_text)

if __name__ == "__main__":
    main()
