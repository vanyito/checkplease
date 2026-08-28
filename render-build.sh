#!/usr/bin/env bash
# Script de build para Render (Fase 4).
# Render corre el entorno "Python" sobre Linux/Debian, así que instalamos
# el binario de Tesseract con apt-get antes de instalar las dependencias
# de Python. Sin este paso, pytesseract está instalado pero no tiene qué
# ejecutar y /api/scan-receipt fallaría con "Tesseract no está instalado".
#
# En el dashboard de Render, configurar el "Build Command" como:
#   ./render-build.sh
#
# Si por algún motivo apt-get no está disponible en el build de Render,
# el escaneo de boletas queda temporalmente no funcional en producción
# (el resto de la app sigue andando igual) — no es bloqueante, se
# documenta y se arregla después.

set -o errexit

apt-get update -y
apt-get install -y tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng

pip install -r requirements.txt
