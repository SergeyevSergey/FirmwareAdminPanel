from channels.routing import URLRouter
from channels.auth import AuthMiddlewareStack
from boards.routing import websocket_urlpatterns as boards_ws


# Common routing
application_router = AuthMiddlewareStack(
    URLRouter(
        boards_ws
    )
)