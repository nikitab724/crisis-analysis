#!/usr/bin/env python3

import os
import time
import inspect
import pandas as pd

# Import from your existing pipeline code
# (Adjust as needed if 'entry.py' is not in the same directory)
from entry import filter_posts, extract_entities, reset_csv_files, calculate_crisis_counts
from entry import main as entry_main

def create_mock_post(text):
    """
    Create a single mock post dictionary that resembles 
    the format a real 'scrape' would produce.

    This avoids sending a request to any server's /test_tweet route.
    """
    # You can change these fields as needed
    mock_post = {
        'author': 'test_user.bsky.social',
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'post_id': '',
        'text': text,
        'uri': f'at://did:plc:test/{time.time()}'
    }
    # Return a list with this single dict, 
    # matching the shape that get_scraped_posts(...) normally returns
    return [mock_post]

def process_test_tweet(text):
    """
    Process a single test tweet through the 'entry.py' pipeline:
      1. Backs up existing CSVs (filtered_posts.csv, crisis_counts.csv).
      2. Creates a local mock post from 'text'.
      3. Monkey-patches entry.scrape_posts so 'entry_main()' processes ONLY that single post.
      4. Calls entry_main(), then restores the original function and CSV backups.
    """
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
    
    # 2) Create a single mock post from the text
    print(f"Creating a single test post from: '{text}'")
    posts = create_mock_post(text)
    if not posts:
        print("Error: No mock posts created. Aborting.")
        return
    
    print(f"Test post created successfully! {len(posts)} post(s) in our list.")

    # 3) Monkey-patch the scraping function so 'entry_main()' processes only that single post
    import entry
    original_scrape_posts = entry.get_scraped_posts  # or entry.get_scraped_posts, whichever your 'entry.py' calls
    
    def mock_scrape_posts(limit=None):
        """
        Returns the single test post only (ignoring real scraping).
        """
        print("Using mock scraper that returns the single test post only...")
        return posts
    
    entry.get_scraped_posts = mock_scrape_posts

    try:
        # 4) Call entry_main() to run the pipeline
        print("Processing test post through entry_main() pipeline...")
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
                    
                    if len(df) > 1:
                        print("\nWARNING: More than one row was generated from a single test post!")
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
