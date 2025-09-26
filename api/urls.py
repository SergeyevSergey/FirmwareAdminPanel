from django.urls import path
from .views import AccessOnlyTokenObtainView

app_name = "api"

urlpatterns = [
    # Token routes
    path("token/", AccessOnlyTokenObtainView.as_view(), name="token_obtain_access"),
]
