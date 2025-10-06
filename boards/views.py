import os
import logging
import shortuuid
from .models import Board
from .tasks import set_board_flash_response_timeout
from .serializers import BoardSerializer, BoardUpdateSerializer, BoardStateSerializer
from files.models import FirmwareFile
from utils.pagination import BoardsListPagination
from utils.functions import publish_mqtt, MqttError, cache_exists
from django.conf import settings
from django.db.models import Q
from django.core.files.storage import FileSystemStorage
from django_redis import get_redis_connection
from redis.exceptions import RedisError, ConnectionError
from rest_framework import status
from rest_framework import serializers, exceptions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.generics import CreateAPIView, ListAPIView, DestroyAPIView, UpdateAPIView


logger = logging.getLogger(__name__)
file_system = FileSystemStorage()
COMMON_TOPIC = os.environ.get("MQTT_COMMON_TOPIC")


# Create your views here.

class BoardsListAPI(ListAPIView):
    queryset = Board.objects.all().order_by("-created_at")
    serializer_class = BoardSerializer
    pagination_class = BoardsListPagination
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer]

    def get_queryset(self):
        queryset = Board.objects.all()
        mac_address = self.request.query_params.get("mac")
        file_version = self.request.query_params.get("version")
        if mac_address:
            queryset = queryset.filter(
                Q(mac_address__icontains=mac_address)
            )
        if file_version:
            queryset = queryset.filter(file_version=file_version)
        return queryset


class BoardCreateAPI(CreateAPIView):
    queryset = Board.objects.all()
    serializer_class = BoardSerializer
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]


class BoardUpdateAPI(UpdateAPIView):
    queryset = Board.objects.all()
    serializer_class = BoardUpdateSerializer
    lookup_field = "mac_address"
    permission_classes = [IsAuthenticated]
    http_method_names = ["patch"]


class BoardStateAPI(UpdateAPIView):
    queryset = Board.objects.all()
    serializer_class = BoardStateSerializer
    lookup_field = "mac_address"
    permission_classes = [IsAuthenticated]
    http_method_names = ["patch"]

    def patch(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(
            instance=instance,
            data=request.data or {},
            partial=True
        )
        serializer.is_valid(raise_exception=True)

        # Validate serializer
        try:
            serializer.save()
        except serializers.ValidationError:
            return Response({"detail": "currently under operation"}, status=status.HTTP_409_CONFLICT)
        except exceptions.APIException:
            return Response({"detail": "unexpected error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Success, returns 202 Accept to indicate asynchronous pending
        return Response({"detail": "pending"}, status=status.HTTP_202_ACCEPTED)


class BoardDestroyAPI(DestroyAPIView):
    queryset = Board.objects.all()
    serializer_class = BoardSerializer
    lookup_field = "mac_address"
    permission_classes = [IsAuthenticated]


class FlashSingleBoardFirmwareAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        # Fields validation
        mac_address = request.data.get("mac_address")
        file_id = request.data.get("file_id")
        if not mac_address or not file_id:
            logger.info(
                "validation failed, mac_address=%s file_id=%s",
                mac_address, file_id
            )
            return Response(
                data={"detail": "mac_address and file_id fields are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Object validation
        try:
            board = Board.objects.get(mac_address=mac_address)
        except Board.DoesNotExist:
            logger.info(
                "validation failed, Board object does not exist, mac_address=%s",
                mac_address
            )
            return Response(
                data={"detail": "board object not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        # File validation
        try:
            file = FirmwareFile.objects.get(id=file_id)
        except FirmwareFile.DoesNotExist:
            logger.info(
                "validation failed, FirmwareFile object does not exist, file_id=%s",
                file_id
            )
            return Response(
                data={"detail": "firmware file object not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        if not file_system.exists(file.path):
            logger.warning(
                "validation failed, file is not on disk, path=%s",
                file.path
            )
            return Response(
                data={"detail": "firmware file not found on disk"},
                status=status.HTTP_404_NOT_FOUND
            )
        try:
            cache = get_redis_connection("default")

            # Check if any flag for this mac address in Redis (no task keys = execute) (else cancel)
            is_pending = cache_exists(f"pending:{mac_address}")
            is_flashing = cache_exists(f"flashing:{mac_address}")

            if is_pending or is_flashing:
                logger.info(
                    "board with mac_address=%s is currently under operation",
                    mac_address
                )
                return Response(
                    data={"detail": "currently under operation"},
                    status=status.HTTP_409_CONFLICT
                )

            # Set flashing flag in Redis
            job_id = shortuuid.ShortUUID().random(length=8)
            flag = f"flashing:{mac_address}:{job_id}"

            is_set = cache.set(flag, 1, nx=True, ex=330)

            if not is_set:
                logger.warning(
                    "flashing flag %s already exist",
                    flag
                )
                return Response(
                    data={"detail": "collision error"},
                    status=status.HTTP_409_CONFLICT
                )
            else:
                logger.info(
                    "set flashing flag %s",
                    flag
                )

            # Set timeout
            set_board_flash_response_timeout.apply_async((mac_address, job_id), countdown=300)

            # Publish MQTT command
            download_url = settings.SITE_HOST.rstrip("/") + file_system.url(file.path)
            context = {
                "command": "flash",
                "url": download_url,
                "version": file.version
            }
            topic = COMMON_TOPIC + "/" + board.mac_address
            try:
                publish_mqtt(context, topic)
            except MqttError:
                # delete task key
                cache.delete(flag)
                logger.info(
                    "deleted flashing flag %s",
                    flag
                )
                logger.exception(
                    "flashing failed due to MQTT error for mac_address=%s",
                    mac_address
                )
                # return error
                return Response(
                    data={"detail": f"unexpected error"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        except (RedisError, ConnectionError):
            logger.exception("flashing failed due to Redis error for mac_address=%s",mac_address)
        except Exception:
            logger.exception("flashing failed due to unexpected error for mac_address=%s", mac_address)
            return Response(
                data={"detail": "unexpected error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Success, returns 202 Accept to indicate asynchronous flashing
        return Response(data={"detail": "flashing"}, status=status.HTTP_202_ACCEPTED)


class FlashAllBoardsFirmwareAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        # Fields validation
        file_id = request.data.get("file_id")
        if not file_id:
            logger.info(
                "validation failed, file_id=%s",
                file_id
            )
            return Response(
                data={"detail": "file_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # File validation
        try:
            file = FirmwareFile.objects.get(id=file_id)
        except FirmwareFile.DoesNotExist:
            logger.info(
                "validation failed, FirmwareFile object does not exist, file_id=%s",
                file_id
            )
            return Response(
                data={"detail": "firmware file object not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        if not file_system.exists(file.path):
            logger.warning(
                "validation failed, file is not on disk, path=%s",
                file.path
            )
            return Response(
                data={"detail": "firmware file not found on disk"},
                status=status.HTTP_404_NOT_FOUND
            )
        try:
            cache = get_redis_connection("default")

            mac_address_queryset = Board.objects.values_list("mac_address", flat=True)
            flashing_processes = []
            for mac_address in mac_address_queryset:

                # Check if any flags for this mac address in Redis (no task keys = execute) (else cancel)
                is_pending = cache_exists(f"pending:{mac_address}")
                is_flashing = cache_exists(f"flashing:{mac_address}")

                if is_pending or is_flashing:
                    logger.info(
                        "board with mac_address=%s is currently under operation",
                        mac_address
                    )
                    continue

                # Set flashing flag in Redis
                job_id = shortuuid.ShortUUID().random(length=8)
                flag = f"flashing:{mac_address}:{job_id}"

                is_set = cache.set(flag, 1, nx=True, ex=330)

                if not is_set:
                    logger.warning(
                        "flashing flag %s already exist",
                        flag
                    )
                    continue
                flashing_processes.append(flag)
                logger.info(
                    "set flashing flag %s",
                    flag
                )

                # Set timeout
                set_board_flash_response_timeout.apply_async((mac_address, job_id), countdown=300)

            # Publish MQTT command
            download_url = settings.SITE_HOST.rstrip("/") + file_system.url(file.path)
            context = {
                "command": "flash",
                "url": download_url,
                "version": file.version
            }
            topic = COMMON_TOPIC
            try:
                publish_mqtt(context, topic)
            except MqttError:
                # delete task keys
                for flag in flashing_processes:
                    cache.delete(flag)
                    logger.info(
                        "deleted flashing flag %s",
                        flag
                    )
                logger.exception(
                    "mass flashing failed due to MQTT error",
                )
                # return error
                return Response(
                    data={"detail": f"MQTT publish error"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        except (RedisError, ConnectionError):
            logger.exception("mass flashing failed due to Redis error")
            return Response(
                data={"detail": "unexpected error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception:
            logger.exception("mass flashing failed due to unexpected error")
            return Response(
                data={"detail": "unexpected error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Success, returns 202 Accept to indicate asynchronous mass flashing
        return Response({"detail": "flashing"}, status=status.HTTP_202_ACCEPTED)
