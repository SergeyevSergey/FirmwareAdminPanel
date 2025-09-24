from django.urls import path
from .views import FirmwareFilesListAPI, FirmwareFileCreateAPI, FirmwareFileDestroyAPI

app_name = "files"

urlpatterns = [
    path("", FirmwareFilesListAPI.as_view(), name="files_list"),
    path("create/", FirmwareFileCreateAPI.as_view(), name="file_create"),
    path("delete/<uuid:id>/", FirmwareFileDestroyAPI.as_view(), name="file_delete"),
]
