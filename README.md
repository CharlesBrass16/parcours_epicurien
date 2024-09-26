# Projet VéloEpicurien

Ce projet est une application Flask intégrée avec MongoDB et PostgreSQL, utilisant Docker et Docker Compose pour orchestrer les différents services.

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
http://localhost:8080/heartbeat
```