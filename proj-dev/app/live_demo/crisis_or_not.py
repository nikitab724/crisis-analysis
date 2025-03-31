import pandas as pd
from transformers import BertTokenizer, BertForSequenceClassification
import torch

class CrisisOrNot:
    def __init__(self, model_path):
        self.tokenizer = BertTokenizer.from_pretrained(model_path)
        self.model = BertForSequenceClassification.from_pretrained(model_path)
        self.device = torch.device('cuda') if torch.cuda.is_available() else torch.device('cpu')
        self.model.to(self.device)
        print(f"Using device: {self.device}")

    def predict(self, text):
        inputs = self.tokenizer(text, return_tensors='pt', truncation=True, padding=True, max_length=512)
        inputs = {key: value.to(self.device) for key, value in inputs.items()}  
        with torch.no_grad():
            outputs = self.model(**inputs)
        logits = outputs.logits
        predicted_class = torch.argmax(logits, dim=1).item()
        return 'Crisis' if predicted_class == 1 else 'Not Crisis'
    
if __name__ == '__main__':
    model_name = './saved_model_4'
    crisis_model = CrisisOrNot(model_name)
    test_df = pd.read_csv('train.csv')
    test_df['prediction'] = test_df['text'].apply(crisis_model.predict)
    true_labels = test_df['target'].tolist()
    predicted_labels = test_df['prediction'].apply(lambda x: 1 if x == 'Crisis' else 0).tolist()
    accuracy = sum(1 for true, pred in zip(true_labels, predicted_labels) if true == pred) / len(true_labels)
    print(f"Accuracy: {accuracy:.2f}")  
    

