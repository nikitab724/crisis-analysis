#!/usr/bin/env python3
"""Reproduce the pipeline-building cell from dataset_test.ipynb."""

import json
from pathlib import Path

import spacy
from spacytextblob.spacytextblob import SpacyTextBlob  # noqa: F401 - registers the pipeline factory

ROOT = Path(__file__).resolve().parent
DISASTER_TYPES = ROOT / "proj-dev/data/disasters/disaster_types.json"
MODEL_PATH = ROOT / "proj-dev/app/disaster_ner"


def create_training_data(nlp, file=DISASTER_TYPES):
    """Preserve the notebook's lemma-derived, optional-plural regex patterns."""
    with Path(file).open(encoding="utf-8") as source:
        disasters = json.load(source)["disasters"]

    patterns = []
    for label, synonyms in disasters.items():
        for synonym in synonyms:
            doc = nlp(synonym)
            pattern_tokens = []
            for token in doc:
                lemma = token.lemma_.lower()
                pattern_tokens.append({"TEXT": {"REGEX": fr"(?i)^{lemma}s?$"}})
            patterns.append({"label": "DISASTER", "pattern": pattern_tokens, "id": label})
    return patterns


def build_model():
    nlp = spacy.load("en_core_web_trf")
    patterns = create_training_data(nlp)
    if "entity_ruler" in nlp.pipe_names:
        nlp.remove_pipe("entity_ruler")
    ruler = nlp.add_pipe("entity_ruler", before="ner")
    ruler.add_patterns(patterns)
    nlp.add_pipe("spacytextblob")
    nlp.to_disk(MODEL_PATH)
    print(f"Saved {len(ruler.patterns)} disaster patterns and {nlp.pipe_names} to {MODEL_PATH}")


if __name__ == "__main__":
    build_model()
