from nltk.sentiment.vader import SentimentIntensityAnalyzer

class SentimentAnalysis:
    def __init__(self):
        self.analyzer = SentimentIntensityAnalyzer()

    def getSentiment(self, text):
        scores = self.analyzer.polarity_scores(text)
        return scores['compound']
    
if __name__ == '__main__':
    sentiment_model = SentimentAnalysis()
    text = 'I love the weather today! #sunny'
    print(sentiment_model.getSentiment(text))





