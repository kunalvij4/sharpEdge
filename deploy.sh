#!/bin/bash

echo "Pulling latest changes..."
git pull

echo "Starting app..."
python3 app/app.py
