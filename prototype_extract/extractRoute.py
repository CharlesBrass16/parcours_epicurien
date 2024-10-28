import pandas as pd
import openrouteservice


df = pd.read_csv('restaurants_rimouski.csv')


if len(df) < 2:
    raise ValueError("Il n'y a pas assez de restaurants dans le fichier CSV.")


restaurant_A_name = df.iloc[0]['name']
restaurant_B_name = df.iloc[1]['name']
restaurant_A = (float(df.iloc[0]['longitude']), float(df.iloc[0]['latitude']))
restaurant_B = (float(df.iloc[1]['longitude']), float(df.iloc[1]['latitude']))


print(f"Restaurant A: {restaurant_A_name} : {restaurant_A}")
print(f"Restaurant B: {restaurant_B_name} : {restaurant_B}")


client = openrouteservice.Client(key='CLE_API')


mode = 'cycling-regular'  
route = client.directions(
    coordinates=[restaurant_A, restaurant_B],
    profile=mode,
    format='geojson'
)


if 'features' in route:
    summary = route['features'][0]['properties']['summary']
    distance = summary['distance']  
    duration = summary['duration']  

    print(f"Distance entre {restaurant_A_name} et {restaurant_B_name}: {distance} mètres, Durée: {duration} secondes")

    steps = route['features'][0]['properties']['segments'][0]['steps']
    print("\nÉtapes de l'itinéraire :")
    for i, step in enumerate(steps):
        instruction = step['instruction']
        step_distance = step['distance']
        step_duration = step['duration']
        print(f"{i+1}. {instruction} - {step_distance:.1f} mètres, {step_duration:.1f} secondes")
else:
    raise ValueError("La réponse de l'API ORS ne contient pas de données d'itinéraire.")