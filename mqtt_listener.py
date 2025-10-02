import json
import logging
import os
import threading
import signal
import django

django.setup()

from paho.mqtt.client import Client
from django.conf import settings
from logging.handlers import RotatingFileHandler
from utils.functions import mqtt_response_state_board

MQTT_USER = os.environ.get("MQTT_USER")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD")
LOG_DIR = os.environ.get("LOG_DIR", "/srv/logs/mqtt_listener")
os.makedirs(LOG_DIR, exist_ok=True)

fh = RotatingFileHandler(
    os.path.join(LOG_DIR, "mqtt.log"),
    maxBytes=10*1024*1024,
    backupCount=3,
    encoding="utf-8",
)
fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s %(module)s:%(lineno)d - %(message)s"))
fh.setLevel(logging.INFO)

logger = logging.getLogger("mqtt_listener")
logger.propagate = False
logger.setLevel(logging.INFO)
if not any(getattr(h, "baseFilename", "").endswith("mqtt.log") for h in logger.handlers):
    logger.addHandler(fh)

# Constants

client = None
stop_event = threading.Event()
REPLY_TOPIC = os.environ.get("MQTT_REPLY_TOPIC")


# Hook functions

def on_connect(_client, userdata, flags, rc):
    if rc == 0:
        _client.subscribe(REPLY_TOPIC)
        logger.info("connected to broker, subscribed to %s", REPLY_TOPIC)
    else:
        logger.error("connection to broker failed with rc=%s", rc)


def on_message(_client, userdata, msg):
    # Decode message
    try:
        payload = json.loads(msg.payload.decode())
        logger.debug("payload=%s", payload)
    except Exception:
        logger.exception("invalid json payload")
        return

    # Validate data
    response_type = payload.get("type")

    # Type = state
    if response_type == "state":
        mac_address = payload.get("mac_address")
        value = payload.get("value")
        if mac_address is not None and value is not None:
            logger.info("received reply with payload=%s", payload)
            mqtt_response_state_board(mac_address, value)
        else:
            logger.warning("invalid JSON response for type=sate, mac_address and value fields required")

    # Invalid response
    else:
        logger.warning("invalid JSON response, type field is required")


def shutdown(signum, frame):
    logger.info("received signal %s, shutting down...", signum)
    stop_event.set()
    try:
        if client is not None:
            client.disconnect()
            logger.info("client disconnected")
    except Exception:
        logger.exception("shutdown process error")


# Startup
def run():
    global client
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    client = Client()
    client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message

    loop_started = False

    # Life cycle
    while not stop_event.is_set():
        try:
            client.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=60)
            client.loop_start()
            loop_started = True
            stop_event.wait()
            break
        except Exception:
            logger.exception("failed to connect to MQTT")
            logger.warning("MQTT connection error, retry in 5s...")
            if stop_event.wait(timeout=5):
                break

    # Stop loop
    try:
        if loop_started:
            client.loop_stop()
    except Exception:
        logger.exception("loop stop error")

    # Disconnect
    try:
        if client is not None:
            client.disconnect()
    except Exception:
        logger.exception("client disconnect error")

    logger.info("stopped")


if __name__ == "__main__":
    run()
