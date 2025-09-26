from typing import Any

from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

class AccessOnlyTokenObtainSerializer(TokenObtainPairSerializer):

    def validate(self, attrs):
        data = super().validate(attrs)
        access = data.get("access")
        return {"access": access}
