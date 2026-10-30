from django.urls import path

from . import views

app_name = "fixedassets"

urlpatterns = [
    path("", views.asset_list, name="asset_list"),
    path("new/", views.asset_edit, name="asset_create"),
    path("<int:pk>/", views.asset_detail, name="asset_detail"),
    path("<int:pk>/edit/", views.asset_edit, name="asset_edit"),
    path("<int:pk>/dispose/", views.asset_dispose, name="asset_dispose"),
    path("depreciation/", views.run_list, name="run_list"),
    path("depreciation/new/", views.run_create, name="run_create"),
    path("depreciation/<int:pk>/", views.run_detail, name="run_detail"),
    path("depreciation/<int:pk>/void/", views.run_void, name="run_void"),
]
