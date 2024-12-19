from flask import Flask, jsonify, request, send_file
from pymongo import MongoClient
from neo4j import GraphDatabase
from math import radians, cos, sin, sqrt, atan2
import random

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


@app.route('/readme', methods=['GET'])
def download_file():
    try:
        # Fichier readMe
        return send_file('README.md', as_attachment=True)
    except FileNotFoundError:
        # Devrait jamais arriver
        return {"error": "README.md not found"}, 404


@app.route('/type', methods=['GET'])
def type():
    # Types de restaurants
    restaurant_types = restaurant_collection.aggregate([
        {"$group": {"_id": "$type_de_restaurant"}}
    ])

    restaurants_data = []
    for r_type in restaurant_types:
        restaurants_data.append(r_type["_id"])

    return jsonify(list(set(restaurants_data)))


@app.route('/starting_point', methods=['POST'])
def starting_point():
    payload = request.get_json()

    # Données de la request
    length = payload["length"]  # int
    types = payload["type"]  # Liste de strings
    random_restaurant = None

    max_length = length * 1.1
    min_length = length * 0.9
    result = []

    # Recherche de resto par type
    if types == []:
        while result == []:
            random_restaurant = restaurant_collection.aggregate([{'$sample': {'size': 1}}]).next()
            try:
                point_recherche = location_from_restaurant(random_restaurant['nom'])
            except:
                continue
            result = get_starting_points(point_recherche['latitude'], point_recherche['longitude'], min_length,
                                         max_length)

    else:
        restaurants = list(restaurant_collection.find({'type_de_restaurant': {'$in': types}}))
        while result == [] and restaurants != []:
            random_restaurant = random.choice(restaurants)
            restaurants.remove(random_restaurant)
            try:
                point_recherche = location_from_restaurant(random_restaurant['nom'])
            except:
                continue
            result = get_starting_points(point_recherche['latitude'], point_recherche['longitude'], min_length,
                                         max_length)

    if result == []:
        return "No valid restaurant found for these types and distance", 404

    result = random.choice(result)
    latitude = result['lastNode'].get('latitude')
    longitude = result['lastNode'].get('longitude')

    # Créer la réponse
    response = {
        "startingPoint": {
            "type": "Point",
            "coordinates": [longitude, latitude]
        }
    }

    return jsonify(response), 200


@app.route('/parcours', methods=['POST'])
def parcours():
    """
    Génère un parcours à partir d'un point de départ, avec une longueur spécifiée
    et un nombre d'arrêts souhaité.
    """
    data = request.get_json()
    starting_point = data['startingPoint']['coordinates']
    length = data['length']
    number_of_stops = data['numberOfStops']
    types = data.get('type', [])

    features = []  # Liste des éléments GeoJSON
    total_distance = 0
    stops_added = 0
    visited_restaurants = set()  # Ensemble pour garder la trace des restaurants visités
    current_multiline = []  # Accumulateur pour MultiLineString

    with neo4j_driver.session() as session:
        # Trouver le nœud de piste cyclable le plus proche dans un rayon de 500 mètres
        result = session.run(
            """
            MATCH (loc:Location)
            RETURN loc.latitude AS lat, loc.longitude AS lng,
                   point.distance(point({latitude: loc.latitude, longitude: loc.longitude}),
                                  point({latitude: $start_lat, longitude: $start_lng})) AS dist
            ORDER BY dist ASC
            LIMIT 1
            """,
            start_lat=starting_point[1], start_lng=starting_point[0]
        )
        nearest_node = result.single()
        if not nearest_node or nearest_node["dist"] > 500:
            return jsonify({"error": "Aucun nœud de piste cyclable trouvé dans un rayon de 500 mètres."}), 400

        current_node = {"latitude": nearest_node["lat"], "longitude": nearest_node["lng"]}
        current_multiline.append([current_node["longitude"], current_node["latitude"]])  # Ajouter le premier point

        while total_distance < length * 1.1 and stops_added < number_of_stops:
            # Trouver les restaurants connectés au nœud courant
            restaurant_result = session.run(
                """
                MATCH (start:Location {latitude: $current_lat, longitude: $current_lng})
                MATCH (restaurant:Restaurant)-[rel:CONNECTED_TO]->(start)
                RETURN restaurant.nom AS name, restaurant.latitude AS lat, restaurant.longitude AS lng,
                       rel.length AS dist
                ORDER BY rel.length ASC
                """,
                current_lat=current_node["latitude"], current_lng=current_node["longitude"]
            )

            next_restaurant = None
            for record in restaurant_result:
                if record["dist"] < 10 and record["name"] not in visited_restaurants and (
                    not types or record.get("type") in types
                ):
                    next_restaurant = record
                    break

            if next_restaurant:
                # Finaliser le segment MultiLineString jusqu'au restaurant
                current_multiline.append([next_restaurant["lng"], next_restaurant["lat"]])
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "MultiLineString",
                        "coordinates": [current_multiline]
                    },
                    "properties": {
                        "length": sum(
                            calculate_distance(
                                current_multiline[i][1], current_multiline[i][0],
                                current_multiline[i + 1][1], current_multiline[i + 1][0]
                            ) for i in range(len(current_multiline) - 1)
                        )
                    }
                })
                current_multiline = [[next_restaurant["lng"], next_restaurant["lat"]]]  # Réinitialiser pour le prochain segment

                # Ajouter le restaurant au parcours
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [next_restaurant["lng"], next_restaurant["lat"]]
                    },
                    "properties": {
                        "name": next_restaurant["name"],
                        "type": next_restaurant.get("type", "Unknown"),
                        "distance": next_restaurant["dist"]
                    }
                })
                stops_added += 1
                visited_restaurants.add(next_restaurant["name"])
                current_node = {"latitude": next_restaurant["lat"], "longitude": next_restaurant["lng"]}
                total_distance += next_restaurant["dist"]

            else:
                # Trouver le prochain nœud cyclable connecté
                neighbor_result = session.run(
                    """
                    MATCH (start:Location {latitude: $current_lat, longitude: $current_lng})
                    MATCH (start)-[rel:CYCLEWAY]->(neighbor:Location)
                    RETURN neighbor.latitude AS lat, neighbor.longitude AS lng,
                           rel.length AS dist
                    ORDER BY rel.length ASC
                    LIMIT 1
                    """,
                    current_lat=current_node["latitude"], current_lng=current_node["longitude"]
                )
                next_node = neighbor_result.single()
                if not next_node:
                    return jsonify({
                        "error": "Impossible de trouver un prochain noeud pour le parcours.",
                        "total_distance": total_distance,
                        "features": features
                    }), 400

                # Ajouter au segment courant
                current_multiline.append([next_node["lng"], next_node["lat"]])
                current_node = {"latitude": next_node["lat"], "longitude": next_node["lng"]}
                total_distance += next_node["dist"]

        # Vérifier si le parcours respecte la longueur spécifiée
        if total_distance < length * 0.9 or total_distance > length * 1.1:
            return jsonify({
                "error": "Impossible de respecter la longueur spécifiée pour le parcours.",
                "total_distance": total_distance,
                "features": features
            }), 400
        if stops_added < number_of_stops:
            return jsonify({
                "error": "Impossible de respecter le nombre de stops spécifié pour le parcours.",
                "number_stop_current": stops_added,
                "total_distance": total_distance,
                "features": features
            }), 400

    return jsonify({
        "type": "FeatureCollection",
        "features": features
    })


def location_from_restaurant(restaurantName):
    with neo4j_driver.session() as session:
        result = session.run("""
                    MATCH (restaurant:Restaurant {nom: $nom})
                    MATCH (pointPiste:Location)
                    WITH 
                        point({latitude: restaurant.latitude, longitude: restaurant.longitude}) AS restaurantPoint,
                        point({latitude: pointPiste.latitude, longitude: pointPiste.longitude}) AS pointPisteCoords,
                        pointPiste
                    WITH pointPiste, point.distance(restaurantPoint, pointPisteCoords) AS distance
                    RETURN pointPiste
                    ORDER BY distance ASC
                    LIMIT 1
                """,
                             nom=restaurantName)
        return result.single()["pointPiste"]


def get_starting_points(latitude, longitude, minLength, maxLength):
    with neo4j_driver.session() as session:
        result = session.run(
            """
            MATCH path = (start:Location {latitude: $lat, longitude: $lon})-[:CYCLEWAY*..10]->(end:Location)
            WITH path, 
                 reduce(distance = 0, rel IN relationships(path) | distance + rel.length) AS totalDistance, 
                 nodes(path)[-1] AS lastNode
            WHERE totalDistance >= $minDist AND totalDistance <= $maxDist
            RETURN lastNode, totalDistance
            ORDER BY totalDistance DESC
            LIMIT 1
            """,
            lat=latitude,
            lon=longitude,
            minDist=minLength,
            maxDist=maxLength
        )

        resList = []
        for record in result:
            resList.append(record)
        return resList



def calculate_distance(lat1, lng1, lat2, lng2):
    """
    Calcule la distance en mètres entre deux points géographiques en utilisant la formule haversine.
    """
    R = 6371000  # Rayon de la Terre en mètres
    phi1, phi2 = radians(lat1), radians(lat2)
    delta_phi = radians(lat2 - lat1)
    delta_lambda = radians(lng2 - lng1)

    a = sin(delta_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(delta_lambda / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return R * c


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)