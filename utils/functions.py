import json
import logging
import paho.mqtt.publish as publish
from redis.exceptions import RedisError, ConnectionError
from channels.exceptions import InvalidChannelLayerError
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django_redis import get_redis_connection
from django.conf import settings
from boards.models import Board

logger = logging.getLogger(__name__)

# MQTT


# Pub

class MqttError(Exception):
    pass

def publish_mqtt(context: dict, topic: str):
    host = settings.MQTT_HOST
    port = settings.MQTT_PORT
    payload = json.dumps(context)

    try:
        publish.single(topic=topic, payload=payload, hostname=host, port=port)
        logger.info("published payload=%s to %s", payload, topic)
    except OSError as e:
        logger.exception("MQTT OS error")
        raise MqttError(str(e)) from e
    except Exception as e:
        logger.exception("MQTT unexpected error")
        raise MqttError(str(e)) from e


# Sub

def mqtt_response_state_board(mac_address: str, is_active: bool):
    # Redis cache update
    try:
        cache = get_redis_connection("default")
        pending = cache.get(f"pending:{mac_address}")

        if pending:
            cache.delete(f"pending:{mac_address}")
            logger.info("deleted pending flag for mac_address=%s", mac_address)
        else:
            logger.warning("reply for %s but no pending flag found", mac_address)
            return

    except (RedisError, ConnectionError):
        logger.exception("Redis connection error")
    except Exception:
        logger.exception("unexpected error")

    # Board object update
    Board.objects.filter(mac_address=mac_address).update(is_active=is_active)

    # Send WebSocket event
    event = {
        "type": "board_update",
        "data": {
            "mac_address": mac_address,
            "is_active": is_active
        }
    }
    ws_send(event, "boards")



# WebSocket


def ws_send(event: dict, group: str):
    try:
        layer = get_channel_layer()
        async_to_sync(layer.group_send)(
            group,
            event
        )
        logger.info("send event=%s to group %s on layer %s", event, group, layer)
    except InvalidChannelLayerError:
        logger.exception("channel layer error")
    except Exception:
        logger.exception("unexpected error")
