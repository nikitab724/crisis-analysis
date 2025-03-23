import time
import os
import csv
import multiprocessing
from datetime import datetime
from atproto import FirehoseSubscribeReposClient, parse_subscribe_repos_message, CAR, IdResolver, DidInMemoryCache

# ==============================================================================
# Internal Helper Functions
# ==============================================================================

def _resolve_author_handle(repo, resolver):
    """Resolve the author handle from the DID."""
    try:
        resolved_info = resolver.did.resolve(repo)
        return resolved_info.also_known_as[0].split('at://')[1] if resolved_info.also_known_as else repo
    except Exception as e:
        print(f"Could not resolve handle for {repo}: {e}")
        return repo  # Fallback to DID

def _check_for_images(record):
    """Check if the post has images."""
    embed = record.get('embed', {})
    return (
        embed.get('$type') == 'app.bsky.embed.images' or
        (embed.get('$type') == 'app.bsky.embed.external' and 'thumb' in embed)
    )

def _get_reply_to(record):
    """Get the URI of the post being replied to."""
    reply_ref = record.get('reply', {})
    return reply_ref.get('parent', {}).get('uri')

# ==============================================================================
# Core Processing Functions
# ==============================================================================

def _extract_post_data(record, repo, path, author_handle):
    """
    Extract post data from a record returned by the Firehose. 
    Return a dict containing relevant fields.
    """
    has_images = _check_for_images(record)
    reply_to = _get_reply_to(record)
    return {
        'text': record.get('text', ''),
        'created_at': record.get('createdAt', ''),
        'author': author_handle,
        'uri': f'at://{repo}/{path}',
        'has_images': has_images,
        'reply_to': reply_to
    }

def _process_post(commit, op, resolver, data_callback, keyword=None):
    """
    Process a single post operation with optional keyword filtering.
    Once the post data is extracted, call `data_callback(post_data)`
    so the user can handle/save the data however they choose.
    """
    try:
        author_handle = _resolve_author_handle(commit.repo, resolver)
        car = CAR.from_bytes(commit.blocks)
        for record in car.blocks.values():
            if isinstance(record, dict) and record.get('$type') == 'app.bsky.feed.post':
                post_data = _extract_post_data(record, commit.repo, op.path, author_handle)

                # Filter based on keyword (case-insensitive)
                if keyword and keyword.lower() not in post_data['text'].lower():
                    continue  # Skip this post if it doesn't contain the keyword

                # Pass the post data to the user-defined callback
                data_callback(post_data)

    except Exception as e:
        print(f"Error processing record: {e}")

def process_message(message, resolver, data_callback, keyword=None):
    """
    Process a single message from the firehose, filtering posts if a keyword is specified.
    Once a valid post is found, calls `data_callback(post_data)`.
    """
    try:
        commit = parse_subscribe_repos_message(message)
        if not hasattr(commit, 'ops'):
            return

        for op in commit.ops:
            if op.action == 'create' and op.path.startswith('app.bsky.feed.post/'):
                _process_post(commit, op, resolver, data_callback, keyword)

    except Exception as e:
        print(f"Error processing message: {e}")

# ==============================================================================
# Worker / Client Processes
# ==============================================================================

def worker_process(queue, resolver, data_callback, stop_event, keyword):
    """
    Worker process that continually pulls messages off the queue
    and processes them. Terminates when 'stop_event' is set.
    """
    while not stop_event.is_set():
        try:
            message = queue.get(timeout=1)
            process_message(message, resolver, data_callback, keyword)
        except multiprocessing.queues.Empty:
            continue
        except Exception as e:
            print(f"Worker error: {e}")

def client_process(queue, stop_event):
    """
    The client process that subscribes to the Firehose and places
    incoming messages onto the multiprocessing queue.
    """
    client = FirehoseSubscribeReposClient()
    def message_handler(message):
        if stop_event.is_set():
            client.stop()
            return
        queue.put(message)

    try:
        client.start(message_handler)
    except Exception as e:
        if not stop_event.is_set():
            print(f"Client process error: {e}")

# ==============================================================================
# The FirehoseScraper Class
# ==============================================================================

class FirehoseScraper:
    """
    A class to subscribe to the Bluesky Firehose and process post data in real time.

    Usage:
        1. Instantiate with desired parameters:
           scraper = FirehoseScraper(num_workers=4, keyword="dog")
        2. Define a data_callback function to handle each post:
           def my_callback(post_data):
               # store in DB, write to CSV, etc.
        3. Start indefinitely:
           scraper.start_collection(data_callback=my_callback)

        The collection continues until you kill the process (Ctrl+C) or call 
        `scraper.stop_collection()` from your code.
    """
    def __init__(
        self,
        num_workers=4,
        keyword=None, 
        verbose=False
    ):
        self.num_workers = num_workers
        self.keyword = keyword
        self.verbose = verbose
        self.queue = multiprocessing.Queue()
        self.workers = []
        self.stop_event = multiprocessing.Event()
        self.client_proc = None

        # For DID resolution
        self.cache = DidInMemoryCache()
        self.resolver = IdResolver(cache=self.cache)

    def start_collection(self, data_callback):
        """
        Start collecting posts. This method will run indefinitely unless 
        stopped by user interrupt (Ctrl+C) or by calling `stop_collection()`.

        Args:
            data_callback (callable): Function that takes a single argument (post_data dict)
                                      and handles/stores that data. 
        """
        print("Starting firehose collection...")
        if self.keyword:
            print(f"Filtering posts that contain the keyword: '{self.keyword}'")

        # Start worker processes
        for _ in range(self.num_workers):
            p = multiprocessing.Process(
                target=worker_process,
                args=(
                    self.queue,
                    self.resolver,
                    data_callback,
                    self.stop_event,
                    self.keyword
                )
            )
            p.start()
            self.workers.append(p)

        # Start the client process
        self.client_proc = multiprocessing.Process(
            target=client_process,
            args=(self.queue, self.stop_event)
        )
        self.client_proc.start()

        # Monitor indefinitely
        try:
            while not self.stop_event.is_set():
                # If the client process dies unexpectedly, stop everything
                if not self.client_proc.is_alive():
                    print("\nClient process exited unexpectedly.")
                    self.stop_collection()
                    break
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nCollection interrupted by user.")
            self.stop_collection()
        except Exception as e:
            print(f"\nUnexpected error: {e}")
            self.stop_collection()
        finally:
            self.stop_collection()

    def stop_collection(self):
        """Stop the collection gracefully."""
        if not self.stop_event.is_set():
            self.stop_event.set()

        # Stop the client process
        if self.client_proc and self.client_proc.is_alive():
            self.client_proc.terminate()
            self.client_proc.join()

        # Stop all worker processes
        for p in self.workers:
            if p.is_alive():
                p.terminate()
            p.join()

        print("Firehose collection stopped.")

# ==============================================================================
# Optional: A Default CSV Callback
# ==============================================================================

def csv_data_callback_factory(output_file="bluesky_posts.csv"):
    """
    Returns a callback function that saves incoming post_data to a CSV file.
    This is purely optional – you can define your own callback for any DB/storage.
    """
    # Ensure the output directory exists
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)

    # A counter to give each post a unique numeric ID (per runtime)
    from itertools import count
    post_id_generator = count(start=1)

    # Prepare CSV file with headers if needed
    file_exists = os.path.exists(output_file)
    if not file_exists:
        with open(output_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Post ID", "Author", "Text", "Created At", "URI", "URL", "Has Images", "Reply To"])

    def _csv_data_callback(post_data):
        """
        Callback that writes the post_data to a CSV file.
        """
        post_id = next(post_id_generator)

        # Build a post URL from the URI
        post_url = f"https://bsky.app/profile/{post_data['author']}/post/{post_data['uri'].split('/')[-1]}"

        # Write the data
        with open(output_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                post_id,
                post_data['author'],
                post_data['text'].replace("\n", " "),
                post_data['created_at'],
                post_data['uri'],
                post_url,
                post_data['has_images'],
                post_data['reply_to'] or "N/A"
            ])

    return _csv_data_callback
