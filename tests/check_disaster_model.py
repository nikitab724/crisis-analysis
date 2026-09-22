"""Integration check: requires the real model built by build_disaster_model.py."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proj-dev/app/live_demo"))
from entity_extraction import clean_text, extract_ent_sent, load_nlp  # noqa: E402

text = "Flood in Austin Texas."
nlp = load_nlp()
doc = nlp(clean_text(text))
entities = [(entity.text, entity.label_, entity.ent_id_) for entity in doc.ents]
result = extract_ent_sent(text)
print("Entities:", entities)
print("Extraction:", result)
assert any(label == "DISASTER" and canonical == "Flood" for _, label, canonical in entities), entities
assert "Flood" in result["disasters"], result
assert {"Austin", "Texas"}.issubset(result["locations"]), result
assert all(any(name == place and label == "GPE" for name, label, _ in entities) for place in ("Austin", "Texas"))
assert "entity_ruler" in nlp.pipe_names and "spacytextblob" in nlp.pipe_names
print("PASS: real saved pipeline detects Flood (DISASTER), Austin (GPE), and Texas (GPE).")
