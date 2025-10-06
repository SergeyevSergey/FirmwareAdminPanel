import logging
from .models import FirmwareFile
from .serializers import FirmwareFileSerializer, FirmwareFileUpdateSerializer
from django.db.models import Q
from django.core.files.storage import FileSystemStorage
from rest_framework import status
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.generics import ListAPIView, CreateAPIView, DestroyAPIView, UpdateAPIView


logger = logging.getLogger(__name__)


# Create your views here.

class FirmwareFilesListAPI(ListAPIView):
    queryset = FirmwareFile.objects.order_by("-uploaded_at")
    serializer_class = FirmwareFileSerializer
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer]

    def get_queryset(self):
        queryset = FirmwareFile.objects.all()
        version = self.request.query_params.get("version")
        if version:
            queryset = queryset.filter(
                Q(version__icontains=version)
            )
        return queryset


class FirmwareFileCreateAPI(CreateAPIView):
    queryset = FirmwareFile.objects.all()
    serializer_class = FirmwareFileSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]


class FirmwareFileUpdateAPI(UpdateAPIView):
    queryset = FirmwareFile.objects.all()
    serializer_class = FirmwareFileUpdateSerializer
    lookup_field = "id"
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    http_method_names = ["patch"]


class FirmwareFileDestroyAPI(DestroyAPIView):
    queryset = FirmwareFile.objects.all()
    serializer_class = FirmwareFileSerializer
    lookup_field = "id"
    permission_classes = [IsAuthenticated]

    def perform_destroy(self, instance):
        file_system = FileSystemStorage()
        path = getattr(instance, "path", None)

        # No file uploaded
        if not path:
            logger.info(
                "validation failed, path=%s",
                path
            )
            return super().perform_destroy(instance)

        # Delete uploaded file
        try:
            if file_system.exists(path):
                file_system.delete(path)
        except Exception as e:
            logger.info(
                "validation failed, file is not on disk, path=%s",
                path
            )
            raise

        # Delete instance
        return super().perform_destroy(instance)

    def delete(self, request, *args, **kwargs):
        try:
            return super().delete(request, *args, **kwargs)
        except Exception:
            logger.exception("file deletion failed")
            return Response(
                data={"detail": "unexpected error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
