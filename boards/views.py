from rest_framework.generics import CreateAPIView, ListAPIView, DestroyAPIView
from rest_framework.response import Response
from rest_framework.status import HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND, HTTP_200_OK, HTTP_500_INTERNAL_SERVER_ERROR
from rest_framework.views import APIView
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework import status
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from files.models import FirmwareFile
from utils.functions import publish_mqtt
from .models import Board
from .serializers import BoardSerializer

# Create your views here.

class BoardsListAPI(ListAPIView):
    queryset = Board.objects.all()
    serializer_class = BoardSerializer
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer]


class BoardCreateAPI(CreateAPIView):
    queryset = Board.objects.all()
    serializer_class = BoardSerializer
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]


class BoardDestroyAPI(DestroyAPIView):
    queryset = Board.objects.all()
    serializer_class = BoardSerializer
    lookup_field = "mac_address"
    permission_classes = [IsAuthenticated]


class FlashSingleBoardFirmwareAPI(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request, *args, **kwargs):
        mac_address = request.data.get("mac_address")
        file_id = request.data.get("file_id")
        if not mac_address or not file_id:
            return Response({"detail": "mac_address and file_id are required"}, status=status.HTTP_400_BAD_REQUEST)
        # Validate board
        try:
            board = Board.objects.get(mac_address=mac_address)
        except Board.DoesNotExist:
            return Response({"detail": "board object not found"}, status=HTTP_404_NOT_FOUND)
        # Validate file
        file_system = FileSystemStorage()
        try:
            file = FirmwareFile.objects.get(id=file_id)
        except FirmwareFile.DoesNotExist:
            return Response({"detail": "firmware file object not found"}, status=HTTP_404_NOT_FOUND)
        if not file_system.exists(file.path):
            return Response({"detail": "firmware file not found on disk"}, status=HTTP_404_NOT_FOUND)
        # Send MQTT message
        download_url = settings.SITE_HOST.rstrip("/") + file_system.url(file.path)
        context = {
            "command": "firmware",
            "url": download_url,
            "version": file.version
        }
        topic = "boards/" + board.mac_address
        try:
            publish_mqtt(context, topic)
        except Exception as e:
            return Response({"detail": f"MQTT publish error {str(e)}"}, status=HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({"detail": "published"}, status=HTTP_200_OK)


class FlashAllBoardsFirmwareAPI(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request, *args, **kwargs):
        file_id = request.data.get("file_id")
        if not file_id:
            return Response({"detail": "file_id is required"}, status=HTTP_400_BAD_REQUEST)
        # Validate file
        file_system = FileSystemStorage()
        try:
            file = FirmwareFile.objects.get(id=file_id)
        except FirmwareFile.DoesNotExist:
            return Response({"detail": "firmware file object not found"}, status=HTTP_404_NOT_FOUND)
        if not file_system.exists(file.path):
            return Response({"detail": "firmware file not found on disk"}, status=HTTP_404_NOT_FOUND)
        # Send MQTT message
        download_url = settings.SITE_HOST.rstrip("/") + file_system.url(file.path)
        context = {
            "command": "firmware",
            "url": download_url,
            "version": file.version
        }
        topic = "boards"
        try:
            publish_mqtt(context, topic)
        except Exception as e:
            return Response({"detail": f"MQTT publish error: {str(e)}"}, status=HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({"detail": "published"}, status=HTTP_200_OK)
