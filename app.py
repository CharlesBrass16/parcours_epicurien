from flask import Flask, jsonify
from pymongo import MongoClient
from neo4j import GraphDatabase

app = Flask(__name__)

# Connexion à MongoDB
mongo_client = MongoClient("mongodb://mongo:27017/velo_epicurien")
db = mongo_client['velo_epicurien']
restaurant_collection = db['restaurants']

# Connexion à Neo4j
neo4j_driver = GraphDatabase.driver("bolt://neo4j:7687", auth=("neo4j", "password"))


@app.route('/heartbeat', methods=['GET'])
def heartbeat():
    return jsonify({"villeChoisie": "Paris"})


@app.route('/extracted_data', methods=['GET'])
def extracted_data():
    # Nombre de restaurants
    nb_restaurants = restaurant_collection.count_documents({})

    # Nombre de segments de pistes cyclables
    with neo4j_driver.session() as session:
        result = session.run("MATCH ()-[r:CYCLEWAY]->() RETURN count(r) AS nbSegments")
        nb_segments = result.single()["nbSegments"]

    return jsonify({
        "nbRestaurants": nb_restaurants,
        "nbSegments": nb_segments
    })


@app.route('/transformed_data', methods=['GET'])
def transformed_data():
    # Nombre de restaurants par type de restaurant et type de service
    restaurant_types = restaurant_collection.aggregate([
        {"$group": {"_id": "$type_de_restaurant", "count": {"$sum": 1}}}
    ])
    service_types = restaurant_collection.aggregate([
        {"$group": {"_id": "$type_de_service", "count": {"$sum": 1}}}
    ])

    # Construction de l'objet JSON pour les restaurants
    restaurants_data = {}
    for r_type in restaurant_types:
        restaurants_data[f"{r_type['_id']}"] = r_type['count']
    for s_type in service_types:
        restaurants_data[f"{s_type['_id']}"] = s_type['count']

    # Longueur totale des pistes cyclables
    with neo4j_driver.session() as session:
        result = session.run("""
            MATCH (a)-[r:CYCLEWAY]->(b)
            RETURN sum(point.distance(point({latitude: a.latitude, longitude: a.longitude}), 
                                      point({latitude: b.latitude, longitude: b.longitude}))) AS totalLength
        """)
        longueur_cyclable = result.single()["totalLength"]

    return jsonify({
        "restaurants": restaurants_data,
        "longueurCyclable": longueur_cyclable
    })



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)
