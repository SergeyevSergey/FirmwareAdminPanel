import os
import logging
from django_redis import get_redis_connection
from redis.exceptions import RedisError, ConnectionError
from rest_framework import serializers, exceptions
from django.db import IntegrityError, transaction
from utils.functions import publish_mqtt, MqttError
from .tasks import set_board_state_response_timeout
from .models import Board

logger = logging.getLogger(__name__)

COMMON_TOPIC = os.environ.get("MQTT_COMMON_TOPIC")


class BoardSerializer(serializers.ModelSerializer):
    mac_address = serializers.CharField(max_length=32, required=True)

    class Meta:
        model = Board
        fields = "__all__"
        read_only_fields = ["topic"]

    def create(self, validated_data):
        mac_address = validated_data.get("mac_address")
        file_version = validated_data.get("file_version")

        # Validate
        if not mac_address:
            logger.info(
                "validation failed, mac_address=%s file_version=%s",
                mac_address, file_version
            )
            raise serializers.ValidationError(
                {"mac_address, file_version": "these fields are required"}
            )

        # Save
        topic = f"boards/{mac_address}"
        try:
            with transaction.atomic():
                instance = Board.objects.create(
                    topic=topic,
                    file_version=file_version,
                    **validated_data
                )
                logger.info(
                    "Board created, mac_address=%s file_version=%s",
                    mac_address, file_version
                )
                return instance
        except IntegrityError:
            logger.warning(
                "Board create failed: duplicate mac_address=%s",
                mac_address, exc_info=True
            )
            raise serializers.ValidationError({"mac_address": "board with this mac_address already exists"})


class BoardUpdateSerializer(serializers.ModelSerializer):

    class Meta:
        model = Board
        fields = "__all__"
        read_only_fields = ["mac_address", "topic, file_version"]

    def update(self, instance, validated_data):
        # Save
        try:
            with transaction.atomic():
                for attr, val in validated_data.items():
                    setattr(instance, attr, val)
                logger.info(
                    "Board updated, mac-address=%s is_active=%s",
                    instance.mac_address, instance.is_active
                )
                instance.save()
                return instance
        except Exception:
            logger.exception(
                "update failed for mac_address=%s",
                instance.mac_address
            )
            raise exceptions.APIException("failed to save board")


class BoardStateSerializer(serializers.ModelSerializer):
    is_active = serializers.BooleanField(required=False)

    class Meta:
        model = Board
        fields = ["is_active"]

    def update(self, instance, validated_data):
        # Toggle state
        old_state = instance.is_active
        new_state = not old_state

        try:
            cache = get_redis_connection("default")

            # Check if any task keys in Redis (no task keys = execute) (else cancel)
            is_flashing = cache.exists(f"flashing:{instance.mac_address}")

            if is_flashing:
                logger.info(
                    "board is currently flashing with mac_address=%s",
                    instance.mac_address
                )
                raise serializers.ValidationError("board currently flashing")

            # Set pending task key in Redis
            is_set = cache.set(f"pending:{instance.mac_address}", 1, nx=True, ex=60)
            if not is_set:
                logger.info(
                    "command is already pending for mac_address=%s",
                    instance.mac_address
                )
                raise serializers.ValidationError("command already pending")
            else:
                logger.info(
                    "set pending flag for mac_address=%s",
                    instance.mac_address
                )

            # Set timeout
            set_board_state_response_timeout.apply_async((instance.mac_address,), countdown=30)

            # Publish MQTT command
            context = {
                "command": "state",
                "value": new_state
            }
            topic = COMMON_TOPIC + "/" + instance.mac_address
            try:
                publish_mqtt(context, topic)
            except MqttError:
                # delete task key
                cache.delete(f"pending:{instance.mac_address}")
                logger.info(
                    "deleted pending flag for mac_address=%s",
                    instance.mac_address
                )
                # raise error
                raise exceptions.APIException("failed to send mqtt command")
        except (RedisError, ConnectionError):
            logger.exception(
                "state changing failed due to Redis error for mac_address=%s",
                instance.mac_address
            )
            raise exceptions.APIException("state changing operation failed due to Redis error")

        # Success
        return instance
