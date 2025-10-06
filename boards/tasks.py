import logging
from utils.functions import ws_send
from django_redis import get_redis_connection
from redis.exceptions import RedisError, ConnectionError
from celery import shared_task


logger = logging.getLogger(__name__)


@shared_task
def set_board_state_response_timeout(mac_address: str, job_id: str):
    try:
        cache = get_redis_connection("default")
        pending = cache.get(f"pending:{mac_address}:{job_id}")

        # Board did not send reply
        if pending:

            logger.info("no reply from mac_address=%s", mac_address)

            cache.delete(f"pending:{mac_address}:{job_id}")
            logger.info("deleted pending flag for mac_address=%s", mac_address)

            event = {
                "type": "board_timeout",
                "command": "state",
                "data": {
                    "mac_address": mac_address
                }
            }
            ws_send(event, "boards")
    except (RedisError, ConnectionError):
        logger.exception("Redis connection error")
    except Exception:
        logger.exception("unexpected error")


@shared_task
def set_board_flash_response_timeout(mac_address: str, job_id: str):
    try:
        cache = get_redis_connection("default")
        flashing = cache.get(f"flashing:{mac_address}:{job_id}")

        # Board did not send reply
        if flashing:
            logger.info("no reply from mac_address=%s", mac_address)

            cache.delete(f"flashing:{mac_address}:{job_id}")
            logger.info("deleted flashing flag for mac_address=%s", mac_address)

            event = {
                "type": "board_timeout",
                "command": "flash",
                "data": {
                    "mac_address": mac_address
                }
            }
            ws_send(event, "boards")
    except (RedisError, ConnectionError):
        logger.exception("Redis connection error")
    except Exception:
        logger.exception("unexpected error")
