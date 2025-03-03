import torch
from transformers import BertTokenizer, BertForSequenceClassification
import re

# Load the BERT model and tokenizer
model_path = './saved_model_2'
tokenizer = BertTokenizer.from_pretrained(model_path)
model = BertForSequenceClassification.from_pretrained(model_path)

def preprocess_text(text):
    text = re.sub(r'http\S+', '', text)  # Remove links
    text = re.sub(r'#\w+', '', text)  # Remove hashtags
    text = re.sub(r'@\w+', '', text)  # Remove mentions
    text = re.sub(r'[^\w\s]', '', text)  # Remove punctuation
    text = text.lower()  # Convert to lowercase
    return text

def predict(text):
    # Tokenize the input text
    inputs = tokenizer(preprocess_text(text), return_tensors='pt', truncation=True, padding=True, max_length=512)
    
    # Get the model's prediction
    with torch.no_grad():
        outputs = model(**inputs)
    
    # Get the predicted class
    logits = outputs.logits
    predicted_class = torch.argmax(logits, dim=1).item()
    
    return 'Crisis' if predicted_class == 1 else 'Not Crisis'

# Example usage
if __name__ == "__main__":
    text = "abcdefg"
    prediction = predict(text)
    print(f"{'Text:':<30} {'Prediction:':<15}")
    print(f"{text:<30} {prediction:<15}")