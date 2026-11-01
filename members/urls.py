from django.urls import path

from . import views

app_name = "members"

urlpatterns = [
    path("members/", views.member_list, name="member_list"),
    path("members/new/", views.member_edit, name="member_create"),
    path("members/import/", views.member_import, name="member_import"),
    path("members/<int:pk>/", views.member_detail, name="member_detail"),
    path("members/<int:pk>/edit/", views.member_edit, name="member_edit"),
    path("members/<int:pk>/induct/", views.member_induct, name="member_induct"),
    path("members/<int:pk>/portal/", views.member_portal, name="member_portal"),
    path("members/<int:pk>/giving/", views.member_giving, name="member_giving"),
    path("members/link-giving/", views.link_giving, name="link_giving"),
    path("summary/", views.membership_summary, name="summary"),
    path("groups/", views.group_list, name="group_list"),
    path("groups/new/", views.group_edit, name="group_create"),
    path("groups/<int:pk>/", views.group_detail, name="group_detail"),
    path("groups/<int:pk>/edit/", views.group_edit, name="group_edit"),
    path("memberships/<int:pk>/", views.membership_action, name="membership_action"),
    path("sermons/", views.sermon_list, name="sermon_list"),
    path("sermons/new/", views.sermon_edit, name="sermon_create"),
    path("sermons/<int:pk>/", views.sermon_edit, name="sermon_edit"),
    path("sermons/<int:pk>/<str:kind>/", views.sermon_media, name="sermon_media"),
]
