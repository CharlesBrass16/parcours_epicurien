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
    # Lecture des données de la requête
    data = request.get_json()
    starting_point = data['startingPoint']['coordinates']  # Coordonnées du point de départ
    length = data['length']  # Longueur du parcours en mètres
    number_of_stops = data['numberOfStops']  # Nombre d'arrêts souhaités
    types = data.get('type', [])  # Types de restaurants spécifiés (vide = tous les types)

    # Étape 1 : Récupérer les restaurants proches et valider leur connectivité au réseau cyclable
    nearby_restaurants = list(restaurant_collection.find({
        "latitude": {"$gt": starting_point[1] - 0.0045, "$lt": starting_point[1] + 0.0045},
        "longitude": {"$gt": starting_point[0] - 0.0045, "$lt": starting_point[0] + 0.0045}
    }))

    # Filtrer les restaurants par type
    if types:
        nearby_restaurants = [r for r in nearby_restaurants if r['type_de_restaurant'] in types]

    if not nearby_restaurants:
        return jsonify({"error": "Aucun restaurant correspondant au type spécifié dans le rayon de 500 mètres."}), 404

    # Vérifier la connectivité des restaurants avec Neo4j
    connected_restaurants = nearby_restaurants
    # with neo4j_driver.session() as session:
    #     for restaurant in nearby_restaurants:
    #         result = session.run(
    #             """
    #             MATCH (start:Location {latitude: $start_lat, longitude: $start_lng}),
    #                   (restaurant:Restaurant)-[:CONNECTED_TO]->(location:Location)
    #             WHERE location.latitude = $rest_lat AND location.longitude = $rest_lng
    #             RETURN EXISTS( (start)-[:CYCLEWAY*]->(location) ) AS connected
    #             """,
    #             start_lat=starting_point[1], start_lng=starting_point[0],
    #             rest_lat=restaurant['latitude'], rest_lng=restaurant['longitude']
    #         )
    #         record = result.single()
    #         if record and record["connected"]:  # Vérifier que le résultat n'est pas None
    #             connected_restaurants.append(restaurant)
    #
    # # Si aucun restaurant connecté n'est trouvé, retourner une erreur
    # if not connected_restaurants:
    #     return jsonify({"error": "Aucun restaurant connecté au réseau cyclable trouvé."}), 404

    # Étape 2 : Construire le trajet avec Neo4j (Dijkstra) pour respecter la longueur demandée
    with neo4j_driver.session() as session:
        ensure_graph_projected(session)
        current_point = starting_point
        total_distance = 0
        stops_added = 0
        features = []  # GeoJSON features

        while total_distance < length * 1.1 and stops_added < number_of_stops:
            # Trouver le segment le plus court qui reste dans la longueur restante
            next_segment = None
            min_cost = float('inf')
            next_restaurant = None

            for restaurant in connected_restaurants:
                result = session.run(
                    """
                    MATCH (start:Location {latitude: $start_lat, longitude: $start_lng}),
                          (end:Location {latitude: $end_lat, longitude: $end_lng})
                    CALL gds.shortestPath.dijkstra.stream('cyclewaysGraph', {
                        sourceNode: id(start),
                        targetNode: id(end),
                        relationshipWeightProperty: 'length'
                    })
                    YIELD totalCost, nodeIds
                    RETURN totalCost, nodeIds
                    """,
                    start_lat=current_point[1], start_lng=current_point[0],
                    end_lat=restaurant['latitude'], end_lng=restaurant['longitude']
                )
                for record in result:
                    cost = record['totalCost']
                    print(f"Test path to restaurant {restaurant['nom']} with cost {cost} meters")
                    if cost < min_cost and total_distance + cost <= length * 1.1:
                        min_cost = cost
                        next_segment = record
                        next_restaurant = restaurant

            if not next_segment:
                print("Aucun segment valide trouvé. Vérifiez les relations ou les projections de graphe.")
                break

            # Ajouter le segment et le restaurant au parcours
            total_distance += min_cost
            current_point = [next_restaurant['longitude'], next_restaurant['latitude']]
            stops_added += 1

            # Ajouter le restaurant comme point
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [next_restaurant['longitude'], next_restaurant['latitude']]
                },
                "properties": {
                    "name": next_restaurant['nom'],
                    "type": next_restaurant['type_de_restaurant']
                }
            })

            # Ajouter le segment cyclable
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "MultiLineString",
                    "coordinates": next_segment['nodeIds']  # Convertir les nœuds en coordonnées
                },
                "properties": {
                    "length": min_cost
                }
            })

    # Étape 3 : Vérifier que la longueur totale est dans la plage acceptable
    if total_distance < length * 0.9 or total_distance > length * 1.1:
        return jsonify(
            {
                "error": "Impossible de respecter la longueur spécifiée pour le parcours.",
                "nearby_restaurants": [serialize_restaurant(r) for r in connected_restaurants],
                "total_distance": total_distance,
                "features":features
            }
        ), 400

    # Retourner le GeoJSON
    return jsonify({
        "type": "FeatureCollection",
        "features": features
    })


def serialize_restaurant(restaurant):
    restaurant['_id'] = str(restaurant['_id'])  # Convertir l'ObjectId en chaîne
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