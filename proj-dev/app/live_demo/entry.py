import ast
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
import threading
import os
import time
from pathlib import Path

import pandas as pd
import requests
from pipeline_status import read_status, save_csv, write_status
from us_scope import is_us_location, us_records
from retention import live_retention_enabled, recent_posts
from jev_relevance import JevRelevance, get_relevance_client, RelevanceUnavailable
from crisis_classification import classification_mode, semantic_candidate
from post_context import candidate_text, context_for_post, extraction_text

DATA_DIR = Path(os.environ.get("CRISIS_DATA_DIR", Path(__file__).parent)).resolve()
MODEL_SERVER_URL = os.environ.get("MODEL_SERVER_URL", "http://127.0.0.1:5000").rstrip("/")
SCRAPER_SERVER_URL = os.environ.get("SCRAPER_SERVER_URL", "http://127.0.0.1:5001").rstrip("/")

_http = threading.local()


def model_session():
    if not hasattr(_http, 'session'):
        _http.session = requests.Session()
        _http.session.trust_env = False
    return _http.session


def screen_candidates(texts):
    response = model_session().post(f"{MODEL_SERVER_URL}/disaster_candidates",
                                    json={'texts': texts}, timeout=10)
    if response.status_code == 404:
        return [True] * len(texts)  # Older model/fixture servers remain compatible.
    response.raise_for_status()
    flags = response.json().get('candidates')
    if not isinstance(flags, list) or len(flags) != len(texts) or any(type(flag) is not bool for flag in flags):
        raise ValueError('Invalid batch screening response; keep the batch queued.')
    return flags


@lru_cache(maxsize=4)
def processing_pool(workers):
    return ThreadPoolExecutor(max_workers=workers, thread_name_prefix='crisis-post')


def extract_entities(text, *, rule_gate=True):
    """
    A direct call to the model_server's /extract_entities endpoint.
    Raises an exception if there's any HTTP/network error or if
    the server responds with 4xx/5xx status.
    """
    response = model_session().post(
        f"{MODEL_SERVER_URL}/extract_entities",
        json={'text': text, **({'rule_gate': False} if not rule_gate else {})},
        timeout=10
    )
    response.raise_for_status()  # Will raise a requests.HTTPError if status not 200
    result = response.json()
    if not rule_gate and result.get('rule_gate_applied') is not False:
        raise ValueError('The model service needs updating before Jev classification can run.')
    return result

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

def filter_posts(df: pd.DataFrame, on_progress=None, relevance_stats=None, *,
                 workers=1, prefilter=False, completed=None, progress_interval=0):
    if not 1 <= workers <= 4:
        raise ValueError("Processing workers must be between 1 and 4.")
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
        'relevance_status', 'relevance_model', 'relevance_probability',
        'classification_mode', 'classification_taxonomy', 'context_sources'
    ]

    relevance = get_relevance_client()
    classify = classification_mode() == 'jev'
    if classify and relevance is None:
        raise ValueError('Jev classification requires an enabled Jev client.')
    if relevance_stats is None:
        relevance_stats = {}
    completed = {} if completed is None else completed
    rows = list(df.iterrows())
    keys = [(str(row.get('uri', '')), row['text'], str(row.get('created_at', '')))
            for _, row in rows]
    pending = [i for i, key in enumerate(keys) if key not in completed]
    candidates = dict(zip(pending, screen_candidates([rows[i][1]['text'] for i in pending]))) if prefilter and pending and not classify else {}
    if prefilter and pending and classify:
        if os.environ.get('CRISIS_CANDIDATE_FILTER', 'expanded') == 'expanded':
            candidates = {i: semantic_candidate(candidate_text(rows[i][1])) for i in pending}
        elif os.environ.get('CRISIS_CANDIDATE_FILTER') != 'all':
            raise ValueError('CRISIS_CANDIDATE_FILTER must be expanded or all.')
        if os.environ.get('JEV_BATCH_SCREEN', 'off') == 'on':
            selected = [i for i in pending if candidates.get(i) is not False]
            batch, characters = [], 0
            for position in selected + [None]:
                text = candidate_text(rows[position][1]) if position is not None else ''
                if batch and (position is None or len(batch) == 16 or characters + len(text) > 12000):
                    flags = relevance.event_candidates([candidate_text(rows[i][1]) for i in batch])
                    if len(flags) != len(batch) or any(type(flag) is not bool for flag in flags):
                        raise ValueError('Invalid event screening decisions')
                    candidates.update(zip(batch, flags))
                    batch, characters = [], 0
                if position is not None:
                    batch.append(position)
                    characters += len(text)
    results, finished, errors, last_progress = {}, 0, 0, 0

    def consume(position, result, reused=False):
        nonlocal finished, errors, last_progress
        records, stats, failures = result
        results[position] = records
        for key, value in stats.items():
            relevance_stats[key] = relevance_stats.get(key, 0) + value
        if not reused and not any(stats.get(key, 0) for key in ('model_errors', 'relevance_errors', 'location_errors')):
            completed[keys[position]] = records
        finished += 1
        errors += failures
        now = time.monotonic()
        if on_progress and (finished == len(rows) or failures or now - last_progress >= progress_interval):
            last_progress = now
            on_progress(finished, errors)

    jobs = []
    for position, key in enumerate(keys):
        if key in completed:
            consume(position, (completed[key], {}, 0), reused=True)
        elif candidates.get(position) is False:
            consume(position, ([], {'rule_skipped': 1}, 0))
        else:
            jobs.append(position)
    if workers == 1:
        for position in jobs:
            consume(position, analyze_post(*rows[position], relevance, classify=classify))
    else:
        futures = {processing_pool(workers).submit(analyze_post, *rows[position], relevance, classify=classify): position
                   for position in jobs}
        for future in as_completed(futures):
            consume(futures[future], future.result())
    records = [record for position in range(len(rows)) for record in results[position]]
    return pd.DataFrame(records, columns=required_columns)


def analyze_post(idx, row, relevance, *, classify=False, diagnostics=None):
    """A worker returns data only; progress, CSV writes, and acknowledgement stay serial."""
    processed_rows, relevance_stats, errors = [], {}, 0
    try:
        context = context_for_post(row) if classify else []
        context_args = {'context': context} if context else {}
        entity_result = (extract_entities(extraction_text(row['text'], context), rule_gate=False)
                         if classify else extract_entities(row['text']))

        if not entity_result or not isinstance(entity_result, dict):
            raise ValueError('The model returned no valid entity data')
        if entity_result.get('location_status') == 'error':
            raise ValueError('Location lookup unavailable; keep the post queued.')
        if diagnostics is not None:
            diagnostics.update({key: entity_result.get(key) for key in (
                'locations', 'location_status', 'location_choices', 'unresolved_locations')})
        if entity_result.get('skipped_non_crisis') is True:
            relevance_stats['rule_skipped'] = relevance_stats.get('rule_skipped', 0) + 1

        disasters = entity_result.get('disasters', [])
        locations = entity_result.get('locations', [])
        sentiment = entity_result.get('sentiment', 'Neutral')
        polarity = entity_result.get('polarity', 0.0)

        # Semantic classification must also see posts the original disaster rules missed.
        if not locations or (not disasters and not classify):
            return [], relevance_stats, errors
        chosen_locations = []
        choices = entity_result.get('location_choices', [])
        if relevance and choices:
            try:
                chosen_locations = relevance.choose_locations(row['text'], choices, **context_args)
                relevance_stats['location_checked'] = relevance_stats.get('location_checked', 0) + len(choices)
                relevance_stats['location_resolved'] = relevance_stats.get('location_resolved', 0) + len(chosen_locations)
            except RelevanceUnavailable as exc:
                relevance_stats['location_errors'] = relevance_stats.get('location_errors', 0) + 1
                print(str(exc))
        resolved_mentions = {loc['location'] for loc in chosen_locations}
        unresolved = [loc for loc in entity_result.get('unresolved_locations', [])
                      if loc not in resolved_mentions]
        if diagnostics is not None:
            diagnostics['unresolved_locations'] = unresolved
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
        if diagnostics is not None:
            diagnostics['resolved_locations'] = len(location_rows)

        if relevance and location_rows:
            decide = relevance.classify if classify else relevance.screen
            screened = decide(row['text'], row.get('created_at', ''), location_rows, **context_args)
            relevance_stats['relevance_checked'] = relevance_stats.get('relevance_checked', 0) + len(location_rows)
            relevance_stats['relevance_excluded'] = relevance_stats.get('relevance_excluded', 0) + len(location_rows) - len(screened)
            location_rows = screened
        for location in location_rows:
            location['context_sources'] = '; '.join(item.get('uri', 'attached headline') for item in context)
        processed_rows.extend(location_rows)

    except RelevanceUnavailable as exc:
        relevance_stats['relevance_errors'] = relevance_stats.get('relevance_errors', 0) + 1
        print(str(exc))
    except Exception as e:
        print(f"Error processing row {idx}: {e}")
        errors += 1
        relevance_stats['model_errors'] = errors

    return processed_rows, relevance_stats, errors

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


COUNT_COLUMNS = ['country', 'state', 'disasters', 'count', 'avg_sentiment', 'cities', 'severity']


def calculate_crisis_counts(df, existing_counts_file=None):
    df = us_records(df)

    if df.empty:
        # If no new data, return existing counts or empty DataFrame
        if existing_counts_file and os.path.exists(existing_counts_file):
            try:
                return us_records(pd.read_csv(existing_counts_file))
            except (OSError, ValueError):
                return pd.DataFrame(columns=COUNT_COLUMNS)
        else:
            return pd.DataFrame(columns=COUNT_COLUMNS)

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

_next_retention_sweep = {}
_pending_receipt = None
_completed_posts = {}


def prune_saved_reports(output_dir, now=None):
    """The single CSV writer expires reports and regenerates totals, including zero."""
    output_dir = Path(output_dir)
    path = output_dir / 'filtered_posts.csv'
    if not path.is_file():
        return
    remaining = recent_posts(us_records(pd.read_csv(path)), now=now)
    save_csv(remaining, path)
    save_csv(calculate_crisis_counts(remaining), output_dir / 'crisis_counts.csv')


def main(post_limit=20, output_dir=DATA_DIR):
    global _pending_receipt, _completed_posts
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    retention = live_retention_enabled(output_dir)
    if retention and time.monotonic() >= _next_retention_sweep.get(output_dir, 0):
        try:
            prune_saved_reports(output_dir)
            _next_retention_sweep[output_dir] = time.monotonic() + 30
        except (OSError, ValueError, KeyError):
            write_status(output_dir, phase="error", last_error="Could not refresh the latest reports. Retrying.")
            return
    previous = read_status(output_dir)
    reviewer = get_relevance_client()
    if isinstance(reviewer, JevRelevance) and previous.get('phase') == 'error':
        diagnostics = reviewer.diagnostics()
        if diagnostics['jev_cooldown_seconds'] > 0:
            # The collector continues independently; don't repeat context/NLP work
            # for this receipt while every uncached Jev request would be rejected.
            write_status(output_dir, **diagnostics)
            return
    relevance_stats = {}
    write_status(output_dir, phase="collecting", last_error=None,
                 relevance_mode=os.environ.get("CRISIS_RELEVANCE_MODE", "off"),
                 classification_mode=os.environ.get("CRISIS_CLASSIFICATION_MODE", "rules"))
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
    if (str(output_dir), receipt) != _pending_receipt or not receipt:
        _pending_receipt = (str(output_dir), receipt)
        _completed_posts = {}
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
        if retention:
            df = recent_posts(df)
    except Exception as e:
        print(f"Error creating DataFrame: {e}")
        return

    print(f'Scraped {len(df)} posts')
    processing_started = time.perf_counter()
    write_status(output_dir, phase="processing", batch_received=len(posts), batch_processed=0,
                 collection_ms=round((processing_started - collect_started) * 1000, 1),
                 posts_received=previous.get("posts_received", 0) + (0 if replay else len(posts)),
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
        filtered_df = filter_posts(df, on_progress=progress, relevance_stats=relevance_stats,
                                   workers=int(os.environ.get('CRISIS_PROCESSING_WORKERS', '4' if retention else '1')),
                                   prefilter=retention, completed=_completed_posts if receipt else None,
                                   progress_interval=0.25)
        print(f'Processed and identified {len(filtered_df)} crisis posts')
        reviewer = get_relevance_client()
        if isinstance(reviewer, JevRelevance):
            relevance_stats.update(reviewer.diagnostics())
            write_status(output_dir, **{key: value for key, value in relevance_stats.items() if key.startswith('jev_')})
    except Exception as e:
        print(f"Error filtering posts: {e}")
        reviewer = get_relevance_client()
        diagnostics = reviewer.diagnostics() if isinstance(reviewer, JevRelevance) else {}
        write_status(output_dir, phase="error", last_error="This batch could not be analyzed. Retrying.", **diagnostics)
        return

    if receipt and any(relevance_stats.get(key, 0) for key in ('model_errors', 'location_errors', 'relevance_errors')):
        call_limit = relevance_stats.get('jev_max_calls', 0)
        capped = call_limit > 0 and relevance_stats.get('jev_calls', 0) >= call_limit
        message = ("Jev's configured request limit is reached. Posts remain queued."
                   if capped else "Analysis unavailable. Keeping this batch queued for retry.")
        write_status(output_dir, phase="error", last_error=message)
        return

    if filtered_df.empty:
        print("No crisis posts found. Skipping this run.")
        finish()
        return

    # Rebuild totals from the saved records: replay after a write/ack failure is idempotent.
    try:
        destination = output_dir / 'filtered_posts.csv'
        existing = us_records(pd.read_csv(destination)) if destination.is_file() else pd.DataFrame()
        if retention:
            existing = recent_posts(existing)
            filtered_df = recent_posts(filtered_df)
        combined = pd.concat([existing, filtered_df], ignore_index=True)
        keys = combined[['uri', 'country', 'state', 'city']].fillna('')
        repeated = keys['uri'].ne('') & keys.duplicated(keep='first')
        combined = combined[~repeated].copy()
        added = max(0, len(combined) - len(existing))
        save_csv(combined, destination)
        counts = calculate_crisis_counts(combined)
        save_csv(counts, output_dir / 'crisis_counts.csv')
        finish(added)
    except Exception as exc:
        print(f"Could not save this batch: {exc}")
        write_status(output_dir, phase="error", last_error="Could not save posts and counts. Keeping this batch queued for retry.")

if __name__ == '__main__':
    post_limit = int(os.environ.get('CRISIS_BATCH_SIZE', '100' if live_retention_enabled(DATA_DIR) else '20'))
    if not 1 <= post_limit <= 100:
        raise ValueError('CRISIS_BATCH_SIZE must be between 1 and 100.')
    while True:
        try:
            main(post_limit)
            status = read_status(DATA_DIR)
            if status.get('phase') == 'error':
                time.sleep(2)
            elif status.get('batch_received', 0) < post_limit:
                time.sleep(0.1)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(1)
