import ast
import os
import time
from pathlib import Path

import pandas as pd
import requests
from pipeline_status import read_status, save_csv, write_status
from us_scope import is_us_location, us_records
from jev_relevance import get_relevance_client, RelevanceUnavailable

DATA_DIR = Path(os.environ.get("CRISIS_DATA_DIR", Path(__file__).parent)).resolve()
MODEL_SERVER_URL = os.environ.get("MODEL_SERVER_URL", "http://127.0.0.1:5000").rstrip("/")
SCRAPER_SERVER_URL = os.environ.get("SCRAPER_SERVER_URL", "http://127.0.0.1:5001").rstrip("/")

def extract_entities(text):
    """
    A direct call to the model_server's /extract_entities endpoint.
    Raises an exception if there's any HTTP/network error or if
    the server responds with 4xx/5xx status.
    """
    response = requests.post(
        f"{MODEL_SERVER_URL}/extract_entities",
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
        'latitude': None,
        'longitude': None,
        'all_locations': None
    }

class CollectedPosts(list):
    def __init__(self, posts, receipt=None, collector=None):
        super().__init__(posts)
        self.receipt = receipt
        self.collector = collector or {}


def acknowledge_posts(posts):
    receipt = getattr(posts, 'receipt', None)
    if receipt:
        response = requests.post(f"{SCRAPER_SERVER_URL}/ack", json={'receipt': receipt}, timeout=5)
        response.raise_for_status()


def get_scraped_posts(limit=20):
    url = f"{SCRAPER_SERVER_URL}/scrape"
    params = {"limit": limit}
    try:
        response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()
        return CollectedPosts(data.get("posts", []), data.get("receipt"), data.get("collector"))
    except requests.exceptions.RequestException as e:
        print(f"Could not fetch posts: {e}")
        if os.environ.get("CRISIS_PIPELINE_MODE") == "live":
            raise
        return []
    except Exception as e:
        print(f"Invalid scraper response: {e}")
        return []

def filter_posts(df: pd.DataFrame, on_progress=None, relevance_stats=None):
    # Create a copy of the DataFrame to avoid SettingWithCopyWarning
    df = df.copy()

    # Distinct source posts may have identical text. Deduplicate by URI when available.
    if 'uri' in df:
        identified = df['uri'].fillna('').ne('')
        df = pd.concat([df[identified].drop_duplicates(subset=['uri']),
                        df[~identified].drop_duplicates(subset=['text'])]).sort_index()
    else:
        df = df.drop_duplicates(subset=['text'])

    # Drop rows where text is empty (has zero length)
    df = df[df['text'].str.len() > 0]

    # Define required columns for consistency
    required_columns = [
        'author', 'created_at', 'post_id', 'text', 'uri',
        'disasters', 'sentiment', 'polarity',
        'city', 'state', 'region', 'country', 'latitude', 'longitude', 'location',
        'location_status', 'location_detail', 'location_mentions', 'location_review',
        'geonameid', 'location_model', 'location_probability', 'location_context_probability',
        'relevance_status', 'relevance_model', 'relevance_probability'
    ]

    # Process each row individually to avoid entity_data errors
    processed_rows = []
    relevance = get_relevance_client()
    if relevance_stats is None:
        relevance_stats = {}

    errors = 0
    for processed, (idx, row) in enumerate(df.iterrows(), start=1):
        try:
            # Extract entities with error handling
            entity_result = extract_entities(row['text'])

            if not entity_result or not isinstance(entity_result, dict):
                raise ValueError('The model returned no valid entity data')
            if entity_result.get('skipped_non_crisis') is True:
                relevance_stats['rule_skipped'] = relevance_stats.get('rule_skipped', 0) + 1

            disasters = entity_result.get('disasters', [])
            locations = entity_result.get('locations', [])
            sentiment = entity_result.get('sentiment', 'Neutral')
            polarity = entity_result.get('polarity', 0.0)

            # Require both a disaster mention and a location.
            if not disasters or not locations:
                continue
            chosen_locations = []
            choices = entity_result.get('location_choices', [])
            if relevance and choices:
                try:
                    chosen_locations = relevance.choose_locations(row['text'], choices)
                    relevance_stats['location_checked'] = relevance_stats.get('location_checked', 0) + len(choices)
                    relevance_stats['location_resolved'] = relevance_stats.get('location_resolved', 0) + len(chosen_locations)
                except RelevanceUnavailable as exc:
                    relevance_stats['location_errors'] = relevance_stats.get('location_errors', 0) + 1
                    print(str(exc))
            resolved_mentions = {loc['location'] for loc in chosen_locations}
            unresolved = [loc for loc in entity_result.get('unresolved_locations', [])
                          if loc not in resolved_mentions]
            location_review = entity_result.get('location_review', '')
            if 'unresolved_locations' in entity_result:
                location_review = 'Unresolved mentions: ' + '; '.join(dict.fromkeys(unresolved)) if unresolved else ''
            location_rows = []
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
                        'country': entity_result.get('country'),
                        'latitude': entity_result.get('latitude', None),
                        'longitude': entity_result.get('longitude', None),
                        'location': entity_result.get('location', entity_result.get('city', '')),
                        'location_status': entity_result.get('location_status', ''),
                        'location_detail': entity_result.get('location_detail', ''),
                        'location_mentions': entity_result.get('location_mentions', '; '.join(locations)),
                        'location_review': location_review,
                        'geonameid': entity_result.get('geonameid'),
                    }
            if is_us_location(top_row):
                location_rows.append(top_row)
            # Get standardized location info
            all_locations = entity_result.get('all_locations', [])
            all_locations = (all_locations if isinstance(all_locations, list) else []) + chosen_locations

            # If we have location details, create rows for each location
            if isinstance(all_locations, list) and all_locations:
                for loc_info in all_locations:
                    if not isinstance(loc_info, dict) or not is_us_location(loc_info):
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
                        'country': loc_info.get('country'),
                        'latitude': loc_info.get('latitude', None),
                        'longitude': loc_info.get('longitude', None),
                        'location': loc_info.get('location', ''),
                        'location_status': loc_info.get('location_status', ''),
                        'location_detail': loc_info.get('location_detail', ''),
                        'location_mentions': entity_result.get('location_mentions', '; '.join(locations)),
                        'location_review': location_review,
                        **{key: loc_info.get(key) for key in (
                            'geonameid', 'location_model', 'location_probability', 'location_context_probability')},
                    }

                    location_rows.append(new_row)

            # A new context-selected city replaces its supporting state, and
            # aliases for the same coordinates must not inflate report counts.
            city_states = {loc['state'] for loc in location_rows if loc.get('city')}
            unique_locations = {}
            for loc in location_rows:
                if not loc.get('city') and loc['state'] in city_states:
                    continue
                identity = tuple(loc.get(key) for key in ('city', 'state', 'latitude', 'longitude'))
                unique_locations.setdefault(identity, loc)
            location_rows = list(unique_locations.values())

            if relevance and location_rows:
                screened = relevance.screen(row['text'], row.get('created_at', ''), location_rows)
                relevance_stats['relevance_checked'] = relevance_stats.get('relevance_checked', 0) + len(location_rows)
                relevance_stats['relevance_excluded'] = relevance_stats.get('relevance_excluded', 0) + len(location_rows) - len(screened)
                location_rows = screened
            processed_rows.extend(location_rows)

        except RelevanceUnavailable as exc:
            relevance_stats['relevance_errors'] = relevance_stats.get('relevance_errors', 0) + 1
            print(str(exc))
        except Exception as e:
            print(f"Error processing row {idx}: {e}")
            errors += 1
            relevance_stats['model_errors'] = errors
            continue
        finally:
            if on_progress:
                on_progress(processed, errors)

    result_df = pd.DataFrame(processed_rows, columns=required_columns)

    return result_df

def parse_cities(value):
    """Read CSV list values without executing code or accepting other types."""
    if isinstance(value, str):
        try:
            value = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return []
    if not isinstance(value, list):
        return []
    return [city for city in value if isinstance(city, str)]


def calculate_crisis_counts(df, existing_counts_file=None):
    df = us_records(df)

    if df.empty:
        # If no new data, return existing counts or empty DataFrame
        if existing_counts_file and os.path.exists(existing_counts_file):
            try:
                return us_records(pd.read_csv(existing_counts_file))
            except (OSError, ValueError):
                return pd.DataFrame()
        else:
            return pd.DataFrame()

    # Make a copy to avoid modifying the original dataframe
    df_copy = df.copy()

    # Ensure disasters is a string if it's a list
    if 'disasters' in df_copy.columns:
        # Convert list to string only for grouping
        def first_disaster(value):
            if isinstance(value, str) and value.startswith('['):
                try:
                    value = ast.literal_eval(value)
                except (ValueError, SyntaxError):
                    return 'Unknown'
            return value[0] if isinstance(value, list) and value else (value if isinstance(value, str) else 'Unknown')
        df_copy['disaster_str'] = df_copy['disasters'].apply(first_disaster)

    # Process new data - use disaster_str for grouping
    exploded_new = df_copy.copy()

    # Group by country, state, and disaster type
    new_counts = (exploded_new.groupby(["country", "state", "disaster_str"])
        .agg(
            count=('disaster_str', 'size'),
            avg_sentiment=('polarity', 'mean'),
            cities=('city', lambda x: sorted({c for c in x if pd.notnull(c)}))
        )
        .reset_index()
        .rename(columns={'disaster_str': 'disasters'})
        .round({'avg_sentiment': 2})
    )

    # Handle existing counts file if it exists
    if existing_counts_file and os.path.exists(existing_counts_file) and os.path.getsize(existing_counts_file) > 0:
        try:
            existing_counts = us_records(pd.read_csv(existing_counts_file))

            if not existing_counts.empty:
                # Convert string representation of cities lists back to actual lists
                try:
                    existing_counts['cities'] = existing_counts['cities'].apply(
                        parse_cities
                    )
                except (OSError, ValueError):
                    # If there's an error with the cities column, just use an empty list
                    existing_counts['cities'] = [[] for _ in range(len(existing_counts))]

                # Combine with new counts
                combined = pd.concat([existing_counts, new_counts])

                # Re-aggregate by country, state, and disaster type
                counts = combined.groupby(["country", "state", "disasters"]).agg({
                    'count': 'sum',
                    'avg_sentiment': 'mean',
                    'cities': lambda x: sorted({item for sublist in x for item in sublist if item})
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
        counts_std = counts['count'].std()
        if pd.isna(counts_std) or counts_std == 0:
            counts_std = 1
        counts['severity'] = (counts['count'] - counts_mean) / counts_std

    return counts

def reset_csv_files(output_dir=DATA_DIR):
    """Check and reset CSV files if corrupt"""

    # Define expected columns for each file
    expected_columns = {
        'filtered_posts.csv': [
            'author', 'created_at', 'post_id', 'text', 'uri', 'preprocessed_text',
            'disasters', 'locations', 'sentiment', 'polarity',
            'city', 'state', 'region', 'country', 'latitude', 'longitude', 'location'
        ],
        'crisis_counts.csv': [
            'country', 'state', 'disasters', 'count', 'avg_sentiment', 'cities', 'severity'
        ]
    }

    for filename, columns in expected_columns.items():
        file_path = Path(output_dir) / filename
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
                            df[col] = [[] for _ in range(len(df))]
                        elif col in ['polarity', 'count', 'avg_sentiment', 'severity']:
                            df[col] = 0.0
                        elif col in ['sentiment']:
                            df[col] = 'Neutral'
                        else:
                            df[col] = ''

                    # Save fixed file
                    save_csv(df, file_path)
                    print(f"Fixed column structure in {file_path}")

            except Exception as e:
                print(f"Error verifying {file_path}, resetting: {e}")
                os.remove(file_path)
                print(f"Removed corrupted file: {file_path}")

def main(post_limit=20, output_dir=DATA_DIR):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    previous = read_status(output_dir)
    relevance_stats = {}
    write_status(output_dir, phase="collecting", last_error=None,
                 relevance_mode=os.environ.get("CRISIS_RELEVANCE_MODE", "off"))
    collect_started = time.perf_counter()
    try:
        posts = get_scraped_posts(post_limit)
    except requests.RequestException:
        write_status(output_dir, phase="error", last_error="Could not collect Bluesky posts. Retrying.")
        return

    collector = getattr(posts, 'collector', {})
    if collector:
        write_status(output_dir, collector=collector)
    receipt = getattr(posts, 'receipt', None)
    replay = bool(receipt and receipt == previous.get('batch_receipt'))
    processed_base = previous.get('batch_processed_base', 0) if replay else previous.get('posts_processed', 0)

    if not posts:
        print("No posts to process. Skipping this run.")
        write_status(output_dir, phase="waiting", batch_received=0)
        if collector and collector.get('state') != 'connected':
            write_status(output_dir, phase="error", last_error="Collection interrupted; reconnecting from the saved position.")
        return

    # Load collected posts
    try:
        df = pd.DataFrame(posts)
    except Exception as e:
        print(f"Error creating DataFrame: {e}")
        return

    print(f'Scraped {len(df)} posts')
    processing_started = time.perf_counter()
    write_status(output_dir, phase="processing", batch_received=len(df), batch_processed=0,
                 collection_ms=round((processing_started - collect_started) * 1000, 1),
                 posts_received=previous.get("posts_received", 0) + (0 if replay else len(df)),
                 batch_receipt=receipt, batch_processed_base=processed_base)

    def progress(processed, errors):
        write_status(output_dir, phase="processing", batch_processed=processed,
                     posts_processed=processed_base + processed - errors,
                     model_errors=previous.get("model_errors", 0) + errors,
                     **{key: previous.get(key, 0) + relevance_stats.get(key, 0)
                        for key in ('relevance_checked', 'relevance_excluded', 'relevance_errors',
                                    'location_checked', 'location_resolved', 'location_errors', 'rule_skipped')})

    def finish(matches=0):
        try:
            acknowledge_posts(posts)
        except requests.RequestException:
            write_status(output_dir, phase="error", last_error="Could not acknowledge saved work. The batch will be retried.")
            return
        write_status(output_dir, phase="waiting", batch_matches=matches,
                     processing_ms=round((time.perf_counter() - processing_started) * 1000, 1),
                     batches_completed=previous.get("batches_completed", 0) + 1,
                     matched_records=previous.get("matched_records", 0) + matches)

    try:
        filtered_df = filter_posts(df, on_progress=progress, relevance_stats=relevance_stats)
        print(f'Processed and identified {len(filtered_df)} crisis posts')
    except Exception as e:
        print(f"Error filtering posts: {e}")
        write_status(output_dir, phase="error", last_error="This batch could not be analyzed. Retrying.")
        return

    if receipt and any(relevance_stats.get(key, 0) for key in ('model_errors', 'location_errors', 'relevance_errors')):
        write_status(output_dir, phase="error", last_error="Analysis unavailable. Keeping this batch queued for retry.")
        return

    if filtered_df.empty:
        print("No crisis posts found. Skipping this run.")
        finish()
        return

    # Rebuild totals from the saved records: replay after a write/ack failure is idempotent.
    try:
        destination = output_dir / 'filtered_posts.csv'
        existing = us_records(pd.read_csv(destination)) if destination.is_file() else pd.DataFrame()
        combined = pd.concat([existing, filtered_df], ignore_index=True)
        keys = combined[['uri', 'country', 'state', 'city']].fillna('')
        repeated = keys['uri'].ne('') & keys.duplicated(keep='first')
        combined = combined[~repeated].copy()
        added = max(0, len(combined) - len(existing))
        save_csv(combined, destination)
        counts = calculate_crisis_counts(combined)
        if not counts.empty:
            save_csv(counts, output_dir / 'crisis_counts.csv')
        finish(added)
    except Exception as exc:
        print(f"Could not save this batch: {exc}")
        write_status(output_dir, phase="error", last_error="Could not save posts and counts. Keeping this batch queued for retry.")

if __name__ == '__main__':
    post_limit = 20
    while True:
        try:
            main(post_limit)
            time.sleep(2 if read_status(DATA_DIR).get("phase") == "error" else 0.1)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(1)
