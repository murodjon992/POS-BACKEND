from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # ws://localhost:8000/ws/pos/ manziliga ulanish uchun
    re_path(r'ws/pos/$', consumers.PosConsumer.as_asgi()),
]