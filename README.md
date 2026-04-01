# Projet VéloEpicurien

Ce projet est une application Flask intégrée avec MongoDB et PostgreSQL, utilisant Docker et Docker Compose pour orchestrer les différents services.

Contributeurs:

- Charles Brassard

- Christian Willy Fosso Teubou

- Charles-Étienne Dumont

- Zack Dufresne

# Description du projet

VéloEpicurien est une application web qui combine des données sur les pistes cyclables et les restaurants afin de proposer des parcours enrichis.

L'objectif est de :

- exploiter des données ouvertes

- les transformer et les structurer

- les exposer via une API Flask

- permettre l’exploration de parcours combinant vélo et restauration

⚙️ Pipeline de données (ETL)

Le projet repose sur un pipeline ETL composé de trois scripts principaux :

🔹 extract.py

Ce script est responsable de l’extraction des données brutes :

- récupération des données (API, fichiers, etc.)

- chargement initial dans une base intermédiaire (MongoDB)

- stockage sans transformation majeure

# Objectif : collecter les données telles quelles

🔹 transform.py

Ce script transforme les données extraites :

- nettoyage des données

- agrégation (ex : nombre de restaurants par type)

- calculs (ex : longueur des pistes cyclables)

- structuration pour analyse

# Objectif : rendre les données exploitables et cohérentes

🔹 load.py

Ce script charge les données transformées :

- insertion dans PostgreSQL

- préparation pour l’accès via l’API Flask

# Objectif : rendre les données disponibles pour l’application

## Fonctionnement global de l'application

Les données sont extraites (extract.py)

Elles sont transformées (transform.py)

Elles sont chargées en base (load.py)

L’API Flask permet ensuite de :

- consulter les données

- générer des parcours

- explorer les statistiques

## Ce que permet l'application

L’application permet notamment :

- d’obtenir des statistiques sur les restaurants

- d’analyser les pistes cyclables

- de générer des parcours combinant vélo et gastronomie

- d’explorer les données via plusieurs endpoints API

## Prérequis

Avant de commencer, assurez-vous d'avoir installé les outils suivants :

- **Docker**
- **Docker Compose** : Docker Compose est inclus avec Docker Desktop.

## Démarrage du projet

### Lancement via Docker Compose

L'application est configurée pour utiliser Docker et Docker Compose, orchestrant harmonieusement plusieurs conteneurs tels que l'application web (Flask), MongoDB et PostgreSQL.

1. **Naviguez dans le répertoire du projet** :
```bash
cd veloEpicurien
```
2. **Pour démarrer tous les services, exécutez la commande suivante :**

```bash
docker-compose up --build
```

## Accès à l'application

Une fois le projet démarré, l'application est accessible via :
```bash
http://localhost:80/heartbeat
```

Une fois le projet démarré, la récupération du nombre de restaurants et de segments sont acessibles via :
```bash
http://localhost:80/extracted_data
```

Une fois le projet démarré, les comptes de restaurants par type ainsi que la taille de la piste cyclable sont accessibles via :
```bash
http://localhost:80/transformed_data
```

Une fois le projet démarré, l'obtention du fichier README est accessible via:
```bash
http://localhost:80/readme
```

Une fois le projet démarré, l'obtention des différents types de restaurant sont accessibles via:
```bash
http://localhost:80/type
```

Une fois le projet démarré, l'obtention d'un point de départ de parcours est accessible via:
```bash
http://localhost:80/starting_point
```

Une fois le projet démarré, l'obtention d'un parcours est accessible via:
```bash
http://localhost:80/parcours
```
