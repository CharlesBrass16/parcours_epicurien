import time
from pymongo import MongoClient
from neo4j import GraphDatabase
import pandas as pd
import os
from neo4j.exceptions import ServiceUnavailable

def wait_for_neo4j(driver, timeout=6000):
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

def precompute_starting_points():
    print("Pré-calcul des starting points...")

    # Charger les données
    restaurants = pd.read_csv("data/restaurants_paris_cleaned.csv").to_dict(orient="records")
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/velo_epicurien")
    client = MongoClient(mongo_uri)
    db = client['velo_epicurien']
    starting_points_collection = db['starting_points']

    # Supprimer les anciens starting points
    starting_points_collection.delete_many({})
    driver = GraphDatabase.driver("bolt://neo4j:7687", auth=("neo4j", "password"))
    # Attendre que Neo4j soit disponible
    wait_for_neo4j(driver)
    starting_points = []
    # Préparer les starting points
    with driver.session() as session:
        for restaurant in restaurants:
            lat, lng = restaurant['latitude'], restaurant['longitude']

            # Vérifier si le restaurant est connecté à une piste cyclable
            result = session.run(
                """
                MATCH (r:Restaurant {latitude: $lat, longitude: $lng})
                MATCH (r)-[:CONNECTED_TO]->(loc:Location)
                RETURN COUNT(loc) > 0 AS is_connected
                """,
                lat=lat, lng=lng
            )

            if result.single()["is_connected"]:
                # Ajouter le point de départ avec des métadonnées
                starting_points.append({
                    "coordinates": [lng, lat],
                    "type": restaurant['type_de_restaurant'],
                    "name": restaurant['nom'],
                    "connected": True  # Validation pré-calculée
                })

            # Arrêter après un certain nombre si nécessaire (facultatif)
            if len(starting_points) >= 100:
                break

    # Sauvegarder les starting points dans MongoDB
    starting_points_collection.insert_many(starting_points)
    print(f"{len(starting_points)} starting points sauvegardés dans MongoDB.")



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
                distance = ((end[1] - start[1]) ** 2 + (end[0] - start[0]) ** 2) ** 0.5 * 111139  # Conversion en mètres
                # Relation dans un sens
                session.run(
                    """
                    MERGE (a:Location {latitude: $start_lat, longitude: $start_lng})
                    ON CREATE SET a.name = $name
                    MERGE (b:Location {latitude: $end_lat, longitude: $end_lng})
                    ON CREATE SET b.name = $name
                    MERGE (a)-[r:CYCLEWAY {name: $name}]->(b)
                    ON CREATE SET r.length = $distance
                    """,
                    start_lat=start[1], start_lng=start[0],
                    end_lat=end[1], end_lng=end[0],
                    name=name, distance=distance
                )
                # Relation dans l'autre sens
                session.run(
                    """
                    MERGE (a:Location {latitude: $end_lat, longitude: $end_lng})
                    ON CREATE SET a.name = $name
                    MERGE (b:Location {latitude: $start_lat, longitude: $start_lng})
                    ON CREATE SET b.name = $name
                    MERGE (a)-[r:CYCLEWAY {name: $name}]->(b)
                    ON CREATE SET r.length = $distance
                    """,
                    start_lat=start[1], start_lng=start[0],
                    end_lat=end[1], end_lng=end[0],
                    name=name, distance=distance
                )
        print("Données de pistes cyclables chargées dans Neo4j.")

        # Charger les restaurants et les connecter au graphe
        for _, row in restaurants.iterrows():
            latitude = row['latitude']
            longitude = row['longitude']
            name = row['nom'] if pd.notna(row['nom']) else "Inconnu"

            # Connecter chaque restaurant à la piste cyclable la plus proche
            result = session.run(
                """
                MATCH (loc:Location)
                WITH loc, point.distance(point({latitude: loc.latitude, longitude: loc.longitude}),
                                         point({latitude: $latitude, longitude: $longitude})) AS dist
                ORDER BY dist ASC
                LIMIT 1
                RETURN loc.latitude AS nearest_lat, loc.longitude AS nearest_lng
                """,
                latitude=latitude, longitude=longitude
            )

            record = result.single()
            if record:
                nearest_lat = record['nearest_lat']
                nearest_lng = record['nearest_lng']

                session.run(
                    """
                    MERGE (r:Restaurant {id_restaurant: $id_restaurant})
                    ON CREATE SET r.nom = $name, r.latitude = $latitude, r.longitude = $longitude
                    WITH r
                    MATCH (loc:Location {latitude: $nearest_lat, longitude: $nearest_lng})
                    MERGE (r)-[:CONNECTED_TO]->(loc)
                    """,
                    id_restaurant=row['id_restaurant'],
                    name=name,
                    latitude=latitude,
                    longitude=longitude,
                    nearest_lat=nearest_lat,
                    nearest_lng=nearest_lng
                )

        print("Restaurants connectés aux pistes cyclables et chargés dans Neo4j.")



#load_to_mongo()
#load_to_neo4j()
#precompute_starting_points()