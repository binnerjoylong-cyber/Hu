#!/bin/bash

apt-get update -y
apt-get install -y ffmpeg

pip install -r requirements.txt
pip install --upgrade pytubefix
