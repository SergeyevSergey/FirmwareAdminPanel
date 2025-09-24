import json
import paho.mqtt.publish as publish
from django.conf import settings

def publish_mqtt(context: dict, topic: str):
    host = settings.MQTT_HOST
    port = settings.MQTT_PORT
    payload = json.dumps(context)

    publish.single(topic=topic, payload=payload, hostname=host, port=port)
