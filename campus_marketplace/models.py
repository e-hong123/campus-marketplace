from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    wechat = db.Column(db.String(50), nullable=True, default='')
    qq = db.Column(db.String(20), nullable=True, default='')
    avatar = db.Column(db.String(200), default='default_avatar.png')
    is_admin = db.Column(db.Boolean, default=False)          # 是否为管理员
    create_time = db.Column(db.DateTime, default=datetime.now)

    items = db.relationship('Item', backref='seller', lazy=True)
    cart_items = db.relationship('Cart', backref='user', lazy=True)
    orders = db.relationship('Order', backref='buyer', lazy=True)
    notifications = db.relationship('Notification', backref='user', lazy=True)
    reports_made = db.relationship('Report', foreign_keys='Report.reporter_id', backref='reporter', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'phone': self.phone,
            'wechat': self.wechat,
            'qq': self.qq,
            'avatar': self.avatar,
            'is_admin': self.is_admin,
            'create_time': self.create_time.strftime('%Y-%m-%d')
        }


class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    image_path = db.Column(db.String(200), nullable=False)
    create_time = db.Column(db.DateTime, default=datetime.now)
    is_sold = db.Column(db.Boolean, default=False)
    is_top = db.Column(db.Boolean, default=False)            # 是否置顶
    is_active = db.Column(db.Boolean, default=True)          # 商品是否有效（下架后为False）

    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    cart_entries = db.relationship('Cart', backref='item', lazy=True)
    orders = db.relationship('Order', backref='item', lazy=True)
    reports = db.relationship('Report', backref='item', lazy=True)

    def to_dict(self, hide_seller_info=False):
        data = {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'price': self.price,
            'category': self.category,
            'image_path': self.image_path,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M'),
            'is_sold': self.is_sold,
            'is_top': self.is_top,
            'is_active': self.is_active,
            'seller_id': self.seller_id,
            'seller_username': self.seller.username
        }
        if not hide_seller_info:
            data['seller_phone'] = self.seller.phone
            data['seller_wechat'] = self.seller.wechat
            data['seller_qq'] = self.seller.qq
        return data


class Cart(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    add_time = db.Column(db.DateTime, default=datetime.now)


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    order_time = db.Column(db.DateTime, default=datetime.now)
    status = db.Column(db.String(20), default='待发货')


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    send_time = db.Column(db.DateTime, default=datetime.now)
    is_read = db.Column(db.Boolean, default=False)  # 消息是否已读


class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    reason = db.Column(db.String(200), nullable=False)
    report_time = db.Column(db.DateTime, default=datetime.now)
    status = db.Column(db.String(20), default='待处理')   # 待处理/已处理
    handle_time = db.Column(db.DateTime, nullable=True)
    handle_result = db.Column(db.String(200), nullable=True)   # 处理结果说明
    handle_action = db.Column(db.String(50), nullable=True)    # 下架/驳回


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    create_time = db.Column(db.DateTime, default=datetime.now)
    link = db.Column(db.String(200), nullable=True)
    detail = db.Column(db.Text, nullable=True)   # 新增



# 浏览历史表
class BrowseHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer,
                        db.ForeignKey('user.id'),
                        nullable=False)

    item_id = db.Column(db.Integer,
                        db.ForeignKey('item.id'),
                        nullable=False)

    browse_time = db.Column(db.DateTime,
                            default=datetime.now)

    user = db.relationship('User', backref='browse_histories')
    item = db.relationship('Item', backref='browse_histories')