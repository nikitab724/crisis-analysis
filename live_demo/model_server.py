from crisis_or_not import CrisisOrNot
from crisis_type import CrisisType
from sentiment_analysis import SentimentAnalysis
from flask import Flask, request, jsonify

crisisModel = CrisisOrNot('./saved_model_4')
sentimentModel = SentimentAnalysis()
crisisTypeModel = CrisisType('./disaster_type_model')
app = Flask(__name__)

@app.route('/predict_crisis', methods=['POST'])
def predict_crisis():
    data = request.json
    text = data.get('text', '')
    crisis_prediction = crisisModel.predict(text)
    response = {
        'crisis_prediction': crisis_prediction
    }
    return jsonify(response)

@app.route('/predict_sentiment', methods=['POST'])
def predict_sentiment():
    data = request.json
    text = data.get('text', '')
    sentiment_prediction = sentimentModel.getSentiment(text)
    response = {
        'sentiment_prediction': sentiment_prediction
    }
    return jsonify(response)

@app.route('/predict_crisis_type', methods=['POST'])
def predict_crisis_type():
    data = request.json
    text = data.get('text', '')
    crisis_type_prediction = crisisTypeModel.getCrisisType(text)
    response = {
        'crisis_type_prediction': crisis_type_prediction
    }
    return jsonify(response)

if __name__ == '__main__':
    app.run()