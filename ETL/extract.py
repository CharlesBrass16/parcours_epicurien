import os
import osmnx as ox
from shapely.geometry import Point, LineString


def extract_data():
    if not os.path.exists("data"):
        os.makedirs("data")

    # Extraction des restaurants
    restaurant_tags = {"amenity": "restaurant"}
    restaurants = ox.features_from_place("Paris, Île-de-France, France", restaurant_tags)
    if not restaurants.empty:
        restaurants = restaurants.reset_index()
        restaurants['latitude'] = restaurants['geometry'].apply(
            lambda geom: geom.y if isinstance(geom, Point) else None)
        restaurants['longitude'] = restaurants['geometry'].apply(
            lambda geom: geom.x if isinstance(geom, Point) else None)

        columns_to_keep = ["osmid", "name", "cuisine", "amenity", "latitude", "longitude",
                           "addr:city", "addr:housenumber", "addr:postcode", "addr:street",
                           "opening_hours", "phone", "description"]
        restaurants = restaurants[columns_to_keep]
        restaurants.to_csv("data/restaurants_paris.csv", index=False)

    # Extraction des pistes cyclables
    cycleway_tags = {"highway": "cycleway"}
    cycleways = ox.features_from_place("Paris, Île-de-France, France", cycleway_tags)
    if not cycleways.empty:
        cycleways = cycleways.reset_index()
        cycleways['coordinates'] = cycleways['geometry'].apply(
            lambda geom: list(geom.coords) if isinstance(geom, LineString) else None)
        columns_to_keep = ["osmid", "name", "coordinates"]
        cycleways = cycleways[columns_to_keep]
        cycleways.to_csv("data/cycleways_paris.csv", index=False)

    print("Extraction terminée.")
    return restaurants, cycleways


extract_data()
