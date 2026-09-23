import re
from functools import lru_cache
from pathlib import Path
from threading import RLock

import spacy
from spacytextblob.spacytextblob import SpacyTextBlob  # noqa: F401 - registers the saved pipeline component

# Share one transformer safely while HTTP/location lookups overlap outside it.
NLP_LOCK = RLock()

pattern = re.compile(
    r"(?P<hashtag>\#[A-Za-z0-9_]+)"           # e.g. #RockIsland
    r"|(?P<mention>@[A-Za-z0-9_]+)"           # remove entire @-mention
    r"|(?P<url>\w+://\S+)"                    # remove entire url
    r"|(?P<remove>[^\w\s,])"                  # remove any other char that's not word char, whitespace, or comma
)

def split_camel_case(text: str) -> str:
    """
    Insert a space before an uppercase char that follows a lowercase char.
    e.g. 'RockIsland' -> 'Rock Island'
    """
    return re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', text)

def replace_func(match: re.Match) -> str:
    """
    - If hashtag is matched, split its camel case part and add a comma afterward.
    - If mention or url is matched, replace with space.
    - If remove is matched (any disallowed char), replace with a space.
    """
    if match.group('hashtag'):
        # Remove the '#' and split the remainder
        hashtag_text = match.group('hashtag')[1:]  # skip '#'
        splitted = split_camel_case(hashtag_text)
        return splitted + ","  # keep a trailing comma

    if match.group('mention') or match.group('url') or match.group('remove'):
        return " "

    # fallback
    return match.group(0)

def clean_text(text: str) -> str:
    """
    Cleans the text by:
    - Removing or transforming selected tokens (@mentions, URLs, certain punctuation)
    - Normalizing extra spaces.
    - Preserving commas and splitting camel case only in hashtags.
    """
    cleaned = pattern.sub(replace_func, text)
    # Normalize spaces
    return ' '.join(cleaned.split())

@lru_cache(maxsize=1)
def load_nlp():
    """Load the existing custom pipeline once, independent of working directory."""
    model_path = Path(__file__).resolve().parent.parent / "disaster_ner"
    if not model_path.is_dir():
        raise FileNotFoundError(
            f"Custom NLP model is missing: {model_path}. "
            "Restore disaster_ner or follow the model setup steps in README.md."
        )
    return spacy.load(model_path)


@lru_cache(maxsize=1)
def surface_disaster_ruler(nlp):
    """Only shortcut the notebook's surface rules, never a trained disaster label."""
    safe_factories = {'transformer', 'curated_transformer', 'tagger', 'parser', 'attribute_ruler', 'lemmatizer',
                      'entity_ruler', 'ner', 'spacytextblob'}
    if (not nlp.has_pipe('entity_ruler') or not nlp.has_pipe('ner')
            or 'DISASTER' in nlp.get_pipe('ner').labels
            or any(nlp.get_pipe_meta(name).factory not in safe_factories for name in nlp.pipe_names)):
        return None
    ruler = nlp.get_pipe('entity_ruler')
    patterns = ruler.patterns
    if not patterns or any(
        item.get('label') != 'DISASTER' or not isinstance(item.get('pattern'), list)
        or not item['pattern'] or any(set(token) != {'TEXT'} for token in item['pattern'])
        for item in patterns
    ):
        return None
    return ruler


def has_disaster_candidate(text):
    """Use identical cleaning/tokenization/rules before paying for the transformer.

    A match still requires the complete original pipeline and all later checks.
    Unknown model/rule shapes bypass this shortcut so they cannot lose candidates.
    """
    with NLP_LOCK:
        nlp = load_nlp()
        ruler = surface_disaster_ruler(nlp)
        return ruler is None or bool(ruler.matcher(nlp.make_doc(clean_text(text))))


def test_model(text):
    doc = load_nlp()(text)
    for ent in doc.ents:
        print(f"Entity lemma: {ent.lemma_.lower()} | Ent text: {ent.text} | Label: {ent.label_} | Canonical label: {ent.ent_id_}")
    print(f"Polarity: {doc._.blob.polarity}, Subjectivity: {doc._.blob.subjectivity}")

#extract entities and sentiment from tweet text

headers = ["Negative", "Neutral", "Positive"]
def extract_ent_sent(text):
    with NLP_LOCK:
        return _extract_ent_sent(text)


def _extract_ent_sent(text):
    doc = load_nlp()(clean_text(text))
    disasters = set()  # Use set to deduplicate identical disasters
    locations = set()  # Use set to deduplicate identical locations
    sentiment = headers[1]
    score = doc._.blob.polarity

    for ent in doc.ents:
        if ent.label_ == "DISASTER":
            disaster_id = ent.ent_id_ if ent.ent_id_ else ent.text
            disasters.add(disaster_id)  # Use add() for set
        elif ent.label_ in ["GPE", "LOC", "FAC"]:
            location = ent.text.strip("# ")
            if location.endswith("'s"):
                location = location[:-2]
            locations.add(location)  # Use add() for set


    if score >= 0.1:
        sentiment = headers[2]
    elif score < 0:
        sentiment = headers[0]
    else:
        sentiment = headers[1]

    return {"disasters": sorted(disasters), "locations": sorted(locations), "sentiment": sentiment, "polarity": score}
