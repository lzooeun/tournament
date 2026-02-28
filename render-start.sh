#!/usr/bin/env bash

# 1. 봇을 백그라운드에서 실행하고 로그를 남김
python bot.py &

# 2. 장고 웹 서버 실행
gunicorn config.wsgi:application --bind 0.0.0.0:$PORT