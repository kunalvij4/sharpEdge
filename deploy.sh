#!/bin/bash
cd /home/ec2-user/sharpEdge/app

echo "Pulling latest code..."
git pull

echo "Restarting service..."
sudo systemctl restart flask-app

echo "Done."
