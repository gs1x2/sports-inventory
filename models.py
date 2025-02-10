from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    """
    Модель пользователя
    """
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='user')
    full_name = db.Column(db.String(100), nullable=True)

    def __repr__(self):
        return f'<User {self.username}>'

class InventoryItem(db.Model):
    """
    Модель спортивного инвентаря
    - inventory_number: уникальный инвентарный номер (допускаем цифры и символы - . /)
    - name: название (например, "Мяч футбольный")
    - condition: new / in_use / broken / decommissioned
    - is_available: True, если предмет свободен
    - assigned_to: FK на user.id, если предмет выдан
    """
    __tablename__ = 'inventory_items'
    
    id = db.Column(db.Integer, primary_key=True)
    inventory_number = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False, default="Unnamed")
    condition = db.Column(db.String(50), default='new')  
    is_available = db.Column(db.Boolean, default=True)
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    assigned_user = db.relationship('User', backref='inventory', foreign_keys=[assigned_to])

    def __repr__(self):
        return f'<InventoryItem #{self.inventory_number} {self.name}>'

class PurchasePlan(db.Model):
    """
    Модель планирования закупок
    - можно пометить status='received', когда фактически куплено
    """
    __tablename__ = 'purchase_plans'
    
    id = db.Column(db.Integer, primary_key=True)
    item_name = db.Column(db.String(100), nullable=False)
    supplier_name = db.Column(db.String(100), nullable=True)
    planned_price = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(50), default='planned')

    def __repr__(self):
        return f'<PurchasePlan {self.item_name} - {self.status}>'

class UserRequest(db.Model):
    """
    Модель заявок от пользователя
    - request_type: get_item / repair_item
    - inventory_number: строка
    - status: pending / approved / rejected
    """
    __tablename__ = 'user_requests'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    request_type = db.Column(db.String(50), nullable=False)
    inventory_number = db.Column(db.String(50), nullable=False)
    comment = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='requests')

    def __repr__(self):
        return f'<UserRequest {self.request_type} - {self.inventory_number} - {self.status}>'

class ActionLog(db.Model):
    """
    Логирование действий
    user_id -> ondelete='SET NULL', чтобы не было IntegrityError при удалении пользователя
    """
    __tablename__ = 'action_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, 
        db.ForeignKey('users.id', ondelete='SET NULL'), 
        nullable=True
    )
    action = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='action_logs', passive_deletes=True)

    def __repr__(self):
        return f'<ActionLog {self.action} by User {self.user_id}>'
