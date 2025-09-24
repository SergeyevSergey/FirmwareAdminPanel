from django.urls import path
from .views import BoardsListAPI, BoardCreateAPI, BoardDestroyAPI, FlashSingleBoardFirmwareAPI, FlashAllBoardsFirmwareAPI

app_name = "boards"

urlpatterns = [
    path("", BoardsListAPI.as_view(), name="boards_list"),
    path("create/", BoardCreateAPI.as_view(), name="board_create"),
    path("flash/all/", FlashAllBoardsFirmwareAPI.as_view(), name="boards_flash"),
    path("flash/single/", FlashSingleBoardFirmwareAPI.as_view(), name="board_flash"),
    path("delete/<str:mac_address>/", BoardDestroyAPI.as_view(), name="board_delete"),
]
