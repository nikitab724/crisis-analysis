from atproto import FirehoseSubscribeReposClient, parse_subscribe_repos_message, CAR, IdResolver, DidInMemoryCache
import time
from datetime import datetime
import multiprocessing
import sys
import signal
import csv
import os
import json

def _save_post_data(post_data, output_file, verbose, post_count, lock):
    """Save post data to a CSV file with a unique post ID."""
    file_exists = os.path.exists(output_file)  # Check if file already exists

    with lock:
        with open(output_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            # Write headers only if the file is new
            if not file_exists:
                writer.writerow(["Post ID", "Author", "Text", "Created At", "URI", "Has Images", "Reply To"])

            # Write post data with a unique post ID
            writer.writerow([
                post_count.value + 1,  # Assign post ID starting from 1
                post_data['author'],
                post_data['text'].replace("\n", " "),  # Remove newlines for CSV formatting
                post_data['created_at'],
                post_data['uri'],
                post_data['has_images'],
                post_data['reply_to'] or "N/A"
            ])

    with post_count.get_lock():
        post_count.value += 1  # Increment the post counter

    if verbose:
        print(f"Saved post #{post_count.value} by @{post_data['author']}: {post_data['text'][:50]}...")


def worker_process(queue, output_file, verbose, post_count, lock, stop_event):
    resolver = IdResolver(cache=DidInMemoryCache())
    while not stop_event.is_set():
        try:
            message = queue.get(timeout=1)
            process_message(message, resolver, output_file, verbose, post_count, lock)
        except multiprocessing.queues.Empty:
            continue
        except Exception as e:
            print(f"Worker error: {e}")

def client_process(queue, stop_event):
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

def process_message(message, resolver, output_file, verbose, post_count, lock):
    """Process a single message from the firehose"""
    try:
        commit = parse_subscribe_repos_message(message)
        if not hasattr(commit, 'ops'):
            return

        for op in commit.ops:
            if op.action == 'create' and op.path.startswith('app.bsky.feed.post/'):
                _process_post(commit, op, resolver, output_file, verbose, post_count, lock)

    except Exception as e:
        print(f"Error processing message: {e}")

def _process_post(commit, op, resolver, output_file, verbose, post_count, lock):
    """Process a single post operation"""
    try:
        author_handle = _resolve_author_handle(commit.repo, resolver)
        car = CAR.from_bytes(commit.blocks)
        for record in car.blocks.values():
            if isinstance(record, dict) and record.get('$type') == 'app.bsky.feed.post':
                post_data = _extract_post_data(record, commit.repo, op.path, author_handle)
                _save_post_data(post_data, output_file, verbose, post_count, lock)
    except Exception as e:
        print(f"Error processing record: {e}")

def _resolve_author_handle(repo, resolver):
    """Resolve the author handle from the DID"""
    try:
        resolved_info = resolver.did.resolve(repo)
        return resolved_info.also_known_as[0].split('at://')[1] if resolved_info.also_known_as else repo
    except Exception as e:
        print(f"Could not resolve handle for {repo}: {e}")
        return repo  # Fallback to DID

def _extract_post_data(record, repo, path, author_handle):
    """Extract post data from a record"""
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

def _check_for_images(record):
    """Check if the post has images"""
    embed = record.get('embed', {})
    return (
        embed.get('$type') == 'app.bsky.embed.images' or
        (embed.get('$type') == 'app.bsky.embed.external' and 'thumb' in embed)
    )

def _get_reply_to(record):
    """Get the URI of the post being replied to"""
    reply_ref = record.get('reply', {})
    return reply_ref.get('parent', {}).get('uri')

class FirehoseScraper:
    def __init__(self, output_file="bluesky_posts.jsonl", verbose=False, num_workers=4):
        self.output_file = output_file
        self.post_count = multiprocessing.Value('i', 0)  # Shared integer
        self.start_time = None
        self.cache = DidInMemoryCache() 
        self.resolver = IdResolver(cache=self.cache)
        self.verbose = verbose
        self.queue = multiprocessing.Queue()
        self.num_workers = num_workers
        self.workers = []
        self.stop_event = multiprocessing.Event()
        self.lock = multiprocessing.Lock()  # For thread-safe file writing
        self.client_proc = None  # Renamed to avoid conflict

    def start_collection(self, duration_seconds=None, post_limit=None):
        """Start collecting posts from the firehose"""
        print(f"Starting collection{f' for {post_limit} posts' if post_limit else ''}...")
        self.start_time = time.time()
        end_time = self.start_time + duration_seconds if duration_seconds else None

        # Start worker processes
        for _ in range(self.num_workers):
            p = multiprocessing.Process(
                target=worker_process,
                args=(
                    self.queue, 
                    self.output_file, 
                    self.verbose, 
                    self.post_count, 
                    self.lock, 
                    self.stop_event
                )
            )
            p.start()
            self.workers.append(p)


        # Handle KeyboardInterrupt in the main process
        def signal_handler(sig, frame):
            print("\nCollection stopped by user.")
            self._stop_collection()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)

        while True:
            # Start the client in a separate process
            self.client_proc = multiprocessing.Process(
                target=client_process,
                args=(self.queue, self.stop_event)
            )
            self.client_proc.start()

            # Monitor the collection
            try:
                while True:
                    if self.stop_event.is_set():
                        break
                    if duration_seconds and time.time() > end_time:
                        print("\nTime limit reached.")
                        self._stop_collection()
                        break
                    elif post_limit and self.post_count.value >= post_limit:
                        print("\nPost limit reached.")
                        self._stop_collection()
                        break
                    if not self.client_proc.is_alive():
                        if not self.stop_event.is_set():
                            # Client process exited unexpectedly
                            print("\nClient process exited unexpectedly.")
                            self._stop_collection()

                            break
                        else:
                            # Stop event is set; exit the loop
                            break
                    time.sleep(1)
                else:
                    # If the collection completed successfully, break out of the retry loop
                    break
                if self.stop_event.is_set():
                    break
            except KeyboardInterrupt:
                print("\nCollection interrupted by user.")
                self._stop_collection()
                break
            except Exception as e:
                error_details = f"{type(e).__name__}: {str(e)}" if str(e) else f"{type(e).__name__}"
                print(f"\nConnection error: {error_details}")

        self._stop_collection()

    def _stop_collection(self):
        """Stop the collection and print summary"""
        if not self.stop_event.is_set():
            self.stop_event.set()

        if self.client_proc and self.client_proc.is_alive():
            self.client_proc.terminate()
            self.client_proc.join()

        # Wait for all worker processes to finish
        for p in self.workers:
            if p.is_alive():
                p.terminate()
            p.join()

        elapsed = time.time() - self.start_time if self.start_time else 0
        rate = self.post_count.value / elapsed if elapsed > 0 else 0
        print("\nCollection complete!")
        print(f"Collected {self.post_count.value} posts in {elapsed:.2f} seconds")
        print(f"Average rate: {rate:.1f} posts/sec")
        print(f"Output saved to: {self.output_file}")

if __name__ == "__main__":
    output_file = "bluesky_posts.csv"  # Save to CSV instead of JSONL
    verbose = True
    num_workers = 4

    archiver = FirehoseScraper(output_file=output_file, verbose=verbose, num_workers=num_workers)
    
    # Collect exactly 10 posts
    archiver.start_collection(post_limit=100)

