from blueskyapi_copy import FirehoseScraper
from flask import Flask, request, jsonify
import pandas as pd


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
    
    # Create a post in the same format as the scraper
    test_post = {
        'text': text,
        'author': 'test_user',
        'created_at': pd.Timestamp.now().isoformat(),
        'tweet_id': f'test_{pd.Timestamp.now().timestamp()}'
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

