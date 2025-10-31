#!/usr/bin/env bash
# exit on error
set -o errexit

# Install system tools needed for dlib and OpenCV
apt-get update && apt-get install -y build-essential cmake libopenblas-dev liblapack-dev libjpeg-dev

# Install Python packages
pip install -r requirements.txt