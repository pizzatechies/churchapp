from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    path("", views.home, name="home"),
    path("groups/", views.groups, name="groups"),
    path("groups/<int:pk>/", views.group_detail, name="group_detail"),
    path("groups/<int:pk>/join/", views.group_join, name="group_join"),
    path("groups/<int:pk>/cancel/", views.group_cancel, name="group_cancel"),
    path("sermons/", views.sermons, name="sermons"),
    path("sermons/<int:pk>/", views.sermon_detail, name="sermon_detail"),
    path("sermons/<int:pk>/<str:kind>/", views.sermon_media, name="sermon_media"),
    path("profile/", views.profile, name="profile"),
    path("profile/password/", views.PasswordChangeView.as_view(), name="password"),
]
