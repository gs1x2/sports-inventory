#!/bin/bash

# Создаем директорию для SSL сертификатов
mkdir -p ssl

# Останавливаем nginx если он запущен
docker compose down

# Запускаем certbot для получения сертификатов
docker run --rm -it \
  -v "$(pwd)/ssl:/etc/letsencrypt" \
  -p 80:80 \
  certbot/certbot certonly \
  --standalone \
  --agree-tos \
  --no-eff-email \
  --email my@maxgoltsev.ru \
  -d gs1x2.ru \
  -d www.gs1x2.ru

# Создаем символические ссылки для nginx
mkdir -p ssl/live/gs1x2.ru
ln -sf ../../archive/gs1x2.ru/fullchain.pem ssl/live/gs1x2.ru/fullchain.pem
ln -sf ../../archive/gs1x2.ru/privkey.pem ssl/live/gs1x2.ru/privkey.pem

# Запускаем приложение
docker compose up --build -d

echo "SSL сертификаты установлены. Приложение запущено с HTTPS." 