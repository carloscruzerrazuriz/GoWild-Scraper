@echo off
title Actualizando Scraper Web App...
echo ======================================
echo Actualizando Scraper Web App a la ultima version...
echo ======================================

cd /d "%~dp0"

:: 1. Bajar ultimos cambios
git pull origin main

:: 2. Reconstruir contenedores
docker-compose up -d --build

echo ======================================
echo Actualizacion Completada! Ya puedes recargar la pagina.
echo ======================================
pause
