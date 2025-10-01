"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os
from channels.routing import ProtocolTypeRouter
from django.core.asgi import get_asgi_application
from .routing import application_router

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')


django_asgi_application = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_application,
    "websocket": application_router
})
