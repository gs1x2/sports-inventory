import os

SECRET_KEY = os.environ.get('SECRET_KEY', 'super_secret_key_change_me')

# Параметры подключения к БД MySQL
DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_USER = os.environ.get('DB_USER', 'root')
DB_PASSWORD = os.environ.get('DB_PASSWORD', 'root')
DB_NAME = os.environ.get('DB_NAME', 'sports_inventory')

# Список логинов администраторов
ADMIN_LOGINS = ["admin"]  # можно добавить других

# SQLAlchemy URI
SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"
SQLALCHEMY_TRACK_MODIFICATIONS = False
