import logging
from celery import shared_task
from django_redis import get_redis_connection
from redis.exceptions import RedisError, ConnectionError
from utils.functions import ws_send

logger = logging.getLogger(__name__)


@shared_task
def mark_board_reply_timeout(mac_address: str):
    try:
        cache = get_redis_connection("default")
        pending = cache.get(f"pending:{mac_address}")

        # Board did not send reply
        if pending:
            logger.info("no reply from mac_address=%s", mac_address)
            cache.delete(f"pending:{mac_address}")
            logger.info("deleted pending flag for mac_address=%s", mac_address)
            event = {
                "type": "board_timeout",
                "data": {
                    "mac_address": mac_address
                }
            }
            ws_send(event, "boards")

    except (RedisError, ConnectionError):
        logger.exception("Redis connection error")
    except Exception:
        logger.exception("unexpected error")
