from flask import Flask, request, jsonify
import asyncio
from atproto import AsyncFirehoseSubscribeReposClient, AsyncIdResolver, AsyncDidInMemoryCache, parse_subscribe_repos_message, CAR
import time

app = Flask(__name__)

async def process_post(commit, op, resolver):
    """Process a single post from the Firehose."""
    try:
        car = CAR.from_bytes(commit.blocks)
        for record in car.blocks.values():
            if isinstance(record, dict) and record.get('$type') == 'app.bsky.feed.post':
                post_data = {
                    'text': record.get('text', ''),
                    'created_at': record.get('createdAt', ''),
                    'author': await resolve_author_handle(commit.repo, resolver),
                    'uri': f'at://{commit.repo}/{op.path}',
                }
                return post_data
    except Exception as e:
        print(f"Error processing post: {e}")
        return

async def resolve_author_handle(repo, resolver):
    """Resolve the author handle from the DID."""
    try:
        resolved_info = await resolver.did.resolve(repo)
        return resolved_info.also_known_as[0].split('at://')[1] if resolved_info.also_known_as else repo
    except Exception as e:
        print(f"Could not resolve handle for {repo}: {e}")
        return repo  # Fallback to DID

async def listen_firehose(client: AsyncFirehoseSubscribeReposClient, 
                          resolver: AsyncIdResolver, 
                          post_limit=50,
                          post_list:list=[]):
    """Listen to the Firehose and process each received post."""

    async def message_handler(message):
        nonlocal post_list

        commit = parse_subscribe_repos_message(message)
        if not hasattr(commit, 'ops'):
            return

        for op in commit.ops:
            if op.action == 'create' and op.path.startswith('app.bsky.feed.post/'):
                post = await process_post(commit, op, resolver)
                if post:
                    post_list.append(post)
                if len(post_list) >= post_limit:
                    await client.stop()
                    return

    try:
        await client.start(message_handler)
    except Exception as e:
        print(f"Error listening to Firehose: {e}")

class FirehoseAPI:
    def __init__(self):
        self.client = AsyncFirehoseSubscribeReposClient()
        self.resolver = AsyncIdResolver(cache=AsyncDidInMemoryCache())
    
    async def fetch_posts(self, post_limit):
        self.client = AsyncFirehoseSubscribeReposClient()
        post_list = []
        await listen_firehose(self.client, self.resolver, post_limit, post_list)
        return post_list
        
scraper = FirehoseAPI()
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

@app.route("/scrape", methods=["GET"])
def scrape():
    try:
        post_limit = int(request.args.get("limit", 50))  # Default to 50 posts
        startTime = time.time()
        posts = loop.run_until_complete(scraper.fetch_posts(post_limit))
        elapsedTime = time.time() - startTime
        print(f'Scraped {post_limit} posts in {elapsedTime:.2f}s')
        return jsonify({"posts": posts})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/test_tweet', methods=['POST'])
def test_tweet():
    data = request.json
    text = data.get('text', '')

    # Create a test post in the same format as Firehose yields
    test_post = {
        'text': text,
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'author': 'test_user.bsky.social',
        'uri': f'at://did:plc:test/{int(time.time())}'
    }

    return jsonify({'posts': [test_post]})

if __name__ == "__main__":
    app.run(port=5001)
