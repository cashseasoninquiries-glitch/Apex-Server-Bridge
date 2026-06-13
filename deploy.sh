#!/bin/bash
echo "--- Apex Deploy: Pulling latest code ---"
cd /root/Apex_Server_Bridge
git pull origin master
echo "--- Rebuilding and restarting containers ---"
docker compose up --build -d
echo "--- Deploy complete ---"
docker compose ps
