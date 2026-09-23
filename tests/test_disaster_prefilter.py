"""The cheap gate may add work but must never discard a supported rule match."""

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'proj-dev/app/live_demo'))
AVAILABLE = all(importlib.util.find_spec(name) for name in ('spacy', 'spacytextblob'))


@unittest.skipUnless(AVAILABLE, 'requires live NLP dependencies')
class DisasterPrefilterTests(unittest.TestCase):
    def setUp(self):
        import spacy
        import entity_extraction
        self.extractor = entity_extraction
        self.nlp = spacy.blank('en')
        self.ruler = self.nlp.add_pipe('entity_ruler')
        self.ruler.add_patterns([
            {'label': 'DISASTER', 'id': 'Flood', 'pattern': [{'TEXT': {'REGEX': '(?i)^floods?$'}}]},
            {'label': 'DISASTER', 'id': 'Tsunami', 'pattern': [
                {'TEXT': {'REGEX': '(?i)^tidals?$'}}, {'TEXT': {'REGEX': '(?i)^waves?$'}}]},
        ])
        self.nlp.add_pipe('ner').add_label('GPE')
        self.patcher = patch.object(self.extractor, 'load_nlp', return_value=self.nlp)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(self.extractor.surface_disaster_ruler.cache_clear)

    def test_keeps_case_plurals_multiword_hashtags_and_metaphors(self):
        for text in ('Flood in Austin', 'FLOODS in Austin', '#Flood in Austin',
                     '#TidalWaves reported nearby', 'A flood of compliments in Portland'):
            with self.subTest(text=text):
                self.assertTrue(self.extractor.has_disaster_candidate(text))

    def test_does_not_broaden_the_notebooks_known_rule_limits(self):
        for text in ('Hello Austin', 'Flooding in Austin', 'aflood', 'floodplain'):
            with self.subTest(text=text):
                self.assertFalse(self.extractor.has_disaster_candidate(text))

    def test_sentence_boundaries_cannot_merge_places_or_multiword_disasters(self):
        self.assertEqual(self.extractor.clean_text('Flood in Portland. Streets underwater!'),
                         'Flood in Portland. Streets underwater!')
        self.assertFalse(self.extractor.has_disaster_candidate('Tidal. Waves at the beach.'))

    def test_trained_disaster_label_disables_shortcut(self):
        self.nlp.get_pipe('ner').add_label('DISASTER')
        self.assertTrue(self.extractor.has_disaster_candidate('Novel wording'))

    def test_annotation_dependent_patterns_disable_shortcut(self):
        self.ruler.add_patterns([{'label': 'DISASTER', 'pattern': [{'LEMMA': 'flood'}]}])
        self.assertTrue(self.extractor.has_disaster_candidate('Novel wording'))

    def test_unknown_component_or_missing_ruler_disables_shortcut(self):
        self.nlp.add_pipe('sentencizer')
        self.assertTrue(self.extractor.has_disaster_candidate('Novel wording'))
        self.extractor.surface_disaster_ruler.cache_clear()
        self.nlp.remove_pipe('entity_ruler')
        self.assertTrue(self.extractor.has_disaster_candidate('Novel wording'))


if __name__ == '__main__':
    unittest.main()
