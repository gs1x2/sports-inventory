#!/bin/bash
# Скрипт для установки и клонирования репозитория, а также установки зависимостей

# Использование:
#   ./setup.sh <ссылка-на-репозиторий>
# Пример:
#   ./setup.sh https://github.com/your-name/sports_inventory.git

if [ -z "$1" ]; then
  echo "Не указана ссылка на репозиторий."
  echo "Использование: $0 <repo-link>"
  exit 1
fi

REPO_LINK=$1

echo "Клонируем репозиторий: $REPO_LINK"
git clone $REPO_LINK sports_inventory

cd sports_inventory || exit

echo "Устанавливаем зависимости из requirements.txt..."
pip install -r requirements.txt

echo "Установка завершена. Для запуска приложения используйте:"
echo "  flask run --host=0.0.0.0 --port=8080"
