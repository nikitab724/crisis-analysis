from atproto import FirehoseSubscribeReposClient, parse_subscribe_repos_message, CAR, IdResolver, DidInMemoryCache
import time
from datetime import datetime
import multiprocessing
import sys
import signal
import os
import json

def _save_post_data(post_data, posts_list, verbose, post_count, lock):
    """Save post data to a shared list with a unique post ID."""
    with lock:
        post_data['post_id'] = post_count.value + 1  # Assign post ID starting from 1
        posts_list.append(post_data)

    with post_count.get_lock():
        post_count.value += 1  # Increment the post counter

    if verbose:
        print(f"Saved post #{post_count.value} by @{post_data['author']}: {post_data['text'][:50]}...")

def worker_process(queue, posts_list, verbose, post_count, lock, stop_event, keyword):
    resolver = IdResolver(cache=DidInMemoryCache())
    while not stop_event.is_set():
        try:
            message = queue.get(timeout=1)
            process_message(message, resolver, posts_list, verbose, post_count, lock, keyword)
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

def process_message(message, resolver, posts_list, verbose, post_count, lock, keyword=None):
    """Process a single message from the firehose, filtering posts if a keyword is specified."""
    try:
        commit = parse_subscribe_repos_message(message)
        if not hasattr(commit, 'ops'):
            return

        for op in commit.ops:
            if op.action == 'create' and op.path.startswith('app.bsky.feed.post/'):
                _process_post(commit, op, resolver, posts_list, verbose, post_count, lock, keyword)

    except Exception as e:
        print(f"Error processing message: {e}")

def _process_post(commit, op, resolver, posts_list, verbose, post_count, lock, keyword=None):
    """Process a single post operation with optional keyword filtering."""
    try:
        author_handle = _resolve_author_handle(commit.repo, resolver)
        car = CAR.from_bytes(commit.blocks)
        for record in car.blocks.values():
            if isinstance(record, dict) and record.get('$type') == 'app.bsky.feed.post':
                post_data = _extract_post_data(record, commit.repo, op.path, author_handle)

                # Filter based on keyword (case-insensitive)
                if keyword and keyword.lower() not in post_data['text'].lower():
                    return  # Skip post if it doesn't contain the keyword

                _save_post_data(post_data, posts_list, verbose, post_count, lock)
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
    return {
        'text': record.get('text', ''),
        'created_at': record.get('createdAt', ''),
        'author': author_handle,
        'uri': f'at://{repo}/{path}',
    }

class FirehoseScraper:
    def __init__(self, verbose=False, num_workers=4, keyword=None):
        self.posts_list = multiprocessing.Manager().list()
        self.post_count = multiprocessing.Value('i', 0)
        self.start_time = None
        self.cache = DidInMemoryCache()
        self.resolver = IdResolver(cache=self.cache)
        self.verbose = verbose
        self.queue = multiprocessing.Queue()
        self.num_workers = num_workers
        self.workers = []
        self.stop_event = multiprocessing.Event()
        self.lock = multiprocessing.Lock()
        self.client_proc = None
        self.keyword = keyword  # Store keyword

    def start_collection(self, duration_seconds=None, post_limit=None):
        """Start collecting posts with optional filtering by keyword."""
        print(f"Starting collection{f' for {post_limit} posts' if post_limit else ''}...")
        if self.keyword:
            print(f"Filtering posts that contain the keyword: '{self.keyword}'")
        
        # Reset instance variables
        self.__init__(verbose=self.verbose, num_workers=self.num_workers, keyword=self.keyword)
        
        self.start_time = time.time()
        end_time = self.start_time + duration_seconds if duration_seconds else None

        # Start worker processes
        for _ in range(self.num_workers):
            p = multiprocessing.Process(
                target=worker_process,
                args=(self.queue, self.posts_list, self.verbose, self.post_count, self.lock, self.stop_event, self.keyword)
            )
            p.start()
            self.workers.append(p)

        # Start the client process
        self.client_proc = multiprocessing.Process(
            target=client_process,
            args=(self.queue, self.stop_event)
        )
        self.client_proc.start()

        # Monitor collection
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
                        print("\nClient process exited unexpectedly.")
                        self._stop_collection()
                    break
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nCollection interrupted by user.")
            self._stop_collection()

        self._stop_collection()
        return list(self.posts_list)

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

if __name__ == "__main__":
    verbose = True
    num_workers = 4
    keyword = input("Enter a keyword to filter posts (leave blank for all posts): ").strip() or None
    archiver = FirehoseScraper(verbose=verbose, num_workers=num_workers, keyword=keyword)
    posts = archiver.start_collection(post_limit=25)
    print(f"Collected {len(posts)} posts.")
    print('---------------------------------------')
    posts = archiver.start_collection(post_limit=25)
    print(f"Collected {len(posts)} posts.")
