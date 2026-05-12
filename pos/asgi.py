import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
# Bu yerda posapp.routing hali yaratilmagan, hozir pastda yaratamiz
import posapp.routing 

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pos.settings')

application = ProtocolTypeRouter({
    # Oddiy HTTP so'rovlar uchun
    "http": get_asgi_application(),
    
    # WebSocket so'rovlar uchun
    "websocket": AuthMiddlewareStack(
        URLRouter(
            posapp.routing.websocket_urlpatterns
        )
    ),
})