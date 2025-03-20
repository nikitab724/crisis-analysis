from blueskyapi_copy import FirehoseScraper
from flask import Flask, request, jsonify


app = Flask(__name__)

@app.route('/scrape_posts', methods=['POST'])
def scrape_posts():
    data = request.json
    post_limit = data.get('post_limit', 50)
    posts = archiver.start_collection(post_limit=post_limit)
    return jsonify({'posts': posts})

if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    
    verbose = True
    num_workers = 4
    keyword = None
    archiver = FirehoseScraper()

    app.run(port=5001)

