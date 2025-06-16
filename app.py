import os
import re
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from io import BytesIO
import csv
import json
import io
from models import db, User, InventoryItem, PurchasePlan, UserRequest, ActionLog, SystemLog, Role
import config
import time
from sqlalchemy.exc import OperationalError
from functools import wraps
from datetime import datetime, timedelta
from flask_migrate import Migrate
from flask_caching import Cache

app = Flask(__name__)
app.config['SECRET_KEY'] = config.SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = config.SQLALCHEMY_TRACK_MODIFICATIONS

# Настройка кэширования
app.config['CACHE_TYPE'] = 'SimpleCache'
app.config['CACHE_DEFAULT_TIMEOUT'] = 300  # 5 минут
cache = Cache(app)

db.init_app(app)
migrate = Migrate(app, db)

def is_admin():
    """
    Проверяет, является ли пользователь системным администратором
    """
    if 'username' not in session:
        return False
    user = User.query.filter_by(username=session['username']).first()
    return user and user.is_admin

def is_manager():
    """
    Проверяет, является ли пользователь менеджером или администратором
    """
    if 'username' not in session:
        return False
    user = User.query.filter_by(username=session['username']).first()
    return user and (user.is_manager or user.is_admin)

def require_role(role):
    """
    Декоратор для проверки роли пользователя.
    Принимает как одну роль, так и список ролей.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'username' not in session:
                flash('Сначала войдите в систему.', 'warning')
                return redirect(url_for('login'))
            
            user = User.query.filter_by(username=session['username']).first()
            if not user:
                return render_template('error_403.html')
            
            # Если передан список ролей, проверяем каждую роль
            if isinstance(role, list):
                if not any(user.has_permission(r) for r in role):
                    return render_template('error_403.html')
            # Если передана одна роль, проверяем её
            elif not user.has_permission(role):
                return render_template('error_403.html')
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def wait_for_db():
    max_retries = 30  # Увеличиваем количество попыток
    retry_interval = 5
    
    for i in range(max_retries):
        try:
            # Сначала проверяем подключение к серверу MySQL
            db.engine.connect()
            # Если подключение успешно, пробуем создать таблицы
            db.create_all()
            print("Database connection successful!")
            return
        except OperationalError as e:
            if "Unknown database" in str(e):
                # Если база данных не существует, создаем её
                try:
                    # Подключаемся к MySQL без указания базы данных
                    engine = db.create_engine(f"mysql+pymysql://{config.DB_USER}:{config.DB_PASSWORD}@{config.DB_HOST}/")
                    with engine.connect() as conn:
                        conn.execute(f"CREATE DATABASE IF NOT EXISTS {config.DB_NAME}")
                    print(f"Database {config.DB_NAME} created successfully!")
                    # После создания базы данных пробуем снова создать таблицы
                    db.create_all()
                    return
                except Exception as create_db_error:
                    print(f"Error creating database: {create_db_error}")
            
            if i < max_retries - 1:
                print(f"Database connection failed. Retrying in {retry_interval} seconds...")
                time.sleep(retry_interval)
            else:
                raise

with app.app_context():
    wait_for_db()
    
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        full_name = request.form.get('full_name')

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Пользователь с таким логином уже существует!', 'danger')
            return redirect(url_for('register'))

        new_user = User(
            username=username,
            password_hash=generate_password_hash(password),
            role=Role.USER.value,
            full_name=full_name
        )
        db.session.add(new_user)
        db.session.commit()

        flash('Регистрация прошла успешно! Можете войти.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        id_card_code = request.form.get('id_card_code', '').strip()

        # Проверяем, что заполнены либо логин/пароль, либо код карты
        if not ((username and password) or id_card_code):
            flash('Пожалуйста, введите либо логин и пароль, либо код ID-карты.', 'warning')
            return redirect(url_for('login'))

        user = None
        auth_method = None

        # Пытаемся найти пользователя по логину
        if username and password:
            user = User.query.filter_by(username=username).first()
            if user and check_password_hash(user.password_hash, password):
                auth_method = 'password'

        # Если не нашли по логину/паролю, пробуем по коду карты
        if not user and id_card_code:
            user = User.query.filter_by(id_card_code=id_card_code).first()
            if user:
                auth_method = 'id_card'

        if user:
            # Проверяем двухфакторную аутентификацию
            if user.two_factor_enabled:
                if not (username and password and id_card_code):
                    flash('Включена двухфакторная аутентификация. Пожалуйста, введите логин, пароль и код ID-карты.', 'warning')
                    return redirect(url_for('login'))
                if auth_method != 'password' or not user.id_card_code or user.id_card_code != id_card_code:
                    flash('Неверные данные для двухфакторной аутентификации.', 'danger')
                    return redirect(url_for('login'))

            # Авторизация успешна
            session['username'] = user.username
            session['role'] = user.role

            # Логируем вход
            log = ActionLog(user_id=user.id, action=f'Logged in using {auth_method} authentication')
            db.session.add(log)
            db.session.commit()

            flash('Вы успешно авторизованы!', 'success')
            if is_admin():
                return redirect(url_for('admin_dashboard'))
            elif is_manager():
                return redirect(url_for('manager_dashboard'))
            else:
                return redirect(url_for('user_dashboard'))
        else:
            flash('Неверные данные для входа.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    if 'username' in session:
        user = User.query.filter_by(username=session['username']).first()
        if user:
            log = ActionLog(user_id=user.id, action='Logged out')
            db.session.add(log)
            db.session.commit()
    session.clear()
    flash('Вы вышли из системы.', 'info')
    return redirect(url_for('index'))

# -------------------- ПОЛЬЗОВАТЕЛЬ --------------------

@app.route('/user/dashboard')
def user_dashboard():
    if 'username' not in session:
        flash('Сначала войдите в систему.', 'warning')
        return redirect(url_for('login'))
    if is_admin():
        return redirect(url_for('admin_dashboard'))

    user = User.query.filter_by(username=session['username']).first()
    if not user:
        return render_template('error_403.html')

    # Показываем весь инвентарь (пример)
    inventory_list = InventoryItem.query.order_by(InventoryItem.inventory_number).all()
    return render_template('user_dashboard.html', user=user, inventory=inventory_list)

@app.route('/user/requests', methods=['GET', 'POST'])
def user_requests():
    if 'username' not in session:
        flash('Сначала войдите в систему.', 'warning')
        return redirect(url_for('login'))
    if is_admin():
        return render_template('error_403.html')

    user = User.query.filter_by(username=session['username']).first()
    if not user:
        return render_template('error_403.html')

    if request.method == 'POST':
        request_type = request.form.get('request_type')  # get_item / repair_item
        inventory_number = request.form.get('inventory_number', '').strip()
        comment = request.form.get('comment', '')

        new_request = UserRequest(
            user_id=user.id,
            request_type=request_type,
            inventory_number=inventory_number,
            comment=comment
        )
        db.session.add(new_request)
        db.session.commit()

        flash('Ваша заявка отправлена!', 'success')
        return redirect(url_for('user_requests'))

    user_requests_list = UserRequest.query.filter_by(user_id=user.id).all()
    return render_template('user_requests.html', user_requests=user_requests_list)

@app.route('/user/return_items')
def user_return_items():
    if 'username' not in session:
        flash('Сначала войдите в систему.', 'warning')
        return redirect(url_for('login'))
    if is_admin():
        return render_template('error_403.html')

    user = User.query.filter_by(username=session['username']).first()
    if not user:
        return render_template('error_403.html')

    # Предметы, закреплённые за пользователем
    assigned_items = InventoryItem.query.filter_by(assigned_to=user.id).all()
    return render_template('user_return_items.html', assigned_items=assigned_items)

@app.route('/user/return_item/<int:item_id>', methods=['POST'])
def return_item(item_id):
    if 'username' not in session:
        flash('Сначала войдите в систему.', 'warning')
        return redirect(url_for('login'))
    if is_admin():
        return render_template('error_403.html')

    user = User.query.filter_by(username=session['username']).first()
    item = InventoryItem.query.get_or_404(item_id)

    if item.assigned_to == user.id:
        item.assigned_to = None
        item.is_available = True
        db.session.commit()

        log = ActionLog(user_id=user.id, action=f"Returned item #{item.inventory_number}")
        db.session.add(log)
        db.session.commit()

        flash(f'Вы вернули предмет #{item.inventory_number}', 'success')
    else:
        flash('У вас нет прав возвращать этот предмет.', 'danger')

    return redirect(url_for('user_return_items'))

@app.route('/user/profile', methods=['GET', 'POST'])
def user_profile():
    if 'username' not in session:
        flash('Сначала войдите в систему.', 'warning')
        return redirect(url_for('login'))
    
    if is_admin():
        return redirect(url_for('admin_profile'))

    user = User.query.filter_by(username=session['username']).first()
    if not user:
        return render_template('error_403.html')

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_profile':
            new_full_name = request.form.get('full_name', '').strip()
            old_password = request.form.get('old_password', '').strip()
            new_password = request.form.get('new_password', '').strip()
            
            if new_full_name:
                user.full_name = new_full_name
            
            if old_password and new_password:
                if not check_password_hash(user.password_hash, old_password):
                    flash('Неверный текущий пароль.', 'danger')
                    return redirect(url_for('user_profile'))
                user.password_hash = generate_password_hash(new_password)
                flash('Пароль успешно изменен.', 'success')
            
            db.session.commit()
            flash('Профиль обновлен.', 'success')
            
        elif action == 'update_id_card':
            new_id_card_code = request.form.get('id_card_code', '').strip()
            if new_id_card_code:
                # Проверяем, не занят ли код другим пользователем
                existing_user = User.query.filter_by(id_card_code=new_id_card_code).first()
                if existing_user and existing_user.id != user.id:
                    flash('Этот код ID-карты уже используется другим пользователем.', 'danger')
                    return redirect(url_for('user_profile'))
                
                user.id_card_code = new_id_card_code
                db.session.commit()
                flash('Код ID-карты обновлен.', 'success')
            else:
                flash('Код ID-карты не может быть пустым.', 'warning')
                
        elif action == 'toggle_2fa':
            if not user.id_card_code:
                flash('Сначала необходимо установить код ID-карты.', 'warning')
                return redirect(url_for('user_profile'))
            
            user.two_factor_enabled = not user.two_factor_enabled
            db.session.commit()
            status = 'включена' if user.two_factor_enabled else 'отключена'
            flash(f'Двухфакторная аутентификация {status}.', 'success')

    return render_template('user_profile.html', user=user)

# -------------------- АДМИНИСТРАТОР --------------------

@app.route('/admin/dashboard')
def admin_dashboard():
    if not is_admin():
        return render_template('error_403.html')

    total_users = User.query.count()
    total_items = InventoryItem.query.count()
    total_requests = UserRequest.query.count()
    total_logs = SystemLog.query.count()

    return render_template('admin_dashboard.html',
                           total_users=total_users,
                           total_items=total_items,
                           total_requests=total_requests,
                           total_logs=total_logs)

@app.route('/admin/inventory')
@require_role([Role.ADMIN.value, Role.MANAGER.value])
def admin_inventory():
    """Управление инвентарем."""
    # Если пользователь менеджер, перенаправляем на страницу менеджера
    user = User.query.filter_by(username=session['username']).first()
    if user and user.is_manager:
        return redirect(url_for('manager_inventory'))

    inventory_list = InventoryItem.query.order_by(InventoryItem.inventory_number).all()
    return render_template('admin_inventory.html', inventory_list=inventory_list)

@app.route('/admin/create_item', methods=['GET', 'POST'])
def create_item():
    """
    Добавление нового предмета:
    - Проверка, что inventory_number уникален
    - Проверка на допустимые символы (цифры, '-', '.', '/')
    """
    if not is_admin():
        return render_template('error_403.html')

    if request.method == 'POST':
        inventory_number = request.form.get('inventory_number', '').strip()
        name = request.form.get('name', '').strip()
        condition = request.form.get('condition', 'new')

        # Регулярное выражение: разрешаем цифры, и символы - . /
        if not re.match(r'^[0-9\-\./]+$', inventory_number):
            flash('Инвентарный номер содержит недопустимые символы!', 'danger')
            return redirect(url_for('create_item'))

        # Проверка уникальности
        existing = InventoryItem.query.filter_by(inventory_number=inventory_number).first()
        if existing:
            flash(f'Инв. номер {inventory_number} уже существует!', 'danger')
            return redirect(url_for('create_item'))

        new_item = InventoryItem(
            inventory_number=inventory_number,
            name=name if name else "Без названия",
            condition=condition,
            is_available=True
        )
        db.session.add(new_item)
        db.session.commit()

        admin_user = User.query.filter_by(username=session['username']).first()
        log = ActionLog(user_id=admin_user.id, action=f"Created item #{inventory_number}")
        db.session.add(log)
        db.session.commit()

        flash('Инвентарь добавлен успешно!', 'success')
        return redirect(url_for('admin_inventory'))

    return render_template('create_item.html')

@app.route('/admin/edit_item/<int:item_id>', methods=['GET', 'POST'])
@require_role([Role.ADMIN.value, Role.MANAGER.value])
def edit_item(item_id):
    """Редактирование предмета инвентаря."""
    item = InventoryItem.query.get_or_404(item_id)

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        condition = request.form.get('condition')
        is_available_checkbox = request.form.get('is_available')
        assigned_user_id = request.form.get('assigned_user_id')

        is_available_val = True if is_available_checkbox == 'on' else False

        item.name = name if name else "Без названия"
        item.condition = condition

        if assigned_user_id and assigned_user_id != 'none':
            item.assigned_to = int(assigned_user_id)
            item.is_available = False
        else:
            item.assigned_to = None
            item.is_available = is_available_val

        db.session.commit()

        user = User.query.filter_by(username=session['username']).first()
        log = ActionLog(user_id=user.id, action=f"Edited item #{item.inventory_number}")
        db.session.add(log)
        db.session.commit()

        flash('Изменения сохранены!', 'success')
        return redirect(url_for('admin_inventory'))

    all_users = User.query.all()
    return render_template('edit_item.html', item=item, all_users=all_users)

@app.route('/admin/delete_item/<int:item_id>', methods=['GET', 'POST'])
@require_role([Role.ADMIN.value, Role.MANAGER.value])
def delete_item(item_id):
    """
    Удаление предмета инвентаря с подтверждением.
    GET -> Страница с предупреждением
    POST -> Удаляем из БД
    """
    item = InventoryItem.query.get_or_404(item_id)

    if request.method == 'POST':
        # Фактическое удаление
        user = User.query.filter_by(username=session['username']).first()

        # Логируем
        log = ActionLog(user_id=user.id, action=f"Deleted item #{item.inventory_number}")
        db.session.add(log)

        db.session.delete(item)
        db.session.commit()

        flash(f'Предмет #{item.inventory_number} удалён из системы.', 'success')
        return redirect(url_for('admin_inventory'))

    # Иначе рендерим страницу подтверждения
    return render_template('delete_item_confirm.html', item=item)

# -------------------- ЗАЯВКИ (APPROVE/REJECT) --------------------

@app.route('/admin/requests')
def admin_requests():
    if not is_admin():
        return render_template('error_403.html')

    requests_list = UserRequest.query.order_by(UserRequest.status, UserRequest.created_at.desc()).all()
    return render_template('admin_requests.html', requests=requests_list)

@app.route('/admin/request/<int:req_id>/approve', methods=['POST'])
def approve_request(req_id):
    if not is_admin():
        return render_template('error_403.html')

    user_req = UserRequest.query.get_or_404(req_id)
    if user_req.status != 'pending':
        flash('Заявка уже обработана.', 'warning')
        return redirect(url_for('admin_requests'))

    item = InventoryItem.query.filter_by(inventory_number=user_req.inventory_number).first()
    if not item:
        flash(f'Предмет #{user_req.inventory_number} не найден! Невозможно подтвердить.', 'danger')
        return redirect(url_for('admin_requests'))

    if user_req.request_type == 'get_item':
        # Проверяем, что предмет ещё доступен
        if not item.is_available:
            flash(f'Предмет #{item.inventory_number} уже недоступен!', 'warning')
        else:
            # Назначаем пользователю
            item.assigned_to = user_req.user_id
            item.is_available = False
            user_req.status = 'approved'
            flash(f'Заявка {req_id} подтверждена: предмет #{item.inventory_number} выдан пользователю.', 'success')
    elif user_req.request_type == 'repair_item':
        # Помечаем предмет недоступным, ставим condition='broken'
        item.is_available = False
        item.condition = 'broken'
        user_req.status = 'approved'
        flash(f'Заявка {req_id} подтверждена: предмет #{item.inventory_number} отправлен на ремонт.', 'success')
    else:
        flash('Неизвестный тип заявки.', 'danger')

    db.session.commit()
    return redirect(url_for('admin_requests'))

@app.route('/admin/request/<int:req_id>/reject', methods=['POST'])
def reject_request(req_id):
    if not is_admin():
        return render_template('error_403.html')

    user_req = UserRequest.query.get_or_404(req_id)
    if user_req.status != 'pending':
        flash('Заявка уже обработана.', 'warning')
        return redirect(url_for('admin_requests'))

    user_req.status = 'rejected'
    db.session.commit()
    flash(f'Заявка {req_id} отклонена.', 'info')
    return redirect(url_for('admin_requests'))

# -------------------- ПЛАН ЗАКУПОК --------------------

@app.route('/admin/purchase_planning', methods=['GET', 'POST'])
def purchase_planning():
    if not is_admin():
        return render_template('error_403.html')

    if request.method == 'POST':
        item_name = request.form.get('item_name', '').strip()
        supplier_name = request.form.get('supplier_name', '').strip()
        planned_price = float(request.form.get('planned_price', 0))

        plan = PurchasePlan(
            item_name=item_name if item_name else "Без названия",
            supplier_name=supplier_name,
            planned_price=planned_price,
            status='planned'
        )
        db.session.add(plan)
        db.session.commit()

        admin_user = User.query.filter_by(username=session['username']).first()
        log = ActionLog(user_id=admin_user.id, action=f"Created purchase plan: {item_name}")
        db.session.add(log)
        db.session.commit()

        flash('План закупки добавлен!', 'success')
        return redirect(url_for('purchase_planning'))

    plans = PurchasePlan.query.all()
    return render_template('purchase_planning.html', plans=plans)

@app.route('/admin/purchase_plan/<int:plan_id>/mark_received', methods=['POST'])
def mark_plan_received(plan_id):
    """
    Пометить план закупки как купленный (status='received').
    Сохраняем в истории (action logs).
    """
    if not is_admin():
        return render_template('error_403.html')

    plan = PurchasePlan.query.get_or_404(plan_id)
    plan.status = 'received'
    db.session.commit()

    admin_user = User.query.filter_by(username=session['username']).first()
    log = ActionLog(user_id=admin_user.id, action=f"Purchase plan received: {plan.item_name}")
    db.session.add(log)
    db.session.commit()

    flash(f'План закупки #{plan_id} помечен как купленный.', 'success')
    return redirect(url_for('purchase_planning'))

# -------------------- ОТЧЁТЫ (CSV, JSON) --------------------

@app.route('/admin/reports')
def reports():
    if not is_admin():
        return render_template('error_403.html')
    return render_template('reports.html')

import io
import csv

@app.route('/admin/export_csv')
def export_csv():
    if not is_admin():
        return render_template('error_403.html')

    items = InventoryItem.query.all()

    # Создаём "текстовый" буфер
    output_str = io.StringIO()
    writer = csv.writer(output_str, delimiter=',')
    writer.writerow(['ID', 'InventoryNumber', 'Name', 'Condition', 'is_available', 'assigned_to'])

    for item in items:
        writer.writerow([
            item.id,
            item.inventory_number,
            item.name,
            item.condition,
            'Да' if item.is_available else 'Нет',
            item.assigned_to if item.assigned_to else ''
        ])

    # Содержимое CSV в виде обычной строки
    csv_data = output_str.getvalue()

    # Кодируем в utf-8-sig
    bytes_buffer = io.BytesIO(csv_data.encode('utf-8-sig'))

    return send_file(
        bytes_buffer,
        mimetype='text/csv',
        as_attachment=True,
        download_name='inventory.csv'
    )


@app.route('/admin/export_json')
def export_json():
    if not is_admin():
        return render_template('error_403.html')

    items = InventoryItem.query.all()
    data = []
    for item in items:
        data.append({
            'id': item.id,
            'inventory_number': item.inventory_number,
            'name': item.name,
            'condition': item.condition,
            'is_available': item.is_available,
            'assigned_to': item.assigned_to
        })
    json_data = json.dumps(data, ensure_ascii=False, indent=2)
    return app.response_class(
        json_data,
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment;filename=inventory.json'}
    )

# -------------------- УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ --------------------

@app.route('/admin/users')
@require_role(Role.ADMIN.value)
def admin_users():
    users = User.query.all()
    roles = [role.value for role in Role]
    return render_template('admin_users.html', users=users, roles=roles)

@app.route('/admin/update_user_role/<int:user_id>', methods=['POST'])
@require_role(Role.ADMIN.value)
def update_user_role(user_id):
    user = User.query.get_or_404(user_id)
    new_role = request.form.get('role')
    
    if new_role not in [role.value for role in Role]:
        flash('Некорректная роль.', 'danger')
        return redirect(url_for('admin_users'))
    
    # Нельзя изменить роль системного администратора
    if user.is_admin:
        flash('Нельзя изменить роль системного администратора.', 'danger')
        return redirect(url_for('admin_users'))
    
    old_role = user.role
    user.role = new_role
    db.session.commit()
    
    log = ActionLog(
        user_id=User.query.filter_by(username=session['username']).first().id,
        action=f'Changed role of user {user.username} from {old_role} to {new_role}'
    )
    db.session.add(log)
    db.session.commit()
    
    flash(f'Роль пользователя {user.username} изменена на {new_role}.', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@require_role(Role.ADMIN.value)
def delete_user(user_id):
    user_to_delete = User.query.get_or_404(user_id)
    
    # Нельзя удалить системного администратора
    if user_to_delete.is_admin:
        flash('Нельзя удалить системного администратора.', 'danger')
        return redirect(url_for('admin_users'))
    
    # Освобождаем все предметы, закреплённые за этим пользователем
    for item in user_to_delete.inventory:
        item.assigned_to = None
        item.is_available = True

    db.session.commit()
    db.session.delete(user_to_delete)
    db.session.commit()
    
    log = ActionLog(
        user_id=User.query.filter_by(username=session['username']).first().id,
        action=f'Deleted user {user_to_delete.username}'
    )
    db.session.add(log)
    db.session.commit()
    
    flash('Пользователь и все связанные предметы освобождены.', 'success')
    return redirect(url_for('admin_users'))

@app.route('/faq')
def faq():
    return render_template('faq.html')

# -------------------- Запуск --------------------

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80, debug=True)

@app.after_request
def log_request(response):
    """Middleware для логирования всех запросов"""
    # Получаем информацию о запросе
    ip = request.remote_addr
    user_agent = request.headers.get('User-Agent', '')
    path = request.path
    method = request.method
    
    # Сохраняем в базу
    log = SystemLog(
        ip_address=ip,
        user_agent=user_agent,
        path=path,
        method=method,
        status_code=response.status_code,
        response_time=time.time() - request.start_time if hasattr(request, 'start_time') else None
    )
    db.session.add(log)
    db.session.commit()
    
    return response

@app.before_request
def before_request():
    """Сохраняем время начала запроса для подсчета времени ответа"""
    request.start_time = time.time()

@app.route('/admin/system_logs', methods=['GET', 'POST'])
def system_logs():
    if not is_admin():
        return render_template('error_403.html')
    
    # Обработка удаления логов
    if request.method == 'POST' and request.form.get('action') == 'delete_logs':
        try:
            SystemLog.query.delete()
            db.session.commit()
            # Инвалидируем кэш после удаления логов
            cache.delete_many(['ip_summary', 'ip_summary_count'])
            flash('Все логи успешно удалены', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при удалении логов: {str(e)}', 'danger')
        return redirect(url_for('system_logs'))
    
    # Получаем параметры пагинации и сортировки
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    sort_by = request.args.get('sort_by', 'last_activity')
    sort_direction = request.args.get('sort_direction', 'desc')
    
    # Кэшируем общее количество IP-адресов
    total_ips = cache.get('ip_summary_count')
    if total_ips is None:
        total_ips = db.session.query(SystemLog.ip_address).distinct().count()
        cache.set('ip_summary_count', total_ips, timeout=300)
    
    # Кэшируем сводку по IP-адресам
    cache_key = f'ip_summary_{page}_{per_page}_{sort_by}_{sort_direction}'
    ip_summary = cache.get(cache_key)
    
    if ip_summary is None:
        # Базовый запрос для получения уникальных IP-адресов с их статистикой
        ip_query = db.session.query(
            SystemLog.ip_address,
            db.func.min(SystemLog.timestamp).label('first_activity'),
            db.func.max(SystemLog.timestamp).label('last_activity'),
            db.func.count(SystemLog.id).label('total_requests')
        ).group_by(SystemLog.ip_address)
        
        # Применяем сортировку
        if sort_by == 'first_activity':
            ip_query = ip_query.order_by(
                db.desc('first_activity') if sort_direction == 'desc' else db.asc('first_activity')
            )
        elif sort_by == 'last_activity':
            ip_query = ip_query.order_by(
                db.desc('last_activity') if sort_direction == 'desc' else db.asc('last_activity')
            )
        elif sort_by == 'total_requests':
            ip_query = ip_query.order_by(
                db.desc('total_requests') if sort_direction == 'desc' else db.asc('total_requests')
            )
        
        # Применяем пагинацию
        ip_query = ip_query.offset((page - 1) * per_page).limit(per_page)
        
        ip_summary = {}
        for ip, first_activity, last_activity, total_requests in ip_query.all():
            # Получаем статистику по кодам ответов для каждого IP
            status_codes = db.session.query(
                SystemLog.status_code,
                db.func.count(SystemLog.id)
            ).filter_by(ip_address=ip).group_by(SystemLog.status_code).all()
            
            ip_summary[ip] = {
                'first_activity': first_activity,
                'last_activity': last_activity,
                'total_requests': total_requests,
                'status_codes': dict(status_codes),
                'unique_paths': db.session.query(SystemLog.path)
                    .filter_by(ip_address=ip)
                    .distinct()
                    .count()
            }
        
        # Кэшируем результаты на 5 минут
        cache.set(cache_key, ip_summary, timeout=300)
    
    # Вычисляем общее количество страниц
    total_pages = (total_ips + per_page - 1) // per_page
    
    # Вычисляем диапазон показанных IP-адресов
    start_ip = (page - 1) * per_page + 1
    end_ip = min(page * per_page, total_ips)
    
    # Вычисляем диапазон страниц для пагинации
    pagination_start = max(1, page - 2)
    pagination_end = min(total_pages + 1, page + 3)
    pagination_range = range(pagination_start, pagination_end)
    
    return render_template('system_logs.html',
                         ip_summary=ip_summary,
                         sort_by=sort_by,
                         sort_direction=sort_direction,
                         page=page,
                         per_page=per_page,
                         total_pages=total_pages,
                         total_ips=total_ips,
                         start_ip=start_ip,
                         end_ip=end_ip,
                         pagination_range=pagination_range)

@app.route('/admin/ip_details/<ip>')
def ip_details(ip):
    """Эндпоинт для получения детальной информации по IP (без пагинации и кэширования)"""
    if not is_admin():
        return render_template('error_403.html')
    
    logs = SystemLog.query.filter_by(ip_address=ip).order_by(SystemLog.timestamp.desc()).all()
    total_logs = len(logs)
    return render_template('ip_details.html',
                         ip=ip,
                         logs=logs,
                         total_logs=total_logs)

@app.route('/admin/export_logs')
def export_logs():
    """Экспорт логов в CSV файл"""
    if not is_admin():
        return render_template('error_403.html')
    
    # Получаем все логи
    logs = SystemLog.query.order_by(SystemLog.timestamp.desc()).all()
    
    # Создаём CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Заголовки
    writer.writerow(['Timestamp', 'IP Address', 'Method', 'Path', 'Status Code', 
                    'Response Time', 'User Agent'])
    
    # Данные
    for log in logs:
        writer.writerow([
            log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            log.ip_address,
            log.method,
            log.path,
            log.status_code,
            f"{log.response_time:.3f}s" if log.response_time else '',
            log.user_agent
        ])
    
    # Подготавливаем ответ
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'system_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )

@app.route('/admin/profile', methods=['GET', 'POST'])
def admin_profile():
    if not is_admin():
        return render_template('error_403.html')

    user = User.query.filter_by(username=session['username']).first()
    if not user:
        return render_template('error_403.html')

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_profile':
            new_full_name = request.form.get('full_name', '').strip()
            old_password = request.form.get('old_password', '').strip()
            new_password = request.form.get('new_password', '').strip()
            
            if new_full_name:
                user.full_name = new_full_name
            
            if old_password and new_password:
                if not check_password_hash(user.password_hash, old_password):
                    flash('Неверный текущий пароль.', 'danger')
                    return redirect(url_for('admin_profile'))
                user.password_hash = generate_password_hash(new_password)
                flash('Пароль успешно изменен.', 'success')
            
            db.session.commit()
            flash('Профиль обновлен.', 'success')
            
        elif action == 'update_id_card':
            new_id_card_code = request.form.get('id_card_code', '').strip()
            if new_id_card_code:
                # Проверяем, не занят ли код другим пользователем
                existing_user = User.query.filter_by(id_card_code=new_id_card_code).first()
                if existing_user and existing_user.id != user.id:
                    flash('Этот код ID-карты уже используется другим пользователем.', 'danger')
                    return redirect(url_for('admin_profile'))
                
                user.id_card_code = new_id_card_code
                db.session.commit()
                flash('Код ID-карты обновлен.', 'success')
            else:
                flash('Код ID-карты не может быть пустым.', 'warning')
                
        elif action == 'toggle_2fa':
            if not user.id_card_code:
                flash('Сначала необходимо установить код ID-карты.', 'warning')
                return redirect(url_for('admin_profile'))
            
            user.two_factor_enabled = not user.two_factor_enabled
            db.session.commit()
            status = 'включена' if user.two_factor_enabled else 'отключена'
            flash(f'Двухфакторная аутентификация {status}.', 'success')

    return render_template('admin_profile.html', user=user)

# Обновляем маршруты для менеджеров
@app.route('/manager/dashboard')
@require_role(Role.MANAGER.value)
def manager_dashboard():
    user = User.query.filter_by(username=session['username']).first()
    inventory_list = InventoryItem.query.order_by(InventoryItem.inventory_number).all()
    requests = UserRequest.query.order_by(UserRequest.created_at.desc()).all()
    return render_template('manager_dashboard.html', user=user, inventory=inventory_list, requests=requests)

@app.route('/manager/inventory')
@require_role(Role.MANAGER.value)
def manager_inventory():
    user = User.query.filter_by(username=session['username']).first()
    inventory_list = InventoryItem.query.order_by(InventoryItem.inventory_number).all()
    return render_template('manager_inventory.html', user=user, inventory=inventory_list)

@app.route('/manager/requests')
@require_role(Role.MANAGER.value)
def manager_requests():
    user = User.query.filter_by(username=session['username']).first()
    requests = UserRequest.query.order_by(UserRequest.created_at.desc()).all()
    return render_template('manager_requests.html', user=user, requests=requests)

@app.route('/manager/add_inventory_item', methods=['POST'])
@require_role(Role.MANAGER.value)
def add_inventory_item():
    """Добавление нового предмета инвентаря менеджером."""
    if request.method == 'POST':
        inventory_number = request.form.get('inventory_number', '').strip()
        name = request.form.get('name', '').strip()
        condition = request.form.get('condition', 'new')

        # Проверка на допустимые символы (цифры, '-', '.', '/')
        if not re.match(r'^[0-9\-\./]+$', inventory_number):
            flash('Инвентарный номер содержит недопустимые символы!', 'danger')
            return redirect(url_for('manager_inventory'))

        # Проверка уникальности
        existing = InventoryItem.query.filter_by(inventory_number=inventory_number).first()
        if existing:
            flash(f'Инв. номер {inventory_number} уже существует!', 'danger')
            return redirect(url_for('manager_inventory'))

        new_item = InventoryItem(
            inventory_number=inventory_number,
            name=name if name else "Без названия",
            condition=condition,
            is_available=True
        )
        db.session.add(new_item)
        db.session.commit()

        manager = User.query.filter_by(username=session['username']).first()
        log = ActionLog(user_id=manager.id, action=f"Created item #{inventory_number}")
        db.session.add(log)
        db.session.commit()

        flash('Инвентарь добавлен успешно!', 'success')
        return redirect(url_for('manager_inventory'))

@app.route('/manager/update_item_condition/<int:item_id>', methods=['POST'])
@require_role(Role.MANAGER.value)
def update_item_condition(item_id):
    """Обновление состояния предмета инвентаря менеджером."""
    item = InventoryItem.query.get_or_404(item_id)
    new_condition = request.form.get('condition')
    
    if new_condition in ['new', 'in_use', 'broken', 'decommissioned']:
        old_condition = item.condition
        item.condition = new_condition
        
        # Если предмет списан, делаем его недоступным
        if new_condition == 'decommissioned':
            item.is_available = False
            item.assigned_to = None
        
        db.session.commit()
        
        manager = User.query.filter_by(username=session['username']).first()
        log = ActionLog(
            user_id=manager.id,
            action=f"Updated item #{item.inventory_number} condition from {old_condition} to {new_condition}"
        )
        db.session.add(log)
        db.session.commit()
        
        flash(f'Состояние предмета #{item.inventory_number} обновлено!', 'success')
    else:
        flash('Недопустимое состояние предмета!', 'danger')
    
    return redirect(url_for('manager_inventory'))

@app.route('/manager/edit_item/<int:item_id>', methods=['GET', 'POST'])
@require_role(Role.MANAGER.value)
def manager_edit_item(item_id):
    """Редактирование предмета инвентаря менеджером."""
    item = InventoryItem.query.get_or_404(item_id)

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        condition = request.form.get('condition')
        is_available_checkbox = request.form.get('is_available')
        assigned_user_id = request.form.get('assigned_user_id')

        is_available_val = True if is_available_checkbox == 'on' else False

        item.name = name if name else "Без названия"
        item.condition = condition

        if assigned_user_id and assigned_user_id != 'none':
            item.assigned_to = int(assigned_user_id)
            item.is_available = False
        else:
            item.assigned_to = None
            item.is_available = is_available_val

        db.session.commit()

        manager = User.query.filter_by(username=session['username']).first()
        log = ActionLog(user_id=manager.id, action=f"Edited item #{item.inventory_number}")
        db.session.add(log)
        db.session.commit()

        flash('Изменения сохранены!', 'success')
        return redirect(url_for('manager_inventory'))

    all_users = User.query.all()
    return render_template('edit_item.html', item=item, all_users=all_users)

@app.route('/manager/delete_item/<int:item_id>', methods=['GET', 'POST'])
@require_role(Role.MANAGER.value)
def manager_delete_item(item_id):
    """Удаление предмета инвентаря менеджером."""
    item = InventoryItem.query.get_or_404(item_id)

    if request.method == 'POST':
        manager = User.query.filter_by(username=session['username']).first()
        log = ActionLog(user_id=manager.id, action=f"Deleted item #{item.inventory_number}")
        db.session.add(log)

        db.session.delete(item)
        db.session.commit()

        flash(f'Предмет #{item.inventory_number} удалён из системы.', 'success')
        return redirect(url_for('manager_inventory'))

    return render_template('delete_item_confirm.html', item=item)

@app.route('/manager/approve_request/<int:req_id>', methods=['POST'])
@require_role(Role.MANAGER.value)
def manager_approve_request(req_id):
    """Одобрение заявки менеджером."""
    user_req = UserRequest.query.get_or_404(req_id)
    if user_req.status != 'pending':
        flash('Заявка уже обработана.', 'warning')
        return redirect(url_for('manager_requests'))

    item = InventoryItem.query.filter_by(inventory_number=user_req.inventory_number).first()
    if not item:
        flash(f'Предмет #{user_req.inventory_number} не найден! Невозможно подтвердить.', 'danger')
        return redirect(url_for('manager_requests'))

    if user_req.request_type == 'get_item':
        if not item.is_available:
            flash(f'Предмет #{item.inventory_number} уже недоступен!', 'warning')
        else:
            item.assigned_to = user_req.user_id
            item.is_available = False
            user_req.status = 'approved'
            flash(f'Заявка {req_id} подтверждена: предмет #{item.inventory_number} выдан пользователю.', 'success')
    elif user_req.request_type == 'repair_item':
        item.is_available = False
        item.condition = 'broken'
        user_req.status = 'approved'
        flash(f'Заявка {req_id} подтверждена: предмет #{item.inventory_number} отправлен на ремонт.', 'success')
    else:
        flash('Неизвестный тип заявки.', 'danger')

    db.session.commit()
    return redirect(url_for('manager_requests'))

@app.route('/manager/reject_request/<int:req_id>', methods=['POST'])
@require_role(Role.MANAGER.value)
def manager_reject_request(req_id):
    """Отклонение заявки менеджером."""
    user_req = UserRequest.query.get_or_404(req_id)
    if user_req.status != 'pending':
        flash('Заявка уже обработана.', 'warning')
        return redirect(url_for('manager_requests'))

    user_req.status = 'rejected'
    db.session.commit()

    manager = User.query.filter_by(username=session['username']).first()
    log = ActionLog(user_id=manager.id, action=f"Rejected request #{req_id}")
    db.session.add(log)
    db.session.commit()

    flash(f'Заявка {req_id} отклонена.', 'success')
    return redirect(url_for('manager_requests'))

@app.route('/manager/reports')
@require_role(Role.MANAGER.value)
def manager_reports():
    """Страница отчётов для менеджера."""
    return render_template('reports.html')

@app.route('/manager/export_csv')
@require_role(Role.MANAGER.value)
def manager_export_csv():
    """Экспорт инвентаря в CSV для менеджера."""
    items = InventoryItem.query.all()

    output_str = io.StringIO()
    writer = csv.writer(output_str, delimiter=',')
    writer.writerow(['ID', 'InventoryNumber', 'Name', 'Condition', 'is_available', 'assigned_to'])

    for item in items:
        writer.writerow([
            item.id,
            item.inventory_number,
            item.name,
            item.condition,
            'Да' if item.is_available else 'Нет',
            item.assigned_to if item.assigned_to else ''
        ])

    csv_data = output_str.getvalue()
    bytes_buffer = io.BytesIO(csv_data.encode('utf-8-sig'))

    return send_file(
        bytes_buffer,
        mimetype='text/csv',
        as_attachment=True,
        download_name='inventory.csv'
    )

@app.route('/manager/export_json')
@require_role(Role.MANAGER.value)
def manager_export_json():
    """Экспорт инвентаря в JSON для менеджера."""
    items = InventoryItem.query.all()
    data = []
    for item in items:
        data.append({
            'id': item.id,
            'inventory_number': item.inventory_number,
            'name': item.name,
            'condition': item.condition,
            'is_available': item.is_available,
            'assigned_to': item.assigned_to
        })
    json_data = json.dumps(data, ensure_ascii=False, indent=2)
    return app.response_class(
        json_data,
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment;filename=inventory.json'}
    )

@app.route('/manager/return_item/<int:item_id>', methods=['POST'])
@require_role(Role.MANAGER.value)
def manager_return_item(item_id):
    """Возврат предмета менеджером."""
    item = InventoryItem.query.get_or_404(item_id)
    
    # Сохраняем старые значения для лога
    old_assigned_to = item.assigned_to
    old_condition = item.condition
    
    # Возвращаем предмет
    item.assigned_to = None
    item.is_available = True
    
    db.session.commit()
    
    # Логируем действие
    manager = User.query.filter_by(username=session['username']).first()
    assigned_user = User.query.get(old_assigned_to) if old_assigned_to else None
    log = ActionLog(
        user_id=manager.id,
        action=f"Returned item #{item.inventory_number} from user {assigned_user.username if assigned_user else 'unknown'} (condition: {old_condition})"
    )
    db.session.add(log)
    db.session.commit()
    
    flash(f'Предмет #{item.inventory_number} возвращен!', 'success')
    return redirect(url_for('manager_inventory'))