from django.urls import path
from .views import FirmwareFilesListAPI, FirmwareFileCreateAPI, FirmwareFileDestroyAPI, FirmwareFileUpdateAPI

app_name = "files"

urlpatterns = [
    path("", FirmwareFilesListAPI.as_view(), name="files_list"),
    path("create/", FirmwareFileCreateAPI.as_view(), name="file_create"),
    path("update/<uuid:id>/", FirmwareFileUpdateAPI.as_view(), name="file_update"),
    path("delete/<uuid:id>/", FirmwareFileDestroyAPI.as_view(), name="file_delete"),
]
