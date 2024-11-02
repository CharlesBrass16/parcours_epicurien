from pymongo import MongoClient
from neo4j import GraphDatabase
import pandas as pd

def load_to_mongo():
    client = MongoClient("mongodb://localhost:27017")
    db = client['velo_epicurien']
    collection = db['restaurants']

    restaurants = pd.read_csv("data/restaurants_paris_cleaned.csv").to_dict(orient="records")
    collection.insert_many(restaurants)
    print("Données de restaurants chargées dans MongoDB.")

def load_to_neo4j():
    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
    cycleways = pd.read_csv("data/cycleways_paris_cleaned.csv")

    with driver.session() as session:
        for _, row in cycleways.iterrows():
            coordinates = eval(row['coordinates'])
            for i in range(len(coordinates) - 1):
                start = coordinates[i]
                end = coordinates[i + 1]
                session.run(
                    """
                    MERGE (a:Location {latitude: $start_lat, longitude: $start_lng})
                    MERGE (b:Location {latitude: $end_lat, longitude: $end_lng})
                    MERGE (a)-[:CYCLEWAY]->(b)
                    """,
                    start_lat=start[1], start_lng=start[0], end_lat=end[1], end_lng=end[0]
                )
    print("Données de pistes cyclables chargées dans Neo4j.")

if __name__ == "__main__":
    load_to_mongo()
    load_to_neo4j()
