#!/usr/bin/env python3

import pandas as pd
import os

def create_test_crisis_counts():
    """Create a test crisis_counts.csv file with properly formatted data."""
    
    # Sample crisis data
    crisis_data = [
        {'country': 'US', 'state': 'California', 'disasters': 'Hurricane', 'count': 10, 
         'avg_sentiment': -0.01, 'cities': ['Santa Fe', 'San Mateo'], 'severity': -0.111},
        {'country': 'US', 'state': 'Texas', 'disasters': 'Flood', 'count': 5, 
         'avg_sentiment': -0.15, 'cities': ['Houston', 'Dallas'], 'severity': 0.5},
        {'country': 'US', 'state': 'Florida', 'disasters': 'Hurricane', 'count': 15, 
         'avg_sentiment': -0.2, 'cities': ['Miami', 'Tampa', 'Orlando'], 'severity': 1.2},
        {'country': 'US', 'state': 'New York', 'disasters': 'Snowstorm', 'count': 7, 
         'avg_sentiment': -0.05, 'cities': ['New York', 'Buffalo'], 'severity': 0.3},
        {'country': 'US', 'state': 'Washington', 'disasters': 'Wildfire', 'count': 8, 
         'avg_sentiment': -0.18, 'cities': ['Seattle', 'Spokane'], 'severity': 0.7},
        {'country': 'US', 'state': 'Kansas', 'disasters': 'Tornado', 'count': 12, 
         'avg_sentiment': -0.25, 'cities': ['Wichita', 'Topeka'], 'severity': 1.5},
        {'country': 'US', 'state': 'Ohio', 'disasters': 'War', 'count': 3, 
         'avg_sentiment': 0.08, 'cities': ['Cleveland', 'Columbus'], 'severity': -0.1}
    ]
    
    # Create DataFrame
    df = pd.DataFrame(crisis_data)
    
    # Ensure cities column is properly formatted
    df['cities'] = df['cities'].apply(lambda x: str(x))
    
    # Save to CSV with quoting to handle commas in lists
    output_file = 'crisis_counts.csv'
    df.to_csv(output_file, index=False, quoting=1)  # quoting=1 means quote all non-numeric fields
    
    print(f"Created test crisis_counts.csv with {len(df)} rows")
    return output_file

if __name__ == "__main__":
    file = create_test_crisis_counts()
    print(f"Test data saved to {file}")
    print("You can now run the dash app to visualize this test data") 