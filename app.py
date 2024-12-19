from flask import Flask, jsonify, request, send_file
from pymongo import MongoClient
from neo4j import GraphDatabase
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
            "coordinates": [latitude, longitude]
        }
    }

    return jsonify(response), 200


# Route @POST /parcours
@app.route('/parcours', methods=['POST'])
def parcours():
    """
    Génère un parcours à partir d'un point de départ, avec une longueur spécifiée
    et un nombre d'arrêts souhaité.
    """
    # Lecture des données de la requête
    data = request.get_json()
    starting_point = data['startingPoint']['coordinates']  # Coordonnées du point de départ
    length = data['length']  # Longueur du parcours en mètres
    number_of_stops = data['numberOfStops']  # Nombre d'arrêts souhaités
    types = data.get('type', [])  # Types de restaurants spécifiés (vide = tous les types)

    visited_nodes = set()  # Ensemble pour stocker les nœuds de piste visités
    visited_restaurants = set()  # Ensemble pour stocker les restaurants visités
    total_distance = 0
    stops_added = 0
    features = []  # GeoJSON features pour construire le parcours

    with neo4j_driver.session() as session:
        # Étape 1 : Trouver le nœud de piste cyclable le plus proche du point de départ
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
        if not nearest_node:
            return jsonify({"error": "Aucun nœud de piste cyclable trouvé proche du point de départ."}), 404

        current_node = {
            "latitude": nearest_node["lat"],
            "longitude": nearest_node["lng"]
        }
        visited_nodes.add((current_node["latitude"], current_node["longitude"]))

        # Étape 2 : Parcourir le réseau cyclable pour visiter les restaurants
        while total_distance < length * 1.1 and stops_added < number_of_stops:
            # Vérifier si le nœud courant est connecté à un restaurant
            restaurant_result = session.run(
                """
                MATCH (current:Location {latitude: $current_lat, longitude: $current_lng})
                MATCH (restaurant:Restaurant)-[r:CONNECTED_TO]->(current)
                WHERE r.length < 10  // Filtrer pour une distance réaliste
                RETURN restaurant.id_restaurant AS id_restaurant, r.length AS distance
                """,
                current_lat=current_node["latitude"],
                current_lng=current_node["longitude"]
            )

            found_restaurant = False
            for record in restaurant_result:
                restaurant_id = record["id_restaurant"]
                if restaurant_id in visited_restaurants:
                    continue  # Passer au prochain restaurant si celui-ci a déjà été visité

                # Récupérer les détails du restaurant depuis MongoDB
                restaurant_details = restaurant_collection.find_one({"id_restaurant": restaurant_id})
                if not restaurant_details:
                    continue

                # Filtrer par type de restaurant si nécessaire
                if types and restaurant_details["type_de_restaurant"] not in types:
                    continue

                # Ajouter le restaurant au parcours
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [restaurant_details["longitude"], restaurant_details["latitude"]]
                    },
                    "properties": {
                        "name": restaurant_details["nom"],
                        "type": restaurant_details["type_de_restaurant"],
                        "distance": record["distance"]
                    }
                })
                total_distance += record["distance"]
                visited_restaurants.add(restaurant_id)
                stops_added += 1
                found_restaurant = True
                break

            if found_restaurant:
                continue  # Passer directement au prochain nœud sans chercher de voisins

            # Sinon, chercher un nœud voisin pour continuer le parcours
            neighbor_result = session.run(
                """
                MATCH (current:Location {latitude: $current_lat, longitude: $current_lng})
                MATCH (neighbor:Location)-[r:CYCLEWAY]->(current)
                WHERE NOT (neighbor.latitude = $current_lat AND neighbor.longitude = $current_lng)
                RETURN neighbor.latitude AS lat, neighbor.longitude AS lng, r.length AS distance
                """,
                current_lat=current_node["latitude"],
                current_lng=current_node["longitude"]
            )

            next_node = None
            for record in neighbor_result:
                candidate = (record["lat"], record["lng"])
                if candidate not in visited_nodes:  # Vérifier si le nœud n'a pas été visité
                    next_node = {
                        "latitude": record["lat"],
                        "longitude": record["lng"],
                        "distance": record["distance"]
                    }
                    break

            if not next_node:
                break  # Aucun nœud voisin valide trouvé, on arrête la recherche

            # Ajouter le segment cyclable au parcours
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [current_node["longitude"], current_node["latitude"]],
                        [next_node["longitude"], next_node["latitude"]]
                    ]
                },
                "properties": {
                    "length": next_node["distance"]
                }
            })

            # Mettre à jour l'état du parcours
            total_distance += next_node["distance"]
            current_node = {
                "latitude": next_node["latitude"],
                "longitude": next_node["longitude"]
            }
            visited_nodes.add((current_node["latitude"], current_node["longitude"]))

    # Étape 3 : Vérifier que la longueur totale est respectée
    if total_distance < length * 0.9 or total_distance > length * 1.1:
        return jsonify({
            "error": "Impossible de respecter la longueur spécifiée pour le parcours.",
            "total_distance": total_distance,
            "features": features
        }), 400

    # Retourner le GeoJSON du parcours
    return jsonify({
        "type": "FeatureCollection",
        "features": features
    })





def serialize_restaurant(restaurant):
    restaurant['_id'] = str(restaurant['_id'])  # Convertir l'ObjectId en chaîne pour JSON
    return restaurant



def ensure_graph_projected(session):
    # Vérifier si le graphe existe
    graph_exists_query = "CALL gds.graph.exists('cyclewaysGraph') YIELD graphName RETURN graphName"
    result = session.run(graph_exists_query)
    if not result.single():
        # Si le graphe n'existe pas, le projeter
        session.run("""
            CALL gds.graph.project(
                'cyclewaysGraph',
                ['Location'],
                {
                    CYCLEWAY: {
                        properties: 'length'
                    }
                }
            )
        """)
        print("Graph projeté avec succès.")
    else:
        print("Le graphe 'cyclewaysGraph' existe déjà.")


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
        result = session.run("""
                    MATCH (dest:Location {latitude: $lat, longitude: $lon}) 
                    CALL(dest) {
                        MATCH path = (dest)-[:CYCLEWAY*]->(startingPoint)
                        WITH path,
                            reduce(totalDist = 0, i IN range(1, size(nodes(path)) - 1) | 
                                totalDist + point.distance(
                                    point({latitude: nodes(path)[i-1].latitude, longitude: nodes(path)[i-1].longitude}),
                                    point({latitude: nodes(path)[i].latitude, longitude: nodes(path)[i].longitude})
                                )
                            ) AS cumulativeDistance,
                            last(nodes(path)) AS lastNode
                        WHERE cumulativeDistance >= $minDist AND cumulativeDistance <= $maxDist
                        RETURN lastNode, cumulativeDistance
                        ORDER BY cumulativeDistance DESC
                        LIMIT 1
                    }
                    RETURN lastNode, cumulativeDistance
                """,
                             lat=latitude, lon=longitude, minDist=minLength, maxDist=maxLength)
        resList = []
        for record in result:
            resList.append(record)
        return resList

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)