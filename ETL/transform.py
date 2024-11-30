import pandas as pd

def format_address(row):
    address_parts = [row.get('addr:housenumber'), row.get('addr:street'), row.get('addr:postcode'), row.get('addr:city')]
    return ", ".join(part for part in address_parts if isinstance(part, str))

def determine_service_type(description):
    if pd.isna(description):
        return "Standard"

    description = description.lower()
    if "gastronomique" in description or "fancy" in description:
        return "Gastronomique"
    elif "buffet" in description or "à volonté" in description:
        return "Buffet / À volonté"
    elif "livraison" in description or "deliveroo" in description or "uber eats" in description:
        return "Service de livraison"
    elif "emporter" in description or "take-away" in description:
        return "Service à emporter"
    elif "bar" in description or "cave à vin" in description:
        return "Bar / Cave à vin"
    elif "cantine" in description or "self-service" in description:
        return "Cantine / Self-service"
    elif "street food" in description:
        return "Street Food"
    elif "brasserie" in description:
        return "Brasserie"
    elif "restaurant associatif" in description or "prix libre" in description:
        return "Restaurant associatif"
    else:
        return "Standard"

def transform_data():
    # Transformation des restaurants
    restaurants = pd.read_csv("data/restaurants_paris.csv")
    restaurants = restaurants.dropna(subset=["latitude", "longitude"])

    # Créer la colonne adresse_complete en format canadien
    restaurants['adresse_complete'] = restaurants.apply(format_address, axis=1)

    # Déterminer les types de restaurant et de service
    restaurants['type_de_service'] = restaurants.apply(lambda row: determine_service_type(row['description']), axis=1)

    # Renommer les colonnes en français
    restaurants = restaurants.rename(columns={
        "osmid": "id_restaurant",
        "name": "nom",
        "amenity": "type_etablissement",
        "cuisine": "type_de_restaurant",
        "latitude": "latitude",
        "longitude": "longitude",
        "phone": "telephone",
        "opening_hours": "horaires_ouverture",
        "description": "description"
    })

    # Supprimer les colonnes non nécessaires
    columns_to_keep = ["id_restaurant", "nom", "type_etablissement", "type_de_restaurant", "type_de_service", "latitude", "longitude", "adresse_complete", "telephone", "horaires_ouverture", "description"]
    restaurants = restaurants[columns_to_keep]

    # Transformation des pistes cyclables
    cycleways = pd.read_csv("data/cycleways_paris.csv")
    cycleways['length'] = cycleways['coordinates'].apply(lambda x: len(eval(x)) if x else 0)

    # Sauvegarder les données transformées
    restaurants.to_csv("data/restaurants_paris_cleaned.csv", index=False)
    cycleways.to_csv("data/cycleways_paris_cleaned.csv", index=False)

    print("Transformation terminée.")
    return restaurants, cycleways


transform_data()
