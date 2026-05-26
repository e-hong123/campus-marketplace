"""
快速修复脚本 - 直接添加 is_read 字段
"""
import sqlite3
import os
import sys

# 数据库路径
db_path = os.path.join(os.path.dirname(__file__), 'instance', 'marketplace.db')

print("=" * 50)
print("数据库修复工具")
print("=" * 50)
print()

if not os.path.exists(db_path):
    print(f"❌ 错误：数据库文件不存在")
    print(f"   路径：{db_path}")
    print()
    print("请先运行应用创建数据库：")
    print("   python app.py")
    input("\n按回车键退出...")
    sys.exit(1)

print(f"✅ 找到数据库文件：{db_path}")
print()

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 检查表是否存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Message'")
    if not cursor.fetchone():
        print("❌ 错误：Message 表不存在")
        print("   请先在应用中发送一条消息来创建表")
        conn.close()
        input("\n按回车键退出...")
        sys.exit(1)
    
    # 检查 is_read 字段
    cursor.execute("PRAGMA table_info(Message)")
    columns = [col[1] for col in cursor.fetchall()]
    
    print("当前 Message 表的字段：")
    for col in columns:
        print(f"  - {col}")
    print()
    
    if 'is_read' in columns:
        print("✅ is_read 字段已存在，无需修复！")
        print()
        print("如果仍然报错，请尝试：")
        print("  1. 停止 Flask 应用（Ctrl+C）")
        print("  2. 重新启动：python app.py")
        print("  3. 刷新浏览器页面")
    else:
        print("⚠️  发现缺少 is_read 字段，开始修复...")
        print()
        
        # 重建表
        cursor.execute('''
            CREATE TABLE Message_new (
                id INTEGER PRIMARY KEY,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                send_time DATETIME DEFAULT (datetime('now')),
                is_read BOOLEAN DEFAULT 0,
                FOREIGN KEY (sender_id) REFERENCES user (id),
                FOREIGN KEY (receiver_id) REFERENCES user (id)
            )
        ''')
        
        cursor.execute('''
            INSERT INTO Message_new (id, sender_id, receiver_id, content, send_time, is_read)
            SELECT id, sender_id, receiver_id, content, send_time, 0
            FROM Message
        ''')
        
        cursor.execute('DROP TABLE Message')
        cursor.execute('ALTER TABLE Message_new RENAME TO Message')
        
        conn.commit()
        
        print("✅ 修复成功！is_read 字段已添加")
        print()
        print("📊 统计信息：")
        cursor.execute("SELECT COUNT(*) FROM Message")
        count = cursor.fetchone()[0]
        print(f"   - 消息总数：{count}")
        print(f"   - 所有消息的 is_read 设置为 False（未读）")
        print()
        print("⚠️  重要提示：")
        print("   由于所有历史消息都被标记为未读，")
        print("   聊天图标可能会显示较大的数字。")
        print()
        print("   解决方法：")
        print("   1. 点击聊天图标进入聊天页面")
        print("   2. 依次点击所有联系人查看消息")
        print("   3. 徽章会自动清零")
    
    conn.close()
    
except Exception as e:
    print(f"❌ 修复失败：{e}")
    import traceback
    traceback.print_exc()
    if 'conn' in locals():
        conn.close()
    input("\n按回车键退出...")
    sys.exit(1)

print()
print("=" * 50)
print("完成！现在可以重启应用了")
print("=" * 50)
print()
input("按回车键退出...")
