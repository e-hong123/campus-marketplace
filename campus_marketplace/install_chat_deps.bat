@echo off
chcp 65001 >nul
echo ========================================
echo   安装 WebSocket 聊天功能依赖
echo ========================================
echo.

echo [1/2] 正在安装 Flask-SocketIO...
pip install Flask-SocketIO

echo.
echo [2/2] 正在安装 eventlet...
pip install eventlet

echo.
echo ========================================
echo   安装完成！
echo ========================================
echo.
echo 现在可以运行 python app.py 启动应用了
echo.
pause
