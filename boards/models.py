from django.db import models


# Create your models here.


class Board(models.Model):
    mac_address = models.CharField(
        max_length=32,
        primary_key=True,
    )
    topic = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True)
