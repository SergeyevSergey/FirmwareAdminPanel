import uuid
import logging
from .models import FirmwareFile
from django.db import transaction, IntegrityError
from django.core.files.storage import FileSystemStorage
from rest_framework import serializers, exceptions


logger = logging.getLogger(__name__)


class FirmwareFileSerializer(serializers.ModelSerializer):
    file = serializers.FileField(write_only=True, required=True)

    class Meta:
        model = FirmwareFile
        fields = "__all__"
        read_only_fields = ["id", "uploaded_at", "path"]

    def create(self, validated_data):
        file_system = FileSystemStorage()
        file = validated_data.pop("file", None)

        # Validate
        if not file:
            logger.info(
                "validation failed file=%s",
                file
            )
            raise serializers.ValidationError({"file": "this field is required"})

        # Upload
        file_id = uuid.uuid4()
        filename = file.name
        try:
            path = file_system.save(f"firmware/{file_id}_{filename}", file)
            logger.info(
                "file uploaded successfully, file_id=%s filename=%s",
                file_id, filename
            )
        except Exception:
            logger.exception(
                "upload failed for file_id=%s filename=%s",
                file_id, filename
            )
            raise exceptions.APIException(f"failed to upload file")

        validated_data["path"] = path

        # Save
        try:
            with transaction.atomic():
                instance = FirmwareFile.objects.create(id=file_id, **validated_data)
                logger.info(
                    "FirmwareFile created, path=%s",
                    path
                )
                return instance
        except IntegrityError:
            if path and file_system.exists(path):
                file_system.delete(path)
            logger.warning(
                "FirmwareFile create failed: duplicate file_id=%s",
                file_id, exc_info=True
            )
            raise serializers.ValidationError({"id": "file integrity error"})
        except Exception:
            if path and file_system.exists(path):
                file_system.delete(path)
            logger.exception(
                "save failed for file_id=%s filename=%s",
                file_id, filename
            )
            raise exceptions.APIException("failed to save file")


class FirmwareFileUpdateSerializer(serializers.ModelSerializer):
    file = serializers.FileField(write_only=True, required=True)

    class Meta:
        model = FirmwareFile
        fields = "__all__"
        read_only_fields = ["id", "uploaded_at", "path"]

    def update(self, instance, validated_data):
        file_system = FileSystemStorage()
        new_file = validated_data.pop("file", None)

        # Validate
        if not new_file:
            logger.info(
                "validation failed, file=%s",
                new_file
            )
            raise serializers.ValidationError({"file": "this field is required"})

        # Upload new file
        new_file_id = uuid.uuid4()
        new_filename = new_file.name
        try:
            new_path = file_system.save(f"firmware/{new_file_id}_{new_filename}", new_file)
            logger.info(
                "file uploaded successfully, file_id=%s filename=%s",
                new_file_id, new_filename
            )
        except Exception:
            logger.exception(
                "upload failed for file_id=%s filename=%s",
                new_file_id, new_filename
            )
            raise exceptions.APIException(f"failed to upload new file")

        # Save
        old_path = instance.path
        try:
            with transaction.atomic():
                instance.path = new_path
                for attr, val in validated_data.items():
                    setattr(instance, attr, val)
                instance.save()
                logger.info(
                    "FirmwareFile updated, path=%s",
                    new_path
                )
        except IntegrityError:
            if file_system.exists(new_path):
                file_system.delete(new_path)
            logger.warning(
                "FirmwareFile update failed: duplicate file_id=%s",
                new_file_id, exc_info=True
            )
            raise serializers.ValidationError({"id": "file integrity error"})
        except Exception:
            if file_system.exists(new_path):
                file_system.delete(new_path)
            logger.exception(
                "update failed for file_id=%s filename=%s",
                new_file_id, new_filename
            )
            raise exceptions.APIException("failed to update file")

        # Delete old file
        try:
            if file_system.exists(old_path):
                file_system.delete(old_path)
        except Exception:
            logger.exception(
                "deletion failed for old file with path=%s",
                old_path
            )
            pass

        return instance
