import os
import logging
from rest_framework.generics import CreateAPIView, ListAPIView, DestroyAPIView, UpdateAPIView
from rest_framework.response import Response
from rest_framework.status import HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND, HTTP_200_OK, HTTP_500_INTERNAL_SERVER_ERROR, \
    HTTP_409_CONFLICT, HTTP_202_ACCEPTED
from rest_framework.views import APIView
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework import status
from rest_framework import serializers, exceptions
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from files.models import FirmwareFile
from utils.functions import publish_mqtt, MqttError
from utils.pagination import BoardsListPagination
from .models import Board
from .serializers import BoardSerializer, BoardUpdateSerializer, BoardStateSerializer


logger = logging.getLogger(__name__)
COMMON_TOPIC = os.environ.get("MQTT_COMMON_TOPIC")


# Create your views here.

class BoardsListAPI(ListAPIView):
    queryset = Board.objects.all().order_by("mac_address")
    serializer_class = BoardSerializer
    pagination_class = BoardsListPagination
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer]


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
            return Response({"detail": "already pending"}, status=HTTP_409_CONFLICT)
        except exceptions.APIException:
            return Response({"detail": "unexpected error"}, status=HTTP_500_INTERNAL_SERVER_ERROR)

        # Success, returns 202 Accept to indicate asynchronous pending
        return Response({"detail": "pending"}, status=HTTP_202_ACCEPTED)


class BoardDestroyAPI(DestroyAPIView):
    queryset = Board.objects.all()
    serializer_class = BoardSerializer
    lookup_field = "mac_address"
    permission_classes = [IsAuthenticated]


class FlashSingleBoardFirmwareAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        file_system = FileSystemStorage()
        mac_address = request.data.get("mac_address")
        file_id = request.data.get("file_id")
        if not mac_address or not file_id:
            logger.info("validation failed, mac_address=%s file_id=%s", mac_address, file_id)
            return Response({"detail": "mac_address and file_id fields are required"}, status=status.HTTP_400_BAD_REQUEST)

        # Validate board
        try:
            board = Board.objects.get(mac_address=mac_address)
        except Board.DoesNotExist:
            logger.info("validation failed, Board object does not exist, mac_address=%s", mac_address)
            return Response({"detail": "board object not found"}, status=HTTP_404_NOT_FOUND)

        # Validate file
        try:
            file = FirmwareFile.objects.get(id=file_id)
        except FirmwareFile.DoesNotExist:
            logger.info("validation failed, FirmwareFile object does not exist, file_id=%s", file_id)
            return Response({"detail": "firmware file object not found"}, status=HTTP_404_NOT_FOUND)
        if not file_system.exists(file.path):
            logger.warning("validation failed, file is not on disk, path=%s", file.path)
            return Response({"detail": "firmware file not found on disk"}, status=HTTP_404_NOT_FOUND)

        # Send MQTT message
        download_url = settings.SITE_HOST.rstrip("/") + file_system.url(file.path)
        context = {
            "command": "firmware",
            "url": download_url,
            "version": file.version
        }
        topic = COMMON_TOPIC + "/" + board.mac_address
        try:
            publish_mqtt(context, topic)
        except MqttError:
            return Response({"detail": f"MQTT publish error"}, status=HTTP_500_INTERNAL_SERVER_ERROR)

        logger.info("command published")
        return Response({"detail": "published"}, status=HTTP_200_OK)


class FlashAllBoardsFirmwareAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        file_system = FileSystemStorage()
        file_id = request.data.get("file_id")
        if not file_id:
            logger.info("validation failed, file_id=%s", file_id)
            return Response({"detail": "file_id is required"}, status=HTTP_400_BAD_REQUEST)

        # Validate file
        try:
            file = FirmwareFile.objects.get(id=file_id)
        except FirmwareFile.DoesNotExist:
            logger.info("validation failed, FirmwareFile object does not exist, file_id=%s", file_id)
            return Response({"detail": "firmware file object not found"}, status=HTTP_404_NOT_FOUND)
        if not file_system.exists(file.path):
            logger.warning("validation failed, file is not on disk, path=%s", file.path)
            return Response({"detail": "firmware file not found on disk"}, status=HTTP_404_NOT_FOUND)

        # Send MQTT message
        download_url = settings.SITE_HOST.rstrip("/") + file_system.url(file.path)
        context = {
            "command": "firmware",
            "url": download_url,
            "version": file.version
        }
        topic = COMMON_TOPIC
        try:
            publish_mqtt(context, topic)
        except MqttError:
            return Response({"detail": f"MQTT publish error"}, status=HTTP_500_INTERNAL_SERVER_ERROR)

        logger.info("command published")
        return Response({"detail": "published"}, status=HTTP_200_OK)
