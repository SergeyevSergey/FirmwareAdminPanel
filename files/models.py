import uuid
from django.db import models


# Create your models here.


class FirmwareFile(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
    )
    version = models.CharField(max_length=64)
    path = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)
