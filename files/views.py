from rest_framework.generics import ListAPIView, CreateAPIView, DestroyAPIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework import status
from django.core.files.storage import FileSystemStorage
from .models import FirmwareFile
from .serializers import FirmwareFileSerializer

# Create your views here.

class FirmwareFilesListAPI(ListAPIView):
    queryset = FirmwareFile.objects.order_by("-uploaded_at")
    serializer_class = FirmwareFileSerializer
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer]


class FirmwareFileCreateAPI(CreateAPIView):
    queryset = FirmwareFile.objects.all()
    serializer_class = FirmwareFileSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]


class FirmwareFileDestroyAPI(DestroyAPIView):
    queryset = FirmwareFile.objects.all()
    serializer_class = FirmwareFileSerializer
    lookup_field = "id"
    permission_classes = [IsAuthenticated]

    def perform_destroy(self, instance):
        file_system = FileSystemStorage()
        path = getattr(instance, "path", None)
        if not path:
            return super().perform_destroy(instance)
        try:
            if file_system.exists(path):
                file_system.delete(path)
        except Exception as e:
            raise
        return super().perform_destroy(instance)

    def delete(self, request, *args, **kwargs):
        try:
            return super().delete(request, *args, **kwargs)
        except Exception as e:
            return Response(
                {"detail": "File deletion error: %s" % str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
