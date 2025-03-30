from blueskyapi_copy import FirehoseScraper
from flask import Flask, request, jsonify
import datetime
import uuid


app = Flask(__name__)

@app.route('/scrape_posts', methods=['POST'])
def scrape_posts():
    data = request.json
    post_limit = data.get('post_limit', 50)
    posts = archiver.start_collection(post_limit=post_limit)
    return jsonify({'posts': posts})

@app.route('/test_tweet', methods=['POST'])
def test_tweet():
    data = request.json
    text = data.get('text', '')
    
    # Create a test post in the exact same format as the real posts
    test_post = {
        'text': text,
        'created_at': datetime.datetime.now().isoformat(),
        'author': 'test_user.bsky.social',
        'uri': f'at://did:plc:test/{uuid.uuid4()}'
    }
    
    # Return in the same format as scrape_posts
    return jsonify({'posts': [test_post]})

if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    
    verbose = True
    num_workers = 4
    keyword = None
    archiver = FirehoseScraper()

    app.run(port=5001)

