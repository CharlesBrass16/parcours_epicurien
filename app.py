from flask import Flask, jsonify, request
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


# Route @GET /type
@app.route('/type', methods=['GET'])
def get_types():
    types = restaurant_collection.distinct("type_de_restaurant")
    return jsonify(types)

# Route @POST /starting_point
@app.route('/starting_point', methods=['POST'])
def get_starting_point():
    data = request.json
    length = data.get("length", 0)
    types = data.get("type", [])

    # Filtrer les restaurants par type
    query = {"type_de_restaurant": {"$in": types}} if types else {}
    restaurants = list(restaurant_collection.find(query, {"latitude": 1, "longitude": 1}))

    if not restaurants:
        return jsonify({"error": "No restaurants found"}), 404

    # Choisir un point de départ aléatoire
    selected_restaurant = random.choice(restaurants)
    point = {
        "type": "Point",
        "coordinates": [selected_restaurant["longitude"], selected_restaurant["latitude"]]
    }

    return jsonify({"startingPoint": point})

@app.route('/starting_point_pre_calculate', methods=['GET'])
def get_starting_point_pre_calculate():
    """
    Recherche un point de départ valide basé sur les données précalculées
    dans la collection 'starting_points'.
    """

    # Filtrer les starting points par type
    query = {}


    # Chercher les starting points
    starting_points = list(db['starting_points'].find(query))

    if not starting_points:
        return jsonify({"error": "Aucun point de départ valide trouvé pour les critères spécifiés."}), 404

    # Choisir un starting point aléatoire parmi ceux qui conviennent
    selected_point = random.choice(starting_points)

    # Sérialiser chaque starting point dans la liste
    serialized_starting_point = {
        "_id": str(selected_point["_id"]),  # Convertir ObjectId en chaîne
        **{key: value for key, value in selected_point.items() if key != "_id"}  # Inclure les autres champs
    }

    return jsonify({"startingPoint": serialized_starting_point})


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

    visited = set()  # Ensemble pour stocker les nœuds déjà visités
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
        visited.add((current_node["latitude"], current_node["longitude"]))

        # Étape 2 : Parcourir le réseau cyclable pour visiter les restaurants
        while total_distance < length * 1.1 and stops_added < number_of_stops:
            # Vérifier si le nœud courant est connecté à un restaurant du type spécifié
            restaurant_result = session.run(
                """
                MATCH (current:Location {latitude: $current_lat, longitude: $current_lng})
                MATCH (restaurant:Restaurant)-[r:CONNECTED_TO]->(current)
                WHERE r.length < 10  // Filtrer pour s'assurer que la connexion est réaliste
                RETURN restaurant.nom AS name, restaurant.type_de_restaurant AS type,
                       restaurant.latitude AS lat, restaurant.longitude AS lng, r.length AS distance
                """,
                current_lat=current_node["latitude"],
                current_lng=current_node["longitude"]
            )

            found_restaurant = False
            for record in restaurant_result:
                if not types or record["type"] in types:  # Filtrer par type de restaurant
                    # Ajouter le restaurant au parcours
                    features.append({
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [record["lng"], record["lat"]]
                        },
                        "properties": {
                            "name": record["name"],
                            "type": record["type"],
                            "distance": record["distance"]
                        }
                    })
                    total_distance += record["distance"]
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
                if candidate not in visited:  # Vérifier si le nœud n'a pas été visité
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
            visited.add((current_node["latitude"], current_node["longitude"]))

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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)