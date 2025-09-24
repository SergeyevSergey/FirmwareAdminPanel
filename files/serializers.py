import uuid
from django.core.files.storage import FileSystemStorage
from rest_framework import serializers
from .models import FirmwareFile


class FirmwareFileSerializer(serializers.ModelSerializer):
    file = serializers.FileField(write_only=True, required=True)

    class Meta:
        model = FirmwareFile
        fields = "__all__"
        read_only_fields = ["uploaded_at", "path"]

    def create(self, validated_data):
        file = validated_data.pop('file', None)
        if not file:
            raise serializers.ValidationError({"file": "This field is required"})
        file_id = uuid.uuid4()
        filename = file.name
        path = FileSystemStorage().save(f"firmware/{file_id}_{filename}", file)
        validated_data["path"] = path
        instance = FirmwareFile.objects.create(id=file_id, **validated_data)
        return instance
