import tensorflow as tf
from transformers import AutoTokenizer, TFAutoModelForSequenceClassification

class CrisisType:
    def __init__(self, model_path):
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        self.model = TFAutoModelForSequenceClassification.from_pretrained(model_path)
        self.labels = {
            0: "haze",
            1: "disease",
            2: "earthquake",
            3: "flood",
            4: "hurricane & tornado",
            5: "wildfire",
            6: "industrial accident",
            7: "societal crime",
            8: "transportation accident",
            9: "meteor crash"
        }
    
    def getCrisisType(self, text):
        inputs = self.tokenizer(text, return_tensors="tf")
        outputs = self.model(**inputs)
        predicted_class = tf.argmax(outputs.logits, axis=1).numpy()[0]
        return self.labels[predicted_class]

# import spacy

# class CrisisType:
#     def __init__(self, model_path):
#         self.nlp = spacy.load(model_path)
    
#     def getCrisisType(self, text):
#         doc = self.nlp(text)
#         for ent in doc.ents:
#             if ent.label_ == 'DISASTER':
#                 return ent.lemma_.lower() 
#         return None



