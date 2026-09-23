"""Bounded public reply/link context; never use profiles as incident locations."""
from functools import lru_cache
import re
import threading

import requests

POST_URI = re.compile(r'^at://[^/\s?#]{1,256}/app\.bsky\.feed\.post/[A-Za-z0-9._~:-]{1,128}$')
PUBLIC_POSTS = 'https://public.api.bsky.app/xrpc/app.bsky.feed.getPosts'
_http = threading.local()


def text_value(value, limit=3000):
    return value[:limit] if isinstance(value, str) else ''


def record_metadata(record):
    def mapping(value):
        return value if isinstance(value, dict) else {}
    reply = mapping(record.get('reply'))
    embed = mapping(record.get('embed'))
    if embed.get('$type') == 'app.bsky.embed.recordWithMedia':
        embed = mapping(embed.get('media'))
    external = mapping(embed.get('external')) if embed.get('$type') == 'app.bsky.embed.external' else {}
    return {
        'reply_parent_uri': text_value(mapping(reply.get('parent')).get('uri'), 512),
        'reply_root_uri': text_value(mapping(reply.get('root')).get('uri'), 512),
        'link_title': text_value(external.get('title'), 500),
        'link_description': text_value(external.get('description'), 1000),
    }


def candidate_text(row):
    parts = (text_value(row.get(key)) for key in ('text', 'link_title', 'link_description'))
    return ' '.join(part for part in parts if part)


@lru_cache(maxsize=1024)
def fetch_public_posts(uris):
    if not hasattr(_http, 'session'):
        _http.session = requests.Session()
        _http.session.trust_env = False
    response = _http.session.get(PUBLIC_POSTS, params=[('uris', uri) for uri in uris],
                                 timeout=(3, 5), allow_redirects=False)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get('posts'), list):
        raise ValueError('Invalid public post context response')
    # Deleted, blocked, and unavailable records are never fabricated.
    found = {item['uri']: item for item in data['posts'] if isinstance(item, dict) and item.get('uri') in uris}
    return tuple(found[uri] for uri in uris if uri in found)


def context_for_post(row):
    context = []
    title, description = (text_value(row.get(key), limit) for key, limit in
                          [('link_title', 500), ('link_description', 1000)])
    if title or description:
        context.append({'kind': 'attached_headline', 'text': title + '. ' + description})
    uris = tuple(dict.fromkeys(uri for key in ('reply_parent_uri', 'reply_root_uri')
                             if POST_URI.fullmatch(uri := text_value(row.get(key), 512))))
    if uris:
        for post in fetch_public_posts(uris):
            record = post.get('record') or {}
            metadata = record_metadata(record)
            context.append({'kind': 'reply_context', 'uri': post['uri'],
                            'same_author': (post.get('author') or {}).get('did') == row.get('author'),
                            'published_at': text_value(record.get('createdAt'), 64),
                            'text': text_value(record.get('text'), 2000),
                            'link_title': metadata['link_title'],
                            'link_description': metadata['link_description']})
    return context


def extraction_text(text, context):
    """Keep sentence boundaries between different posts and their link cards."""
    parts = [text]
    for item in context:
        parts.extend(item.get(key, '') for key in ('text', 'link_title', 'link_description'))
    return '.\n'.join(part for part in parts if part)[:10000]
