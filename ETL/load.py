import time
from pymongo import MongoClient
from neo4j import GraphDatabase
import pandas as pd
import os
from neo4j.exceptions import ServiceUnavailable

def wait_for_neo4j(driver, timeout=60):
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with driver.session() as session:
                session.run("RETURN 1")
            print("Neo4j est prêt.")
            return True
        except ServiceUnavailable:
            print("En attente de Neo4j...")
            time.sleep(5)
    raise Exception("Neo4j n'est pas disponible après un délai d'attente.")

def load_to_mongo():
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/velo_epicurien")
    client = MongoClient(mongo_uri)
    db = client['velo_epicurien']
    collection = db['restaurants']

    # Vider la collection avant de charger de nouvelles données
    collection.delete_many({})

    # Charger les restaurants
    restaurants = pd.read_csv("data/restaurants_paris_cleaned.csv").to_dict(orient="records")
    collection.insert_many(restaurants)
    print("Données de restaurants chargées dans MongoDB.")


def load_to_neo4j():
    driver = GraphDatabase.driver("bolt://neo4j:7687", auth=("neo4j", "password"))
    # Attendre que Neo4j soit disponible
    wait_for_neo4j(driver)
    cycleways = pd.read_csv("data/cycleways_paris_cleaned.csv")
    restaurants = pd.read_csv("data/restaurants_paris_cleaned.csv")

    with driver.session() as session:
        # Vider la base de données Neo4j avant de charger de nouvelles données
        session.run("MATCH (n) DETACH DELETE n")
        print("Base de données Neo4j vidée.")

        # Charger les pistes cyclables dans Neo4j
        for _, row in cycleways.iterrows():
            coordinates = eval(row['coordinates'])
            name = row['name'] if pd.notna(row['name']) else "Inconnu"

            for i in range(len(coordinates) - 1):
                start = coordinates[i]
                end = coordinates[i + 1]
                session.run(
                    """
                    MERGE (a:Location {latitude: $start_lat, longitude: $start_lng})
                    ON CREATE SET a.name = $name
                    MERGE (b:Location {latitude: $end_lat, longitude: $end_lng})
                    ON CREATE SET b.name = $name
                    MERGE (a)-[:CYCLEWAY {name: $name}]->(b)
                    """,
                    start_lat=start[1], start_lng=start[0], end_lat=end[1], end_lng=end[0], name=name
                )
        print("Données de pistes cyclables chargées dans Neo4j.")

        # Charger les restaurants dans Neo4j avec id_restaurant comme identifiant unique
        for _, row in restaurants.iterrows():
            session.run(
                """
                MERGE (r:Restaurant {id_restaurant: $id_restaurant})
                ON CREATE SET r.nom = $nom, r.latitude = $latitude, r.longitude = $longitude
                """,
                id_restaurant=row['id_restaurant'],
                nom=row['nom'] if pd.notna(row['nom']) else "Inconnu",
                latitude=row['latitude'],
                longitude=row['longitude']
            )
        print("Données de restaurants chargées dans Neo4j.")


load_to_mongo()
load_to_neo4j()
