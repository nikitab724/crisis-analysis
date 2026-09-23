"""Compare the rule gate with the unchanged real NLP pipeline; no provider calls."""

import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'proj-dev/app/live_demo'))
from entity_extraction import extract_ent_sent, has_disaster_candidate, load_nlp, surface_disaster_ruler  # noqa: E402

NEGATIVES = [
    'A quiet afternoon in Austin Texas.', 'New coffee shop opening in Portland.',
    'Watching a movie with friends tonight.', 'The bus to Chicago is running late.',
    'Beautiful blue skies above Dallas today.', 'I love the new album.',
    'Working on homework at the library.', 'Looking forward to the weekend in Maine.',
    'Checking baseball scores in New York.', 'Taking my dog for a walk by the river.',
    'The latest update fixed my computer.', 'Lunch with the team was great.',
    'A long drive from Seattle to Portland.', 'Reading a book about city design.',
    'Sharing pictures of flowers from the park.', 'Bought a new pair of running shoes.',
    'Meeting moved to tomorrow morning.', 'Austin fans are discussing the new concert.',
    'Can anyone recommend a good restaurant?', 'Sunset looked amazing over the lake.',
]


def main():
    nlp = load_nlp()
    ruler = surface_disaster_ruler(nlp)
    assert ruler is not None, 'Loaded model does not qualify for the safe shortcut'
    positives = []
    for rule in ruler.patterns:
        words = []
        for token in rule['pattern']:
            regex = token['TEXT']['REGEX']
            assert regex.startswith('(?i)^') and regex.endswith('s?$')
            words.append(regex[len('(?i)^'):-len('s?$')])
        phrase = ' '.join(words)
        positives.extend([phrase+' in Austin, Texas.', phrase.upper()+' in Austin, Texas.',
                          phrase+'s in Austin, Texas.'])
    baseline_times, gate_times, original_nonmatches = [], [], []
    for text in positives + NEGATIVES:
        started = time.perf_counter()
        original = extract_ent_sent(text)
        elapsed = (time.perf_counter() - started)*1000
        started = time.perf_counter()
        candidate = has_disaster_candidate(text)
        gate_elapsed = (time.perf_counter() - started)*1000
        assert candidate or not original['disasters'], f'Gate dropped an original candidate: {text}'
        if text in NEGATIVES:
            assert not original['disasters'] and not candidate
            baseline_times.append(elapsed)
            gate_times.append(gate_elapsed)
        else:
            if not original['disasters']:
                original_nonmatches.append(text)  # Existing cleaning/rule limitations are preserved.
            if candidate:
                assert extract_ent_sent(text) == original, 'Candidate output changed'
    report = {'rules': len(ruler.patterns), 'positive_probes': len(positives),
              'negative_probes': len(NEGATIVES), 'dropped_original_candidates': 0,
              'original_nonmatching_rule_probes': original_nonmatches,
              'noncandidate_baseline_median_ms': round(statistics.median(baseline_times), 3),
              'noncandidate_gate_median_ms': round(statistics.median(gate_times), 3),
              'synthetic_examples_only': True}
    output = ROOT / '.demo-hosted/prefilter-benchmark.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))
    print('PASS: every loaded rule, case/plural probes, and original candidate outputs preserved.')


if __name__ == '__main__':
    main()
