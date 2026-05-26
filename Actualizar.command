#!/bin/bash
# Script de Actualización Automática (Para Mac/Linux)

echo "======================================"
echo "Actualizando Scraper Web App a la última versión..."
echo "======================================"

cd "$(dirname "$0")"

# 1. Bajar últimos cambios de la Nave Nodriza
git pull origin main

# 2. Reconstruir los contenedores por si hay nuevas dependencias
docker-compose up -d --build

echo "======================================"
echo "¡Actualización Completada! Ya puedes recargar la página."
echo "======================================"
sleep 5
