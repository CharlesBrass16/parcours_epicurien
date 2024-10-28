import osmnx as ox
import pandas as pd
from shapely.geometry import Point

tags = {"amenity": "restaurant"}

restaurants = ox.geometries_from_place("Rimouski, Quebec, Canada", tags)

if not restaurants.empty:
    restaurants = restaurants.reset_index()

    restaurants['latitude'] = restaurants['geometry'].apply(lambda geom: geom.y if isinstance(geom, Point) else None)
    restaurants['longitude'] = restaurants['geometry'].apply(lambda geom: geom.x if isinstance(geom, Point) else None)

    # columns_to_export = ['name', 'addr:housenumber', 'addr:street', 'latitude', 'longitude']

    # restaurants_filtered = restaurants[columns_to_export].dropna(subset=['name'])


    restaurants.to_csv("restaurants_rimouski_with_coordinates.csv", index=False)

    print(f"Fichier CSV 'restaurants_rimouski_with_coordinates.csv' exporté avec succès.")
else:
    print("Aucun restaurant trouvé pour la zone spécifiée.")