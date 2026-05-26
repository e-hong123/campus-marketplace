import os
import re
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort
from werkzeug.utils import secure_filename
from models import db, User, Item, Cart, Order, Report, Notification, BrowseHistory, Message
import matplotlib
matplotlib.use('Agg')

import matplotlib.pyplot as plt

# 解决中文乱码
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei']

# 解决负号显示问题
plt.rcParams['axes.unicode_minus'] = False
from io import BytesIO
import base64
from sqlalchemy import func
from flask_socketio import SocketIO, emit, join_room, leave_room

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
socketio = SocketIO(app, cors_allowed_origins="*")

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

# -------------------------- 猜你喜欢推荐 --------------------------
def get_recommend_items(user_id, limit=6):

    # 获取用户最近浏览记录
    from datetime import datetime, timedelta

    thirty_days_ago = datetime.now() - timedelta(days=30)

    histories = BrowseHistory.query.filter(
        BrowseHistory.user_id == user_id,
        BrowseHistory.browse_time >= thirty_days_ago
    ).order_by(
        BrowseHistory.browse_time.desc()
    ).all()

    # 没浏览记录 → 返回最新商品
    # 没浏览记录 → 每个分类推荐一个商品
    if not histories:

        categories = [
            '电子产品',
            '书籍教材',
            '生活用品',
            '运动器材',
            '服饰鞋包'
        ]

        recommend_items = []

        for category in categories:

            item = Item.query.filter_by(
                category=category,
                is_active=True,
                is_sold=False
            ).order_by(
                Item.create_time.desc()
            ).first()

            if item:
                recommend_items.append(item)

        return recommend_items

    # 统计浏览最多的分类
    category_count = {}

    viewed_item_ids = set()

    seen_items = set()

    for history in histories:

        # 重复浏览去重
        if history.item_id in seen_items:
            continue

        seen_items.add(history.item_id)

        item = Item.query.get(history.item_id)
        if not item:
            continue

        # 数据清洗：过滤下架/售出商品
        if not item.is_active or item.is_sold:
            continue

    # 找最喜欢的分类
    # 数据清洗后可能为空
    if not category_count:
        return Item.query.filter_by(
            is_active=True,
            is_sold=False
        ).order_by(
            Item.create_time.desc()
        ).limit(limit).all()

    # 找最喜欢的分类
    favorite_category = max(
        category_count,
        key=category_count.get
    )
    favorite_category = max(category_count,
                            key=category_count.get)

    # 推荐同分类商品
    recommend_items = Item.query.filter(
        Item.category == favorite_category,
        Item.is_active == True,
        Item.is_sold == False,
       # ~Item.id.in_(viewed_item_ids)
    ).order_by(
        Item.create_time.desc()
    ).limit(limit).all()

    return recommend_items

@app.context_processor
def inject_common():
    return dict(
        cart_count=get_cart_count(),
        notif_count=get_unread_notification_count(),   # 注意：函数名正确
        is_admin=session.get('is_admin', False),
        unhandled_reports_count=get_unhandled_reports_count()   # 新增
    )


@app.context_processor
def inject_common():
    return dict(
        cart_count=get_cart_count(),
        notif_count=get_unread_notification_count(),   # 注意：函数名正确
        is_admin=session.get('is_admin', False),
        unhandled_reports_count=get_unhandled_reports_count()   # 新增
    )


# -------------------------- 价格走势分析 --------------------------
@app.route('/price_trend/<category>')
def price_trend(category):

    current_item_id = request.args.get(
        'current_item_id',
        type=int
    )

    items = Item.query.filter(
        Item.category == category,
        Item.is_active == True,
        Item.is_sold == False
    ).order_by(
        Item.create_time.asc()
    ).all()

    dates = []
    prices = []
    titles = []

    for item in items:

        dates.append(
            item.create_time.strftime('%m-%d %H:%M')
        )

        prices.append(float(item.price))

        titles.append(item.title)

    # 图表大小
    plt.figure(figsize=(14, 7))

    # 绘制折线图
    # 图表大小
    plt.figure(figsize=(14, 7))

    # 先画折线
    plt.plot(
        dates,
        prices,
        linewidth=3,
        color='#4A90E2'
    )

    # 遍历所有商品点
    for i in range(len(dates)):

        # 当前商品 → 红点
        if items[i].id == current_item_id:

            plt.scatter(
                dates[i],
                prices[i],
                color='red',
                s=260,
                zorder=5
            )

            plt.annotate(
                f'当前商品\n{titles[i]}\n¥{prices[i]}',
                (dates[i], prices[i]),
                textcoords="offset points",
                xytext=(0, 8),
                ha='center',
                fontsize=11,
                color='red',
                fontweight='bold'
            )

        # 其它商品 → 蓝点
        else:

            plt.scatter(
                dates[i],
                prices[i],
                color='#4A90E2',
                s=120
            )

            plt.annotate(
                f'{titles[i]}\n¥{prices[i]}',
                (dates[i], prices[i]),
                textcoords="offset points",
                xytext=(0, 10),
                ha='center',
                fontsize=9
            )

    # 标题
    plt.title(
        f'{category}历史价格走势分析',
        fontsize=22
    )

    # 横坐标
    plt.xlabel(
        '商品发布时间',
        fontsize=15
    )

    # 纵坐标
    plt.ylabel(
        '商品价格（元）',
        fontsize=15
    )

    # 网格
    plt.grid(
        True,
        linestyle='--',
        alpha=0.5
    )

    # 日期旋转
    plt.xticks(rotation=20)

    plt.tight_layout()
    plt.yticks(fontsize=11)

    # 自动布局
    plt.tight_layout()

    # 转图片
    img = BytesIO()

    plt.savefig(
        img,
        format='png',
        bbox_inches='tight'
    )

    img.seek(0)

    plot_url = base64.b64encode(
        img.getvalue()
    ).decode()

    plt.close()

    return render_template(
        'price_trend.html',
        category=category,
        plot_url=plot_url
    )




# -------------------------- 基础路由 --------------------------
@app.route('/')
def index():

    keyword = request.args.get('keyword', '')
    category = request.args.get('category', 'all')

    items = search_items(keyword, category)

    item_dicts = [
        item.to_dict(hide_seller_info=True)
        for item in items
    ]

    recommend_dicts = []

    # 登录用户才推荐
    if 'user_id' in session and not session.get('is_admin'):

        recommend_items = get_recommend_items(
            session['user_id']
        )

        recommend_dicts = [
            item.to_dict(hide_seller_info=True)
            for item in recommend_items
        ]

    return render_template(
        'index.html',
        items=item_dicts,
        recommend_items=recommend_dicts,
        keyword=keyword,
        category=category
    )

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
    # 记录浏览历史
    if 'user_id' in session and not session.get('is_admin'):

        # 防止重复记录（10分钟内只记录一次）
        recent = BrowseHistory.query.filter_by(
            user_id=session['user_id'],
            item_id=item_id
        ).order_by(BrowseHistory.browse_time.desc()).first()

        if not recent:
            history = BrowseHistory(
                user_id=session['user_id'],
                item_id=item_id
            )
            db.session.add(history)
            db.session.commit()
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

    # 获取买家信息
    buyer = User.query.get(session['user_id'])
    
    # 通知卖家（包含买家信息和联系方式）
    buyer_info = f"买家：{buyer.username}，电话：{buyer.phone}"
    if buyer.wechat:
        buyer_info += f"，微信：{buyer.wechat}"
    if buyer.qq:
        buyer_info += f"，QQ：{buyer.qq}"
    
    # 发送通知，包含详细信息和联系链接
    send_notification(
        item.seller_id, 
        f"您的商品「{item.title}」已被 {buyer.username} 拍下！请及时联系买家安排发货。",
        link=url_for('chat_with_buyer', buyer_id=buyer.id),
        detail=f"订单信息：\n商品：{item.title}\n价格：¥{item.price}\n\n{buyer_info}\n\n点击「联系买家」可直接与买家聊天沟通。"
    )
    
    return jsonify({'success': True, 'message': '购买成功！卖家将尽快与您联系'})

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

# -------------------------- 联系买家/卖家 --------------------------
@app.route('/chat_with_buyer/<int:buyer_id>')
def chat_with_buyer(buyer_id):
    """卖家联系买家"""
    if 'user_id' not in session:
        flash('请先登录')
        return redirect(url_for('login'))
    
    # 验证买家存在
    buyer = User.query.get_or_404(buyer_id)
    if buyer.id == session['user_id']:
        flash('不能和自己聊天')
        return redirect(url_for('index'))
    
    # 跳转到聊天页面，并自动打开与该买家的对话
    return redirect(url_for('chat_list', target_user=buyer.id, target_username=buyer.username))

@app.route('/contact_seller/<int:seller_id>')
def contact_seller(seller_id):
    """买家联系卖家"""
    if 'user_id' not in session:
        flash('请先登录')
        return redirect(url_for('login'))
    
    # 验证卖家存在
    seller = User.query.get_or_404(seller_id)
    if seller.id == session['user_id']:
        flash('不能和自己聊天')
        return redirect(url_for('index'))
    
    # 跳转到聊天页面，并自动打开与该卖家的对话
    return redirect(url_for('chat_list', target_user=seller.id, target_username=seller.username))

# -------------------------- 聊天功能 --------------------------
@app.route('/chat/list')
def chat_list():
    """聊天列表页面（类似微信电脑版）"""
    if 'user_id' not in session or session.get('is_admin'):
        flash('请先登录普通用户')
        return redirect(url_for('login'))
    
    # 获取所有与该用户有聊天记录的其他用户
    user_id = session['user_id']
    
    # 查询所有发送或接收的消息
    messages = db.session.query(
        Message,
        User
    ).join(
        User,
        ((Message.sender_id == User.id) & (Message.receiver_id == user_id)) |
        ((Message.receiver_id == User.id) & (Message.sender_id == user_id))
    ).filter(
        (Message.sender_id == user_id) | (Message.receiver_id == user_id)
    ).order_by(Message.send_time.desc()).all()
    
    # 按用户分组，获取每个用户的最后一条消息
    chat_users = {}
    for message, other_user in messages:
        if other_user.id == user_id:
            continue
            
        if other_user.id not in chat_users:
            chat_users[other_user.id] = {
                'user': other_user,
                'last_message': message
            }
    
    # 转换为列表
    chat_users_list = list(chat_users.values())
    
    # 调试信息：打印联系人数量
    print(f"\n=== 聊天列表调试 ===")
    print(f"当前用户ID: {user_id}")
    print(f"查询到的消息总数: {len(messages)}")
    print(f"去重后的联系人数量: {len(chat_users_list)}")
    for i, chat in enumerate(chat_users_list):
        print(f"  联系人{i+1}: {chat['user'].username} (ID: {chat['user'].id})")
        print(f"    最后消息: {chat['last_message'].content[:50]}...")
    print(f"==================\n")
    
    # 获取目标用户参数（用于自动打开聊天窗口）
    target_user = request.args.get('target_user', type=int)
    target_username = request.args.get('target_username', '')
    
    return render_template('chat_wechat.html', 
                          chat_users=chat_users_list,
                          target_user=target_user,
                          target_username=target_username)

@app.route('/chat/<int:user_id>')
def chat(user_id):
    """聊天页面"""
    if 'user_id' not in session:
        flash('请先登录')
        return redirect(url_for('login'))
    
    other_user = User.query.get_or_404(user_id)
    if other_user.id == session['user_id']:
        flash('不能和自己聊天')
        return redirect(url_for('index'))
    
    # 获取与该用户的所有聊天记录
    messages = Message.query.filter(
        ((Message.sender_id == session['user_id']) & (Message.receiver_id == user_id)) |
        ((Message.sender_id == user_id) & (Message.receiver_id == session['user_id']))
    ).order_by(Message.send_time.asc()).all()
    
    return render_template('chat.html', other_user=other_user, messages=messages)

@app.route('/api/chat/history/<int:user_id>')
def get_chat_history(user_id):
    """获取聊天记录 API"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': '未登录'})
    
    messages = Message.query.filter(
        ((Message.sender_id == session['user_id']) & (Message.receiver_id == user_id)) |
        ((Message.sender_id == user_id) & (Message.receiver_id == session['user_id']))
    ).order_by(Message.send_time.asc()).all()
    
    return jsonify({
        'success': True,
        'messages': [{
            'id': msg.id,
            'sender_id': msg.sender_id,
            'receiver_id': msg.receiver_id,
            'content': msg.content,
            'send_time': msg.send_time.strftime('%Y-%m-%d %H:%M:%S')
        } for msg in messages]
    })

@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    if 'user_id' not in session:
        return False
    
    user_id = session['user_id']
    join_room(f'user_{user_id}')
    print(f'用户 {user_id} 已连接')
    emit('status', {'msg': f'用户 {user_id} 已上线'})

@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开"""
    if 'user_id' in session:
        user_id = session['user_id']
        leave_room(f'user_{user_id}')
        print(f'用户 {user_id} 已断开')

@socketio.on('send_message')
def handle_send_message(data):
    """处理发送消息"""
    if 'user_id' not in session:
        emit('error', {'message': '未登录'})
        return
    
    sender_id = session['user_id']
    receiver_id = data.get('receiver_id')
    content = data.get('content', '').strip()
    
    if not receiver_id or not content:
        emit('error', {'message': '消息内容不能为空'})
        return
    
    # 验证接收者是否存在
    receiver = User.query.get(receiver_id)
    if not receiver:
        emit('error', {'message': '用户不存在'})
        return
    
    # 保存消息到数据库
    message = Message(
        sender_id=sender_id,
        receiver_id=receiver_id,
        content=content
    )
    db.session.add(message)
    db.session.commit()
    
    # 发送给接收者
    emit('receive_message', {
        'sender_id': sender_id,
        'sender_username': session.get('username', ''),
        'content': content,
        'send_time': message.send_time.strftime('%Y-%m-%d %H:%M:%S'),
        'message_id': message.id
    }, room=f'user_{receiver_id}')
    
    # 也发送回给发送者（用于显示）
    emit('message_sent', {
        'receiver_id': receiver_id,
        'content': content,
        'send_time': message.send_time.strftime('%Y-%m-%d %H:%M:%S'),
        'message_id': message.id
    })

@app.route('/api/chat/unread_count')
def get_unread_chat_count():
    """获取未读聊天消息数量"""
    if 'user_id' not in session:
        return jsonify({'count': 0})
    
    # 统计接收给当前用户且未读的消息数量
    count = Message.query.filter(
        Message.receiver_id == session['user_id'],
        Message.is_read == False
    ).count()
    
    return jsonify({'count': count})

@app.route('/api/chat/mark_read/<int:user_id>')
def mark_chat_as_read(user_id):
    """标记与某个用户的所有消息为已读"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': '未登录'})
    
    # 将该用户发送给我的所有消息标记为已读
    messages = Message.query.filter(
        Message.sender_id == user_id,
        Message.receiver_id == session['user_id'],
        Message.is_read == False
    ).all()
    
    for msg in messages:
        msg.is_read = True
    
    db.session.commit()
    
    return jsonify({'success': True, 'marked_count': len(messages)})

@app.route('/api/chat/mark_all_read')
def mark_all_chat_as_read():
    """标记所有聊天消息为已读"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': '未登录'})
    
    # 将所有接收给当前用户的未读消息标记为已读
    messages = Message.query.filter(
        Message.receiver_id == session['user_id'],
        Message.is_read == False
    ).all()
    
    for msg in messages:
        msg.is_read = True
    
    db.session.commit()
    
    return jsonify({'success': True, 'marked_count': len(messages)})

# -------------------------- 启动 --------------------------
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)