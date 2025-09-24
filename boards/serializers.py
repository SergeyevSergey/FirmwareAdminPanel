from rest_framework import serializers
from django.db import IntegrityError, transaction
from .models import Board


class BoardSerializer(serializers.ModelSerializer):
    mac_address = serializers.CharField(max_length=32, required=True)

    class Meta:
        model = Board
        fields = "__all__"
        read_only_fields = ["topic"]

    def create(self, validated_data):
        mac_address = validated_data["mac_address"]
        topic = f"board/{mac_address}"
        try:
            with transaction.atomic():
                instance = Board.objects.create(topic=topic, **validated_data)
            return instance
        except IntegrityError:
            return serializers.ValidationError({"mac_address": "board with this mac_address already exists"})
