import os
import re
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort
from werkzeug.utils import secure_filename
from models import db, User, Item, Cart, Order, Report, Notification

app = Flask(__name__)
app.secret_key = 'campus_marketplace_secret_key_2024'

# 数据库配置
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///marketplace.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 图片上传配置
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

db.init_app(app)

# 创建所有表并创建默认管理员
with app.app_context():
    db.create_all()
    # 检查管理员是否已存在
    if not User.query.filter_by(username='admin111').first():
        admin = User(
            username='admin111',
            password='admin111',
            phone='00000000000',
            wechat='',
            qq='',
            is_admin=True
        )
        db.session.add(admin)
        db.session.commit()
        print("默认管理员已创建: admin111 / admin111")

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_user_input(username, phone, wechat, qq, password):
    errors = []
    if not re.match(r'^[a-zA-Z0-9_]{3,20}$', username):
        errors.append('用户名必须是3-20位字母、数字或下划线')
    if not re.match(r'^1[3-9]\d{9}$', phone):
        errors.append('请输入有效的11位手机号')
    if wechat and not re.match(r'^[a-zA-Z0-9_-]{1,30}$', wechat):
        errors.append('微信号只能包含字母、数字、下划线、横线，且不超过30位')
    if qq and not re.match(r'^\d{5,12}$', qq):
        errors.append('QQ号必须为5-12位数字')
    if not wechat and not qq:
        errors.append('请至少填写微信号或QQ号中的一种联系方式')
    if len(password) < 6 or len(password) > 20:
        errors.append('密码长度必须在6-20位之间')
    return errors

def search_items(keyword, category=None, admin_view=False):
    if admin_view:
        query = Item.query
    else:
        query = Item.query.filter_by(is_active=True, is_sold=False)
    if category and category != 'all':
        query = query.filter_by(category=category)
    if keyword:
        pattern = re.compile(f'.*{re.escape(keyword)}.*', re.IGNORECASE)
        all_items = query.all()
        search_results = []
        for item in all_items:
            if pattern.search(item.title) or pattern.search(item.description):
                search_results.append(item)
        # 置顶商品排在前面
        search_results.sort(key=lambda x: (not x.is_top, x.create_time), reverse=False)
        return search_results
    # 直接按置顶降序、创建时间降序排列
    return query.order_by(Item.is_top.desc(), Item.create_time.desc()).all()

def get_cart_count():
    if 'user_id' in session:
        return Cart.query.filter_by(user_id=session['user_id']).count()
    return 0

def get_unread_notification_count():
    if 'user_id' in session:
        return Notification.query.filter_by(user_id=session['user_id'], is_read=False).count()
    return 0

def send_notification(user_id, content, link=None, detail=None):
    notif = Notification(user_id=user_id, content=content, link=link, detail=detail)
    db.session.add(notif)
    db.session.commit()

def delete_related_cart_items(item_id, reason):
    """商品下架时，从所有用户的购物车中移除并发送通知"""
    carts = Cart.query.filter_by(item_id=item_id).all()
    for cart in carts:
        send_notification(cart.user_id, f"购物车中的商品「{Item.query.get(item_id).title}」已被下架，原因：{reason}")
    Cart.query.filter_by(item_id=item_id).delete()
    db.session.commit()

def get_unhandled_reports_count():
    """获取待处理的举报数量（仅管理员可见）"""
    if session.get('is_admin'):
        return Report.query.filter_by(status='待处理').count()
    return 0

@app.context_processor
def inject_common():
    return dict(
        cart_count=get_cart_count(),
        notif_count=get_unread_notification_count(),   # 注意：函数名正确
        is_admin=session.get('is_admin', False),
        unhandled_reports_count=get_unhandled_reports_count()   # 新增
    )

# -------------------------- 基础路由 --------------------------
@app.route('/')
def index():
    keyword = request.args.get('keyword', '')
    category = request.args.get('category', 'all')
    items = search_items(keyword, category)
    item_dicts = [item.to_dict(hide_seller_info=True) for item in items]
    return render_template('index.html', items=item_dicts, keyword=keyword, category=category)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        phone = request.form['phone']
        wechat = request.form.get('wechat', '').strip()
        qq = request.form.get('qq', '').strip()
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        errors = validate_user_input(username, phone, wechat, qq, password)

        if password != confirm_password:
            errors.append('两次输入的密码不一致')

        # 检查用户名是否已存在
        if User.query.filter_by(username=username).first():
            errors.append('该用户名已被注册')

        # 检查手机号是否已存在
        if User.query.filter_by(phone=phone).first():
            errors.append('该手机号已被注册')

        # 检查微信号是否已存在（如果填写了）
        if wechat and User.query.filter_by(wechat=wechat).first():
            errors.append('该微信号已被注册')

        # 检查QQ号是否已存在（如果填写了）
        if qq and User.query.filter_by(qq=qq).first():
            errors.append('该QQ号已被注册')

        if errors:
            # 传回用户已填写的非密码字段，用于模板回填
            return render_template('register.html',
                                   errors=errors,
                                   username=username,
                                   phone=phone,
                                   wechat=wechat,
                                   qq=qq)

        # 注册成功：创建新用户
        new_user = User(
            username=username,
            password=password,
            phone=phone,
            wechat=wechat,
            qq=qq
        )
        db.session.add(new_user)
        db.session.commit()

        flash('注册成功，请登录')
        return redirect(url_for('login'))

    # GET请求：显示注册页面
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()
        if user and user.password == password:
            session['user_id'] = user.id
            session['username'] = user.username
            session['is_admin'] = user.is_admin
            flash('登录成功')
            if user.is_admin:
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('index'))
        else:
            flash('用户名或密码错误')
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('已退出登录')
    return redirect(url_for('index'))

@app.route('/publish', methods=['GET', 'POST'])
def publish():
    if 'user_id' not in session or session.get('is_admin'):
        flash('请先登录普通用户账号来发布商品')
        return redirect(url_for('login'))

    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        price = float(request.form['price'])
        category = request.form['category']

        if 'image' not in request.files:
            flash('请上传商品图片')
            return redirect(request.url)

        file = request.files['image']
        if file.filename == '':
            flash('请选择要上传的图片')
            return redirect(request.url)

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            filename = f"{timestamp}_{filename}"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            new_item = Item(
                title=title,
                description=description,
                price=price,
                category=category,
                image_path=filename,
                seller_id=session['user_id']
            )
            db.session.add(new_item)
            db.session.commit()

            flash('商品发布成功')
            return redirect(url_for('index'))
        else:
            flash('只允许上传png、jpg、jpeg、gif格式的图片')
            return redirect(request.url)

    return render_template('publish.html')

@app.route('/item/<int:item_id>')
def item_detail(item_id):
    item = Item.query.get_or_404(item_id)
    # 普通用户不能看已下架/已售出的商品
    if not session.get('is_admin') and (not item.is_active or item.is_sold):
        flash('商品不存在或已下架')
        return redirect(url_for('index'))
    show_contact = request.args.get('show_contact', 'false') == 'true'
    return render_template('detail.html',
                           item=item.to_dict(hide_seller_info=not show_contact),
                           show_contact=show_contact,
                           is_admin=session.get('is_admin', False))

# -------------------------- 购物车功能（增加下架检查）--------------------------
@app.route('/cart')
def cart():
    if 'user_id' not in session or session.get('is_admin'):
        flash('请先登录普通用户')
        return redirect(url_for('login'))

    cart_items = Cart.query.filter_by(user_id=session['user_id']).all()
    items = []
    total_price = 0
    for cart_item in cart_items:
        item = Item.query.get(cart_item.item_id)
        if item and item.is_active and not item.is_sold:
            item_dict = item.to_dict()
            item_dict['cart_id'] = cart_item.id
            items.append(item_dict)
            total_price += item.price
        else:
            # 商品已失效，直接从购物车移除并发送通知
            db.session.delete(cart_item)
            send_notification(session['user_id'], f"购物车中的商品「{item.title if item else '未知商品'}」已失效，已自动移除")
    db.session.commit()
    return render_template('cart.html', items=items, total_price=round(total_price, 2))

@app.route('/add_to_cart/<int:item_id>', methods=['POST'])
def add_to_cart(item_id):
    if 'user_id' not in session or session.get('is_admin'):
        return jsonify({'success': False, 'message': '请先登录普通用户'})

    item = Item.query.get(item_id)
    if not item:
        return jsonify({'success': False, 'message': '商品不存在'})
    if not item.is_active or item.is_sold:
        return jsonify({'success': False, 'message': '商品已下架或已售出'})
    if item.seller_id == session['user_id']:
        return jsonify({'success': False, 'message': '不能添加自己的商品'})

    existing = Cart.query.filter_by(user_id=session['user_id'], item_id=item_id).first()
    if existing:
        return jsonify({'success': False, 'message': '商品已在购物车中'})

    cart_item = Cart(user_id=session['user_id'], item_id=item_id)
    db.session.add(cart_item)
    db.session.commit()
    return jsonify({'success': True, 'message': '已加入购物车', 'cart_count': get_cart_count()})

@app.route('/remove_from_cart/<int:cart_id>', methods=['POST'])
def remove_from_cart(cart_id):
    if 'user_id' not in session or session.get('is_admin'):
        return jsonify({'success': False, 'message': '请先登录'})
    cart_item = Cart.query.get(cart_id)
    if cart_item and cart_item.user_id == session['user_id']:
        db.session.delete(cart_item)
        db.session.commit()
        return jsonify({'success': True, 'message': '已移除'})
    return jsonify({'success': False, 'message': '操作失败'})

# -------------------------- 购买功能（增加通知）--------------------------
@app.route('/buy_now/<int:item_id>', methods=['POST'])
def buy_now(item_id):
    if 'user_id' not in session or session.get('is_admin'):
        return jsonify({'success': False, 'message': '请先登录普通用户'})

    item = Item.query.get(item_id)
    if not item:
        return jsonify({'success': False, 'message': '商品不存在'})
    if not item.is_active or item.is_sold:
        return jsonify({'success': False, 'message': '商品已下架或已售出'})
    if item.seller_id == session['user_id']:
        return jsonify({'success': False, 'message': '不能购买自己的商品'})

    order = Order(buyer_id=session['user_id'], item_id=item_id)
    item.is_sold = True
    Cart.query.filter_by(item_id=item_id).delete()
    db.session.add(order)
    db.session.commit()

    # 通知卖家
    send_notification(item.seller_id, f"您的商品「{item.title}」已被拍下，请及时与买家联系！", url_for('my_orders'))
    return jsonify({'success': True, 'message': '购买成功！请联系卖家发货'})

# -------------------------- 咨询卖家 --------------------------
@app.route('/get_seller_contact/<int:item_id>')
def get_seller_contact(item_id):
    if 'user_id' not in session:
        flash('请先登录')
        return redirect(url_for('login'))
    return redirect(url_for('item_detail', item_id=item_id, show_contact='true'))

# -------------------------- 举报功能 --------------------------
@app.route('/report/<int:item_id>', methods=['POST'])
def report_item(item_id):
    if 'user_id' not in session or session.get('is_admin'):
        return jsonify({'success': False, 'message': '请先登录普通用户'})
    reason = request.form.get('reason', '')
    if not reason:
        return jsonify({'success': False, 'message': '请填写举报原因'})
    report = Report(reporter_id=session['user_id'], item_id=item_id, reason=reason)
    db.session.add(report)
    db.session.commit()
    return jsonify({'success': True, 'message': '举报已提交，我们会尽快处理'})

# -------------------------- 用户个人中心（增加通知展示）--------------------------
@app.route('/my')
def my_profile():
    if 'user_id' not in session or session.get('is_admin'):
        flash('请先登录普通用户')
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    return render_template('my.html', user=user.to_dict(), active_tab='profile')

@app.route('/my/items')
def my_items():
    if 'user_id' not in session or session.get('is_admin'):
        flash('请先登录普通用户')
        return redirect(url_for('login'))
    items = Item.query.filter_by(seller_id=session['user_id']).order_by(Item.create_time.desc()).all()
    item_dicts = [item.to_dict() for item in items]
    return render_template('my.html', items=item_dicts, active_tab='items')

@app.route('/my/orders')
def my_orders():
    if 'user_id' not in session or session.get('is_admin'):
        flash('请先登录普通用户')
        return redirect(url_for('login'))
    orders = Order.query.filter_by(buyer_id=session['user_id']).order_by(Order.order_time.desc()).all()
    order_dicts = []
    for order in orders:
        item = Item.query.get(order.item_id)
        order_dicts.append({
            'id': order.id,
            'item_title': item.title,
            'item_image': item.image_path,
            'price': item.price,
            'seller_username': item.seller.username,
            'order_time': order.order_time.strftime('%Y-%m-%d %H:%M'),
            'status': order.status
        })
    return render_template('my.html', orders=order_dicts, active_tab='orders')

@app.route('/my/notifications')
def my_notifications():
    if 'user_id' not in session or session.get('is_admin'):
        return redirect(url_for('login'))
    notifs = Notification.query.filter_by(user_id=session['user_id']).order_by(Notification.create_time.desc()).all()
    # 标记所有为已读
    for n in notifs:
        n.is_read = True
    db.session.commit()
    return render_template('notifications.html', notifications=notifs)

@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session or session.get('is_admin'):
        return jsonify({'success': False, 'message': '请先登录普通用户'})
    user = User.query.get(session['user_id'])
    phone = request.form['phone']
    wechat = request.form.get('wechat', '').strip()
    qq = request.form.get('qq', '').strip()
    if not re.match(r'^1[3-9]\d{9}$', phone):
        return jsonify({'success': False, 'message': '请输入有效的11位手机号'})
    if wechat and not re.match(r'^[a-zA-Z0-9_-]{1,30}$', wechat):
        return jsonify({'success': False, 'message': '微信号格式错误'})
    if qq and not re.match(r'^\d{5,12}$', qq):
        return jsonify({'success': False, 'message': 'QQ号必须为5-12位数字'})
    if not wechat and not qq:
        return jsonify({'success': False, 'message': '请至少填写微信号或QQ号'})
    user.phone = phone
    user.wechat = wechat
    user.qq = qq
    db.session.commit()
    return jsonify({'success': True, 'message': '更新成功'})

import os
from models import Report, Cart   # 确保已导入

@app.route('/delete_item/<int:item_id>', methods=['POST'])
def delete_item(item_id):
    if 'user_id' not in session or session.get('is_admin'):
        return jsonify({'success': False, 'message': '请先登录普通用户'})
    item = Item.query.get(item_id)
    if item and item.seller_id == session['user_id']:
        try:
            # 1. 删除相关举报记录（避免外键约束错误）
            Report.query.filter_by(item_id=item_id).delete()
            # 2. 删除购物车中该商品
            Cart.query.filter_by(item_id=item_id).delete()
            # 3. 删除商品图片文件
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], item.image_path)
            if os.path.exists(image_path):
                os.remove(image_path)
            # 4. 删除商品
            db.session.delete(item)
            db.session.commit()
            return jsonify({'success': True, 'message': '商品已删除'})
        except Exception as e:
            db.session.rollback()
            print(f"删除失败: {e}")
            return jsonify({'success': False, 'message': f'删除失败：{str(e)}'})
    return jsonify({'success': False, 'message': '无权删除或商品不存在'})

@app.route('/edit_item/<int:item_id>', methods=['GET', 'POST'])
def edit_item(item_id):
    if 'user_id' not in session or session.get('is_admin'):
        flash('请先登录普通用户')
        return redirect(url_for('login'))
    item = db.session.get(Item, item_id)
    if not item or item.seller_id != session['user_id']:
        flash('无权限')
        return redirect(url_for('my_items'))
    if item.is_sold:
        flash('已售出商品不能编辑')
        return redirect(url_for('my_items'))
    if request.method == 'POST':
        item.title = request.form['title']
        item.description = request.form['description']
        item.price = float(request.form['price'])
        item.category = request.form['category']
        if 'image' in request.files and request.files['image'].filename:
            file = request.files['image']
            if file and allowed_file(file.filename):
                old = os.path.join(app.config['UPLOAD_FOLDER'], item.image_path)
                if os.path.exists(old):
                    os.remove(old)
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                filename = f"{timestamp}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                item.image_path = filename
        db.session.commit()
        flash('修改成功')
        return redirect(url_for('my_items'))
    return render_template('edit_item.html', item=item.to_dict())

@app.route('/cancel_order/<int:order_id>', methods=['POST'])
def cancel_order(order_id):
    if 'user_id' not in session or session.get('is_admin'):
        return jsonify({'success': False, 'message': '请先登录'})
    order = db.session.get(Order, order_id)
    if not order or order.buyer_id != session['user_id']:
        return jsonify({'success': False, 'message': '订单不存在'})
    if order.status != '待发货':
        return jsonify({'success': False, 'message': '只能取消待发货订单'})
    item = db.session.get(Item, order.item_id)
    item.is_sold = False
    db.session.delete(order)
    db.session.commit()
    return jsonify({'success': True, 'message': '订单已取消'})

@app.route('/confirm_receipt/<int:order_id>', methods=['POST'])
def confirm_receipt(order_id):
    if 'user_id' not in session or session.get('is_admin'):
        return jsonify({'success': False, 'message': '请先登录'})
    order = db.session.get(Order, order_id)
    if not order or order.buyer_id != session['user_id']:
        return jsonify({'success': False, 'message': '订单不存在'})
    if order.status != '待发货':
        return jsonify({'success': False, 'message': '无法确认收货'})
    order.status = '已完成'
    db.session.commit()
    return jsonify({'success': True, 'message': '确认收货成功'})

# -------------------------- 管理员功能 --------------------------
# 管理员仪表盘根路由（重定向到商品管理）
@app.route('/admin')
def admin_dashboard():
    if not session.get('is_admin'):
        abort(403)
    return redirect(url_for('admin_items'))

# 商品管理列表
@app.route('/admin/items')
def admin_items():
    if not session.get('is_admin'):
        abort(403)
    keyword = request.args.get('keyword', '')
    category = request.args.get('category', 'all')
    items = search_items(keyword, category, admin_view=True)
    item_dicts = [item.to_dict(hide_seller_info=True) for item in items]
    return render_template('admin_items.html', items=item_dicts, keyword=keyword, category=category)

# 管理员查看商品详情
@app.route('/admin/item/<int:item_id>')
def admin_item_detail(item_id):
    if not session.get('is_admin'):
        abort(403)
    item = Item.query.get_or_404(item_id)
    return render_template('admin_item_detail.html', item=item.to_dict(hide_seller_info=False))

# 置顶/取消置顶
@app.route('/admin/item/<int:item_id>/top', methods=['POST'])
def admin_toggle_top(item_id):
    if not session.get('is_admin'):
        return jsonify({'success': False, 'message': '无权限'})
    item = Item.query.get(item_id)
    if not item:
        return jsonify({'success': False, 'message': '商品不存在'})
    item.is_top = not item.is_top
    db.session.commit()
    action = "置顶" if item.is_top else "取消置顶"
    send_notification(item.seller_id, f"您的商品「{item.title}」已被管理员{action}")
    return jsonify({'success': True, 'message': f'已{action}'})

# 下架商品
@app.route('/admin/item/<int:item_id>/off_shelf', methods=['POST'])
def admin_off_shelf(item_id):
    if not session.get('is_admin'):
        return jsonify({'success': False, 'message': '无权限'})
    item = Item.query.get(item_id)
    if not item:
        return jsonify({'success': False, 'message': '商品不存在'})
    # 已下架的商品不能再下架
    if not item.is_active:
        return jsonify({'success': False, 'message': '商品已是下架状态'})

    reason = request.json.get('reason', '未提供原因')

    # 下架商品，同时取消置顶
    item.is_active = False
    if item.is_top:
        item.is_top = False
    db.session.commit()

    # 从购物车移除并通知购物车用户
    delete_related_cart_items(item_id, reason)

    # 通知卖家（只发一次）
    send_notification(item.seller_id, f"您的商品「{item.title}」已被管理员下架，\n原因：{reason}")

    return jsonify({'success': True, 'message': '已下架'})

# 重新上架商品
@app.route('/admin/item/<int:item_id>/relist', methods=['POST'])
def admin_relist_item(item_id):
    if not session.get('is_admin'):
        return jsonify({'success': False, 'message': '无权限'})
    item = Item.query.get(item_id)
    if not item:
        return jsonify({'success': False, 'message': '商品不存在'})
    if item.is_active:
        return jsonify({'success': False, 'message': '商品已是上架状态'})
    if item.is_sold:
        return jsonify({'success': False, 'message': '商品已售出，无法重新上架'})

    item.is_active = True
    # 重新上架时，置顶状态保持 false（如需置顶可手动操作）
    db.session.commit()

    send_notification(item.seller_id, f"您的商品「{item.title}」已被管理员重新上架")

    return jsonify({'success': True, 'message': '已重新上架'})

# 用户管理列表
@app.route('/admin/users')
def admin_users():
    if not session.get('is_admin'):
        abort(403)
    users = User.query.filter_by(is_admin=False).all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/user/<int:user_id>')
def admin_user_detail(user_id):
    if not session.get('is_admin'):
        abort(403)
    user = User.query.get_or_404(user_id)
    items = Item.query.filter_by(seller_id=user_id).all()
    return render_template('admin_user_detail.html', user=user, items=items)

# 待处理举报
@app.route('/admin/reports/pending')
def admin_reports_pending():
    if not session.get('is_admin'):
        abort(403)
    reports = Report.query.filter_by(status='待处理').order_by(Report.report_time.desc()).all()
    return render_template('admin_reports.html', reports=reports, type='pending')

# 已处理举报
@app.route('/admin/reports/handled')
def admin_reports_handled():
    if not session.get('is_admin'):
        abort(403)
    reports = Report.query.filter_by(status='已处理').order_by(Report.handle_time.desc()).all()
    return render_template('admin_reports.html', reports=reports, type='handled')

# 处理举报
@app.route('/admin/report/<int:report_id>/handle', methods=['POST'])
def admin_handle_report(report_id):
    if not session.get('is_admin'):
        return jsonify({'success': False, 'message': '无权限'})
    report = Report.query.get(report_id)
    if not report:
        return jsonify({'success': False, 'message': '举报不存在'})
    if report.status != '待处理':
        return jsonify({'success': False, 'message': '该举报已处理过了'})
    action = request.form.get('action')
    reason = request.form.get('reason')
    if not action or not reason:
        return jsonify({'success': False, 'message': '缺少必要参数'})
    item = Item.query.get(report.item_id)
    if action == 'shelf_off':
        if not item:
            return jsonify({'success': False, 'message': '商品不存在'})
        item.is_active = False
        delete_related_cart_items(item.id, f"因举报处理：{reason}")
        send_notification(item.seller_id, f"您的商品「{item.title}」因举报被下架，\n原因：{reason}")
        result_text = f"下架商品，原因：{reason}"
        detail_info = f"处理时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n处理结果：{result_text}"
        send_notification(report.reporter_id, "感谢您对平台环境的监督！相关违规内容已妥善处置。", detail=detail_info)
    elif action == 'reject':
        result_text = f"驳回举报，理由：{reason}"
        detail_info = f"处理时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n处理结果：{result_text}"
        send_notification(report.reporter_id, f"您举报的商品「{item.title if item else '未知'}」已处理，详情点击查看", detail=detail_info)
    else:
        return jsonify({'success': False, 'message': '无效操作'})
    report.status = '已处理'
    report.handle_time = datetime.now()
    report.handle_result = result_text
    report.handle_action = action
    db.session.commit()
    return jsonify({'success': True, 'message': '处理完成'})

# -------------------------- 启动 --------------------------
if __name__ == '__main__':
    app.run(debug=True)