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

    with neo4j_driver.session() as session:
        ensure_graph_projected(session)

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

        # Étape 2 : Parcourir le réseau cyclable pour construire le trajet
        total_distance = 0
        stops_added = 0
        features = []  # GeoJSON features pour le trajet

        while total_distance < length * 1.1 and stops_added < number_of_stops:
            # Trouver le restaurant le plus proche connecté à partir du nœud courant
            next_restaurant = None
            min_cost = float('inf')
            next_segment = None

            # Rechercher les restaurants connectés au réseau cyclable
            result = session.run(
                """
                MATCH (start:Location {latitude: $current_lat, longitude: $current_lng})
                MATCH (restaurant:Restaurant)-[:CONNECTED_TO]->(end:Location)
                CALL gds.shortestPath.dijkstra.stream('cyclewaysGraph', {
                    sourceNode: id(start),
                    targetNode: id(end),
                    relationshipWeightProperty: 'length'
                })
                YIELD totalCost, nodeIds
                RETURN totalCost, nodeIds, restaurant.latitude AS rest_lat,
                       restaurant.longitude AS rest_lng, restaurant.nom AS name,
                       restaurant.type_de_restaurant AS type
                """,
                current_lat=current_node["latitude"],
                current_lng=current_node["longitude"]
            )

            for record in result:
                cost = record["totalCost"]
                restaurant_type = record["type"]

                # Filtrer par type de restaurant et vérifier la distance
                if (not types or restaurant_type in types) and total_distance + cost <= length * 1.1:
                    if cost < min_cost:
                        min_cost = cost
                        next_restaurant = {
                            "latitude": record["rest_lat"],
                            "longitude": record["rest_lng"],
                            "name": record["name"],
                            "type": restaurant_type
                        }
                        next_segment = record

            if not next_restaurant:
                print("Aucun restaurant valide trouvé. Arrêt de la boucle.")
                break

            # Ajouter le restaurant et le segment au parcours
            total_distance += min_cost
            current_node = {
                "latitude": next_restaurant["latitude"],
                "longitude": next_restaurant["longitude"]
            }
            stops_added += 1

            # Ajouter le restaurant comme point
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [next_restaurant["longitude"], next_restaurant["latitude"]]
                },
                "properties": {
                    "name": next_restaurant["name"],
                    "type": next_restaurant["type"]
                }
            })

            # Ajouter le segment cyclable
            coordinates = [
                [nearest_node["lng"], nearest_node["lat"]] for nearest_node in next_segment["nodeIds"]
            ]
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "MultiLineString",
                    "coordinates": coordinates
                },
                "properties": {
                    "length": min_cost
                }
            })

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