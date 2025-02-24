import pandas as pd

# Parameter to determine how many lines of text to test from the test.csv file
num_lines = 15
from transformers import BertTokenizer, BertForSequenceClassification
import torch

# Load the pre-trained BERT model and tokenizer
# Change the path to the location of the saved model on your machine
model_name = r'C:/Users/eyeba/Documents/Code/Test/saved_model'
tokenizer = BertTokenizer.from_pretrained(model_name)
model = BertForSequenceClassification.from_pretrained(model_name)

# Load the test data
test_data = pd.read_csv('test.csv', nrows=num_lines)

# Function to predict if a text involves a crisis
def predict_crisis(text):
    inputs = tokenizer(text, return_tensors='pt', truncation=True, padding=True, max_length=512)
    outputs = model(**inputs)
    logits = outputs.logits
    prediction = torch.argmax(logits, dim=1).item()
    return 'Crisis' if prediction == 1 else 'Not Crisis'

# Apply the function to the text column
test_data['Crisis'] = test_data['text'].apply(predict_crisis)

# Display the results
print(test_data[['text', 'Crisis']])