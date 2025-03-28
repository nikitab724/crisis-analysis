import re
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer

stop_words = set(stopwords.words('english'))

def preprocess_text(text):
    text = re.sub(r'http\S+', '', text)  # Remove links
    text = re.sub(r'#', '', text)  # Remove hashtag symbol but keep the word
    text = re.sub(r'@\w+', '', text)  # Remove mentions
    text = re.sub(r'[^\w\s]', '', text)  # Remove punctuation
    words = text.lower().split()  # Convert to lowercase
    words = [word for word in words if word not in stop_words]  # Remove stopwords
    lemmatizer = WordNetLemmatizer()
    lemmatized_words = [lemmatizer.lemmatize(word) for word in words] # Lemmatize words
    text = ' '.join(lemmatized_words)
    return text

# Example usage
if __name__ == "__main__":
    text = "I love the weather today! #sunny"
    print(preprocess_text(text))  # Output: love weather today sunny
    text = "I can't believe it's raining again! #rain"
    print(preprocess_text(text))  # Output: cant believe raining rain