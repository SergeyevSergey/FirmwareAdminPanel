import os
import json
import logging
import paho.mqtt.publish as publish
from redis.exceptions import RedisError, ConnectionError
from channels.exceptions import InvalidChannelLayerError
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django_redis import get_redis_connection
from django.conf import settings


logger = logging.getLogger(__name__)


# MQTT

MQTT_USER = os.environ.get("MQTT_USER")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD")
MQTT_HOST = os.environ.get("MQTT_HOST", "emqx")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))

class MqttError(Exception):
    pass


def publish_mqtt(context: dict, topic: str):
    payload = json.dumps(context)

    try:
        publish.single(
            topic=topic,
            payload=payload,
            hostname=MQTT_HOST,
            port=MQTT_PORT,
            auth={"username": MQTT_USER, "password": MQTT_PASSWORD}
        )
        logger.info("published payload=%s to %s", payload, topic)
    except OSError as e:
        logger.exception("MQTT OS error")
        raise MqttError(str(e)) from e
    except Exception as e:
        logger.exception("MQTT unexpected error")
        raise MqttError(str(e)) from e


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
