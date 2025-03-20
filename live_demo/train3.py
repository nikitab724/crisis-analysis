import pandas as pd
import torch
from preprocess_text import preprocess_text
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
from transformers import BertTokenizer, BertForSequenceClassification, Trainer, TrainingArguments
from transformers import DataCollatorWithPadding
from datasets import Dataset
from sklearn.metrics import precision_score, recall_score, f1_score

# Load dataset
df = pd.read_csv('train.csv')
df['text'] = df['text'].apply(preprocess_text)

# Split dataset
train_texts, val_texts, train_labels, val_labels = train_test_split(df['text'], df['target'], test_size=0.2)

# Load tokenizer
tokenizer = BertTokenizer.from_pretrained('bert-base-uncased')

# Tokenize dataset
train_encodings = tokenizer(train_texts.tolist(), truncation=True, padding=True)
val_encodings = tokenizer(val_texts.tolist(), truncation=True, padding=True)

# Create torch dataset
class TweetDataset(torch.utils.data.Dataset):
    def __init__(self, encodings, labels):
        self.encodings = encodings
        self.labels = labels

    def __getitem__(self, idx):
        item = {key: torch.tensor(val[idx]) for key, val in self.encodings.items()}
        item['labels'] = torch.tensor(self.labels[idx])
        return item

    def __len__(self):
        return len(self.labels)

train_dataset = TweetDataset(train_encodings, train_labels.tolist())
val_dataset = TweetDataset(val_encodings, val_labels.tolist())

# Load model
model = BertForSequenceClassification.from_pretrained('bert-base-uncased', num_labels=2)

# Training arguments
training_args = TrainingArguments(
    output_dir='./results',
    num_train_epochs=5,
    per_device_train_batch_size=16,
    per_device_eval_batch_size=16,
    warmup_steps=500,
    weight_decay=0.01,
    logging_dir='./logs',
    logging_steps=10,
    evaluation_strategy="epoch",
    save_strategy="epoch",
    load_best_model_at_end=True,
)

# Data collator
data_collator = DataCollatorWithPadding(tokenizer)

# Trainer
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    eval_dataset=val_dataset,
    data_collator=data_collator,
    tokenizer=tokenizer,
)

# Use CUDA acceleration if available
device = torch.device('cuda') if torch.cuda.is_available() else torch.device('cpu')
model.to(device)
print(f"Using device: {device}")

# Train model
trainer.train()

# Save model
model.save_pretrained('./saved_model_4')
tokenizer.save_pretrained('./saved_model_4')

# Evaluate model
predictions = trainer.predict(val_dataset)
preds = predictions.predictions.argmax(-1)
precision = precision_score(val_labels, preds)
recall = recall_score(val_labels, preds)
f1 = f1_score(val_labels, preds)
accuracy = accuracy_score(val_labels, preds)
print(f'Validation Precision: {precision}')
print(f'Validation Recall   : {recall}')
print(f'Validation F1 Score : {f1}')
print(f'Validation Accuracy : {accuracy}')