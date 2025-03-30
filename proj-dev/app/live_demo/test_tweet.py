#!/usr/bin/env python3

import requests
import argparse
import sys

def send_test_tweet(text):
    """Send a test tweet to the scraper server and output the result."""
    try:
        response = requests.post(
            'http://127.0.0.1:5001/test_tweet',
            json={'text': text}
        )
        response.raise_for_status()  # Raise an exception for HTTP errors
        result = response.json()
        print("Test tweet sent successfully!")
        print(f"Text: {text}")
        print("\nTweet will be processed through the normal pipeline.")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error sending test tweet: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Send test tweets to the disaster monitoring system")
    parser.add_argument("text", nargs="?", help="The tweet text to send")
    
    args = parser.parse_args()
    
    if args.text:
        # Text provided as command line argument
        send_test_tweet(args.text)
    else:
        # Interactive mode
        print("Disaster Monitoring System - Test Tweet Sender")
        print("Enter 'exit' or 'quit' to end the program\n")
        
        while True:
            text = input("Enter tweet text: ")
            if text.lower() in ['exit', 'quit']:
                break
                
            if text.strip():
                send_test_tweet(text)
                print()  # Empty line for readability
            else:
                print("Please enter some text for the tweet.\n")

if __name__ == "__main__":
    main()
