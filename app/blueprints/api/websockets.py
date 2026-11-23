from flask import Blueprint, jsonify
from flask_socketio import emit, join_room, leave_room
from flask_login import current_user
from extensions import socketio

# Note: Ensure `socketio` is initialized in extensions.py and `socketio.init_app(app)` in app/__init__.py

@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated and current_user.tenant_id:
        room = f"tenant_{current_user.tenant_id}"
        join_room(room)
        emit('status', {'msg': f'{current_user.name} connected to real-time updates.'})

@socketio.on('disconnect')
def handle_disconnect():
    if current_user.is_authenticated and current_user.tenant_id:
        room = f"tenant_{current_user.tenant_id}"
        leave_room(room)

def broadcast_sale(tenant_id, sale_data):
    """Call this from sales_service.py after a successful sale."""
    room = f"tenant_{tenant_id}"
    socketio.emit('new_sale', sale_data, to=room)

def broadcast_inventory_alert(tenant_id, item_name, quantity):
    room = f"tenant_{tenant_id}"
    socketio.emit('low_stock_alert', {"item": item_name, "qty": quantity}, to=room)