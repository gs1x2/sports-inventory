import os
import re
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from io import BytesIO
import csv
import json
import io
from models import db, User, InventoryItem, PurchasePlan, UserRequest, ActionLog
import config

app = Flask(__name__)
app.config['SECRET_KEY'] = config.SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = config.SQLALCHEMY_TRACK_MODIFICATIONS

db.init_app(app)

def is_admin():
    """
    Проверяем, что:
      1) Пользователь авторизован в сессии (session['username'] есть)
      2) session['username'] присутствует в списке ADMIN_LOGINS из config
    """
    return 'username' in session and session['username'] in config.ADMIN_LOGINS


with app.app_context():
    db.create_all()
    
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
            role='user',
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
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            # Авторизация успешна
            session['username'] = user.username
            session['role'] = user.role

            # Логируем вход
            log = ActionLog(user_id=user.id, action='Logged in')
            db.session.add(log)
            db.session.commit()

            flash('Вы успешно авторизованы!', 'success')
            if is_admin():
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('user_dashboard'))
        else:
            flash('Неправильный логин или пароль.', 'danger')
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

# -------------------- АДМИНИСТРАТОР --------------------

@app.route('/admin/dashboard')
def admin_dashboard():
    if not is_admin():
        return render_template('error_403.html')

    total_users = User.query.count()
    total_items = InventoryItem.query.count()
    total_requests = UserRequest.query.count()

    return render_template('admin_dashboard.html',
                           total_users=total_users,
                           total_items=total_items,
                           total_requests=total_requests)

@app.route('/admin/inventory')
def admin_inventory():
    """Список всего инвентаря для админа."""
    if not is_admin():
        return render_template('error_403.html')
    items = InventoryItem.query.order_by(InventoryItem.inventory_number).all()
    return render_template('admin_inventory.html', items=items)

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
def edit_item(item_id):
    if not is_admin():
        return render_template('error_403.html')

    item = InventoryItem.query.get_or_404(item_id)

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        condition = request.form.get('condition')
        is_available_checkbox = request.form.get('is_available')  # 'on' если стоит галочка
        assigned_user_id = request.form.get('assigned_user_id')

        # Если галочка стоит, is_available_val=True, иначе False
        is_available_val = True if is_available_checkbox == 'on' else False

        # Обновляем название и состояние
        item.name = name if name else "Без названия"
        item.condition = condition

        if assigned_user_id and assigned_user_id != 'none':
            # Если выбрали пользователя, значит предмет выдан:
            item.assigned_to = int(assigned_user_id)
            # Если предмет кому-то назначен, то он всегда недоступен
            item.is_available = False
        else:
            # Нет владельца
            item.assigned_to = None
            # В таком случае уважаем чекбокс "доступен / недоступен"
            item.is_available = is_available_val

        db.session.commit()

        admin_user = User.query.filter_by(username=session['username']).first()
        log = ActionLog(user_id=admin_user.id, action=f"Edited item #{item.inventory_number}")
        db.session.add(log)
        db.session.commit()

        flash('Изменения сохранены!', 'success')
        return redirect(url_for('admin_inventory'))

    all_users = User.query.all()
    return render_template('edit_item.html', item=item, all_users=all_users)


    all_users = User.query.all()
    return render_template('edit_item.html', item=item, all_users=all_users)

@app.route('/admin/delete_item/<int:item_id>', methods=['GET', 'POST'])
def delete_item(item_id):
    """
    Удаление предмета инвентаря с подтверждением.
    GET -> Страница с предупреждением
    POST -> Удаляем из БД
    """
    if not is_admin():
        return render_template('error_403.html')

    item = InventoryItem.query.get_or_404(item_id)

    if request.method == 'POST':
        # Фактическое удаление
        admin_user = User.query.filter_by(username=session['username']).first()

        # Логируем
        log = ActionLog(user_id=admin_user.id, action=f"Deleted item #{item.inventory_number}")
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
def admin_users():
    if not is_admin():
        return render_template('error_403.html')
    users = User.query.all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    if not is_admin():
        return render_template('error_403.html')

    user_to_delete = User.query.get_or_404(user_id)
    # Освобождаем все предметы, закреплённые за этим пользователем
    for item in user_to_delete.inventory:
        item.assigned_to = None
        item.is_available = True

    db.session.commit()

    db.session.delete(user_to_delete)
    db.session.commit()
    flash('Пользователь и все связанные предметы освобождены.', 'success')
    return redirect(url_for('admin_users'))

# -------------------- Запуск --------------------

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)