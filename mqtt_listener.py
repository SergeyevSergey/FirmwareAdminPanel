import os
import json
import asyncio
import logging
import signal
import uuid
import socket
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import redis.asyncio as aioredis

from functools import partial
from asyncio_mqtt import Client as MQTTClient, MqttError
from boards.models import Board
from asgiref.sync import sync_to_async, async_to_sync
from django_redis import get_redis_connection
from redis.exceptions import RedisError, ConnectionError
from channels.layers import get_channel_layer
from channels.exceptions import InvalidChannelLayerError
from logging.handlers import RotatingFileHandler


# MQTT Logger

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

# system
shutdown_event = asyncio.Event()

# MQTT
MQTT_COMMON_TOPIC = os.environ.get("MQTT_COMMON_TOPIC", "boards")
MQTT_WORKER_COUNT = int(os.environ.get("MQTT_WORKER_COUNT", "10"))
MQTT_HOST = os.environ.get("MQTT_HOST", "emqx")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_REPLY_TOPIC = os.environ.get("MQTT_REPLY_TOPIC", "boards/replies")
MQTT_USER = os.environ.get("MQTT_USER")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD")
STREAM_NAME = os.environ.get("MQTT_STREAM_NAME", f"mqtt:stream:{MQTT_COMMON_TOPIC}")
GROUP_NAME = os.environ.get("MQTT_CONSUMER_GROUP", "mqtt_workers")

# Redis
CONSUMER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_URL = os.environ.get("REDIS_URL", f"redis://{REDIS_HOST}:{REDIS_PORT}/0")


# Helpers

async def ping_mqtt(host: str, port: int, timeout: float):
    try:
        response = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(response, timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

        return True

    except Exception:
        return False

async def create_redis_client():
    return aioredis.from_url(REDIS_URL, decode_responses=True)


async def create_redis_group(redis):
    try:
        await redis.xgroup_create(name=STREAM_NAME, groupname=GROUP_NAME, id="$", mkstream=True)
        logger.info("created consumer group %s on stream %s", GROUP_NAME, STREAM_NAME)
    except Exception as e:
        if "BUSYGROUP" in str(e) or "busy group name" in str(e).lower():
            logger.info("consumer group %s already exists", GROUP_NAME)
        else:
            logger.exception("unexpected error creating consumer group")
            raise


async def async_ws_send(event: dict, group: str):
    try:
        layer = get_channel_layer()

        # async layer sending
        if asyncio.iscoroutinefunction(layer.group_send):
            await layer.group_send(group, event)

        # sync layer sending
        else:
            async_to_sync(layer.group_send)(group, event)

        logger.info("send event=%s to group %s on layer %s", event, group, layer)
    except InvalidChannelLayerError:
        logger.exception("channel layer error while sending WebSocket event")
    except Exception:
        logger.exception("unexpected error while sending WebSocket event")


def install_signal_handlers(loop):
    async def _on_shutdown(sig):
        logger.info("received signal %s, initiating shutdown", sig)
        shutdown_event.set()

    def _handler(signum, frame=None):
        # signal handler
        loop.call_soon_threadsafe(asyncio.create_task, _on_shutdown(signum))

    try:
        loop.add_signal_handler(signal.SIGINT, partial(_handler, signal.SIGINT))
        loop.add_signal_handler(signal.SIGTERM, partial(_handler, signal.SIGTERM))
    except NotImplementedError:
        # fallback
        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)


# Database operations

@sync_to_async
def db_update_board_state(mac_address: str, is_active: bool):
    Board.objects.filter(mac_address=mac_address).update(is_active=is_active)

@sync_to_async
def db_update_board_file_version(mac_address: str, file_version: str):
    Board.objects.filter(mac_address=mac_address).update(file_version=file_version)


# Cache operations

@sync_to_async
def cache_exists(key):
    cache = get_redis_connection("default")
    exists = any(cache.scan_iter(match=f"{key}*"))

    return exists

@sync_to_async
def cache_delete(key):
    cache = get_redis_connection("default")
    return cache.delete(*cache.keys(f"{key}*"))


# Hook functions

# Message handling (Redis): puts messages in Redis stream
async def message_handler(redis):
    logger.info("starting MQTT message holder to host=%s port=%s topic=%s", MQTT_HOST, MQTT_PORT, MQTT_REPLY_TOPIC)

    # Set paho message retry set
    try:
        import paho.mqtt.client as paho
        paho_ver = getattr(paho, "__version__", "unknown")
        if not hasattr(paho.Client, "message_retry_set"):
            def _message_retry_set(self, secs):
                try:
                    setattr(self, "_message_retry", secs)
                except Exception:
                    pass

            paho.Client.message_retry_set = _message_retry_set
            logger.info("paho.Client.message_retry_set patched (paho version=%s)", paho_ver)
        else:
            logger.info("paho.Client.message_retry_set exists (paho version=%s)", paho_ver)
    except Exception:
        logger.exception("failed to inspect or patch paho; continuing anyway")

    # Ping MQTT
    retries = 0
    pong = False
    try:
        while retries < 5 and not pong and not shutdown_event.is_set():
            pong = await ping_mqtt(MQTT_HOST, MQTT_PORT, timeout=1.0)

            if not pong:
                logger.warning("could not get response from MQTT %s:%s, retry in 5s...", MQTT_HOST, MQTT_PORT)
                retries += 1
                await asyncio.sleep(5)
                continue
            else:
                break
        if not pong:
            raise MqttError(f"MQTT {MQTT_HOST}:{MQTT_PORT} unreachable after {retries} attempts")
    except MqttError:
        logger.exception("MQTT client error")

    # Accept message
    try:
        async with MQTTClient(
                hostname=MQTT_HOST,
                port=MQTT_PORT,
        ) as client:
            await client.subscribe(MQTT_REPLY_TOPIC)
            logger.info("subscribed to %s topic", MQTT_REPLY_TOPIC)
            async with client.unfiltered_messages() as messages:
                async for message in messages:
                    try:
                        payload_text = message.payload.decode()
                        await redis.xadd(STREAM_NAME, {"topic": message.topic, "payload": payload_text})
                        logger.info("pushed message from topic=%s to stream %s", message.topic, STREAM_NAME)
                    except Exception:
                        logger.exception("failed to push message from mqtt to redis stream")
                        if shutdown_event.is_set():
                            break
    except MqttError:
        logger.exception("MQTT client error")
    except Exception:
        logger.exception("unexpected error")


# Message processing
async def process_stream_entry(redis, entry_id, fields):
    try:
        # Parce payload fields
        try:
            payload_raw = fields.get("payload")
            payload = json.loads(payload_raw)
        except Exception:
            logger.warning("invalid payload type for entry=%s", entry_id)
            return True

        # Validate type field
        response_type = payload.get("type")
        if not response_type:
            logger.info("invalid JSON response for entry=%s, type field is required", entry_id)
            return True

        # STATE TYPE
        if response_type == "state":
            mac_address = payload.get("mac_address")
            value = payload.get("value")

            # Validate fields
            if mac_address is None or value is None:
                logger.info("invalid JSON response type=state for entry=%s, mac_address and value fields required", entry_id)
                return True

            # Delete Redis task key
            try:
                pending = await cache_exists(f"pending:{mac_address}")

                if pending:
                    if await cache_delete(f"pending:{mac_address}"):
                        logger.info("deleted pending flag for mac_address=%s", mac_address)
                    else:
                        logger.warning("could not delete pending flag for mac_address=%s", mac_address)
                else:
                    logger.warning("reply from mac_address=%s but no pending flag found", mac_address)
            except (RedisError, ConnectionError, Exception):
                logger.exception("Redis connection error")

            # Update object in database
            try:
                await db_update_board_state(mac_address, value)
            except Exception:
                logger.error("Database connection error")
                return False

            # Send WebSocket event
            event = {
                "type": "board_update",
                "command": "state",
                "data": {
                    "mac_address": mac_address,
                    "is_active": value
                }
            }
            await async_ws_send(event, "boards")

            return True

        # FLASH TYPE
        elif response_type == "flash":
            mac_address = payload.get("mac_address")
            version = payload.get("version")

            # Validate fields
            if mac_address is None or version is None:
                logger.info("invalid JSON response type=flash for entry=%s, mac_address and version fields required", entry_id)
                return True

            # Delete Redis task key
            try:
                flashing = await cache_exists(f"flashing:{mac_address}")

                if flashing:
                    if await cache_delete(f"flashing:{mac_address}"):
                        logger.info("deleted flashing flag for mac_address=%s", mac_address)
                    else:
                        logger.warning("could not delete flashing flag for mac_address=%s", mac_address)
                else:
                    logger.warning("reply from mac_address=%s but no flashing flag found", mac_address)
            except (RedisError, ConnectionError, Exception):
                logger.exception("Redis connection error")

            # Update object in database
            try:
                await db_update_board_file_version(mac_address, version)
            except Exception:
                logger.error("Database connection error")
                return False

            # Send WebSocket event
            event = {
                "type": "board_update",
                "command": "flash",
                "data": {
                    "mac_address": mac_address,
                    "file_version": version
                }
            }
            await async_ws_send(event, "boards")

            return True

        # INVALID TYPE
        else:
            logger.info("invalid response type called %s for entry=%s", response_type, entry_id)
            return True

    except Exception:
        logger.exception("unexpected error while processing stream entry")
        return False


# Message reclaimer (Redis): tries to reclaim fallen messages
async def reclaim_pending_messages(redis, idle_threshold_ms=60_000):
    # Main Reclaimer: xautoclaim
    try:
        start = "0-0"
        while True:
            try:
                result = await redis.xautoclaim(
                    STREAM_NAME,
                    GROUP_NAME,
                    CONSUMER_ID,
                    min_idle_time=idle_threshold_ms,
                    start_id=start,
                    count=100
                )
            except AttributeError:
                logger.exception("reclaim pending error (xautoclaim not supported)")
                # xautoclaim not supported
                break

            next_start = None
            entries = None

            if isinstance(result, (tuple, list)):
                if len(result) >= 2:
                    next_start, entries = result[0], result[1]
                else:
                    logger.warning("xautoclaim returned unexpected tuple: %s", result)
                    break
            elif isinstance(result, dict):
                next_start = result.get("next-id") or result.get("next") or result.get("next_start")
                entries = result.get("messages") or result.get("entries") or result.get("messages_list")
            else:
                logger.warning("xautoclaim returned unknown type %s: %s", type(result), result)
                break

            if not entries:
                break

            for item in entries:
                try:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        entry_id, fields = item[0], item[1]
                    elif isinstance(item, dict):
                        entry_id = item.get("id")
                        fields = item.get("message") or item.get("fields")
                    else:
                        logger.warning("unknown xautoclaim entry format: %s", item)
                        continue

                    logger.info("reclaimed entry %s to consumer %s", entry_id, CONSUMER_ID)
                except Exception:
                    logger.exception("failed to handle reclaimed entry: %s", item)

            if next_start:
                start = next_start
            else:
                break

    except Exception:
        logger.exception("reclaim pending error (xautoclaim failed)")

    # Fallback: xpending/xclaim
    try:
        pending = await redis.xpending_range(STREAM_NAME, GROUP_NAME, min='-', max='+', count=100)
        for item in pending:
            entry_id = item[0]
            idle = item[2]
            if idle >= idle_threshold_ms:
                try:
                    await redis.xclaim(
                        STREAM_NAME,
                        GROUP_NAME,
                        CONSUMER_ID,
                        min_idle_time=idle_threshold_ms,
                        message_ids=[entry_id]
                    )
                    logger.info("xclaimed entry %s to consumer %s", entry_id, CONSUMER_ID)
                except Exception:
                    logger.exception("failed to xclaim entry %s", entry_id)
    except Exception:
        logger.exception("fallback reclaim failed")


# Worker loop
async def worker_loop(worker_name: str, redis):
    logger.info("worker %s started", worker_name)
    while not shutdown_event.is_set():
        try:
            response = await redis.xreadgroup(
                groupname=GROUP_NAME,
                consumername=worker_name,
                streams={STREAM_NAME: '>'},
                count=1,
                block=1000
            )
            if not response:
                continue

            for stream, entries in response:
                for entry_id, fields in entries:
                    success = False
                    try:
                        success = await process_stream_entry(redis, entry_id, fields)
                    except Exception:
                        logger.exception("could not process entry %s due to unexpected error", entry_id)

                    if success:
                        try:
                            await redis.xack(STREAM_NAME, GROUP_NAME, entry_id)
                            await redis.xdel(STREAM_NAME, entry_id)
                            logger.info("acked and deleted entry %s", entry_id)
                        except Exception:
                            logger.exception("unexpected error while acking/deleting entry %s", entry_id)
                    else:
                        logger.warning("processing of entry %s failed, left in pending", entry_id)
        except (RedisError, ConnectionError):
            logger.exception("Redis error in worker %s, retrying in 5s...", worker_name)
            await asyncio.sleep(5)
        except Exception:
            logger.exception("unexpected error in worker %s, retrying in 5s...", worker_name)
            await asyncio.sleep(5)

    logger.info("worker %s received shutdown command", worker_name)


# Main


async def main():
    redis = await create_redis_client()
    await create_redis_group(redis)
    await reclaim_pending_messages(redis)

    # Startup
    worker_tasks = []
    for i in range(MQTT_WORKER_COUNT):
        worker_name = f"{CONSUMER_ID}-w{i}"
        worker_tasks.append(asyncio.create_task(
            worker_loop(worker_name, redis)
        ))

    handler_task = asyncio.create_task(message_handler(redis))

    # Shutdown
    try:
        await shutdown_event.wait()
    finally:
        logger.info("shutdown requested, canceling tasks...")
        handler_task.cancel()

        for task in worker_tasks:
            task.cancel()

        await asyncio.gather(handler_task, *worker_tasks, return_exceptions=True)

        try:
            await redis.close()
            await redis.connection_pool.disconnect()
        except Exception:
            logger.exception("error closing redis")
        logger.info("stopped main loop")



if __name__ == "__main__":
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        install_signal_handlers(loop)
        loop.run_until_complete(main())
    except Exception:
        logger.exception("fatal error in mqtt listener")
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()
