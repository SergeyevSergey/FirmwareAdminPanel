from rest_framework import serializers
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
        instance = Board.objects.create(topic=topic, **validated_data)
        return instance
