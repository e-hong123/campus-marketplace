"""
数据库迁移脚本 - 删除 Message 表的 is_read 字段
"""
import sqlite3
import os

# 数据库路径
db_path = 'instance/marketplace.db'

if not os.path.exists(db_path):
    print(f"数据库文件不存在: {db_path}")
    exit(1)

print("开始迁移数据库...")

# 连接数据库
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # 检查 is_read 字段是否存在
    cursor.execute("PRAGMA table_info(Message)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'is_read' in columns:
        print("发现 is_read 字段，开始迁移...")
        
        # 1. 创建新表（不包含 is_read）
        cursor.execute('''
            CREATE TABLE Message_new (
                id INTEGER PRIMARY KEY,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                send_time DATETIME DEFAULT (datetime('now')),
                FOREIGN KEY (sender_id) REFERENCES user (id),
                FOREIGN KEY (receiver_id) REFERENCES user (id)
            )
        ''')
        
        # 2. 复制数据（排除 is_read）
        cursor.execute('''
            INSERT INTO Message_new (id, sender_id, receiver_id, content, send_time)
            SELECT id, sender_id, receiver_id, content, send_time
            FROM Message
        ''')
        
        # 3. 删除旧表
        cursor.execute('DROP TABLE Message')
        
        # 4. 重命名新表
        cursor.execute('ALTER TABLE Message_new RENAME TO Message')
        
        conn.commit()
        print("✅ 数据库迁移成功！is_read 字段已删除。")
    else:
        print("✅ is_read 字段不存在，无需迁移。")
        
except Exception as e:
    conn.rollback()
    print(f"❌ 迁移失败: {e}")
    exit(1)
finally:
    conn.close()

print("迁移完成！")
