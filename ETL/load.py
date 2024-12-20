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

def add_link(session, lat1, lon1, lat2, lon2, distance=50, name="Lien ajouté"):
        session.run("""
        MATCH (a:Location {latitude: $lat1, longitude: $lon1})
        MATCH (b:Location {latitude: $lat2, longitude: $lon2})
        MERGE (a)-[:CYCLEWAY {name: $name, length: $distance}]->(b)
        MERGE (b)-[:CYCLEWAY {name: $name, length: $distance}]->(a)
    """, lat1=lat1, lon1=lon1, lat2=lat2, lon2=lon2, distance=distance, name=name)

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
                RETURN loc.latitude AS nearest_lat, loc.longitude AS nearest_lng, dist AS distance
                """,
                latitude=latitude, longitude=longitude
            )

            record = result.single()
            if record:
                nearest_lat = record['nearest_lat']
                nearest_lng = record['nearest_lng']
                distance = record['distance']  # Distance en mètres

                # Relation dans le sens Restaurant -> Location
                session.run(
                    """
                    MERGE (r:Restaurant {id_restaurant: $id_restaurant})
                    ON CREATE SET r.nom = $name, r.latitude = $latitude, r.longitude = $longitude
                    WITH r
                    MATCH (loc:Location {latitude: $nearest_lat, longitude: $nearest_lng})
                    MERGE (r)-[rel:CONNECTED_TO {length: $distance}]->(loc)
                    """,
                    id_restaurant=row['id_restaurant'],
                    name=name,
                    latitude=latitude,
                    longitude=longitude,
                    nearest_lat=nearest_lat,
                    nearest_lng=nearest_lng,
                    distance=distance
                )

                # Relation dans le sens Location -> Restaurant
                session.run(
                    """
                    MATCH (loc:Location {latitude: $nearest_lat, longitude: $nearest_lng})
                    MATCH (r:Restaurant {id_restaurant: $id_restaurant})
                    MERGE (loc)-[rel:CONNECTED_TO {length: $distance}]->(r)
                    """,
                    id_restaurant=row['id_restaurant'],
                    nearest_lat=nearest_lat,
                    nearest_lng=nearest_lng,
                    distance=distance
                )

        print("Restaurants connectés aux pistes cyclables et chargés dans Neo4j.")

        
        add_link(session, 48.8411127, 2.3247417, 48.8562529, 2.3567022)
        add_link(session, 48.8562529, 2.3567022, 48.856641, 2.3549542)
        add_link(session, 48.856641, 2.3549542, 48.8869148, 2.3324769)
        add_link(session, 48.8869148, 2.3324769, 48.8738713, 2.2957297)
        add_link(session, 48.8738713, 2.2957297, 48.8750361, 2.2914629)
        add_link(session, 48.8750361, 2.2914629, 48.8652664, 2.3272303)
        add_link(session, 48.8652664, 2.3272303, 48.8436818, 2.370984)
        add_link(session, 48.8641531, 2.3513847, 48.8567026, 2.3549917)
        add_link(session, 48.8412731, 2.3248713, 48.8582782, 2.2722058)
        add_link(session, 48.8569033, 2.2663846, 48.8573959, 2.2649131)
        add_link(session, 48.8578736, 2.268689, 48.8631744, 2.3338823)
        add_link(session, 48.8631744, 2.3338823, 48.8511554, 2.4127625)
        add_link(session, 48.8511554, 2.4127625,48.8293222, 2.3605988)
        add_link(session, 48.829288, 2.3607131, 48.8741656, 2.3376206)
        add_link(session, 48.8741541,2.3380375,48.8644974, 2.3186104)
        add_link(session, 48.8644974, 2.3186104,48.8747986, 2.3795184)
        add_link(session,48.8747658, 2.3795742, 48.8997745, 2.3740653)
        add_link(session, 48.899827, 2.3740634, 48.8297868, 2.3339636)
        add_link(session,48.899827, 2.3740634, 48.8706506, 2.4107272)
        add_link(session, 48.8435701, 2.3711792, 48.8646683, 2.4046572)
        add_link(session, 48.8435701, 2.3711792,48.8488486,2.3719438 )
        add_link(session, 48.8488486,2.3719438, 48.8407126,	2.2683007 )
        add_link(session, 48.8414184, 2.2691846, 48.8678939, 2.4109962)
        add_link(session, 48.8678957,2.4110853, 48.8664689, 2.3614585)
        add_link(session, 48.8646815, 2.3596085, 48.8642601, 2.3205046)
        add_link(session, 48.8646815, 2.3596085, 48.8690008,2.2735833 )
        add_link(session, 48.8646815, 2.3596085, 48.8410338,2.4132626 )
        add_link(session, 48.8398744, 2.4131365,48.874089,2.4130448 )
        add_link(session,48.8385515,2.2554848,48.8764031,2.4124033)
        add_link(session,48.8768057,2.4119691,48.8842239,2.3690463 )
        add_link(session,48.8842941,2.3689214,48.8549763,2.3536359 )
        add_link(session,48.8842941,2.3689214,48.865737,2.4114338)
        add_link(session,48.8544834,2.3549097,48.8466011,2.3667972)
        add_link(session,48.8512044,2.3689901, 48.8410382,2.3743215)
        add_link(session,48.8410853,2.3742944,48.8351772,2.4068403)
        add_link(session,48.8350334,2.4072374,48.8464002,2.413433)
        add_link(session,48.8464002,2.413433,48.8276761,2.3264288)
        add_link(session,48.8277538,2.3265476,48.8577632,2.2629752)
        add_link(session,48.8577632,2.2629752,48.8759191,2.2809144)
        add_link(session,48.8566442,2.2624977,48.8536609,2.4121988 )
        add_link(session,48.8566442,2.2624977,48.8989625, 2.3810525)
        add_link(session, 48.8989625, 2.3810525,48.8986488,2.3713497)
        add_link(session, 48.8512044, 2.3689901, 48.8517503, 2.3693387)
        add_link(session,48.8517503, 2.3693387, 48.83435, 2.409537)
        add_link(session,48.8517503, 2.3693387, 48.8321312, 2.3797185)
        add_link(session,48.8517503, 2.3693387,	48.8749445,	2.3049905)

        print("Liens supplémentaires ajoutés entre sous-graphes.")



load_to_mongo()
load_to_neo4j()
