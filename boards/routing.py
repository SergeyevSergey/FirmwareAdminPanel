from django.urls import path
from .consumers import BoardsConsumer

websocket_urlpatterns = [
    path("ws/boards/", BoardsConsumer.as_asgi()),
]