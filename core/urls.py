from django.urls import path

from . import dashboard, pwa, views

urlpatterns = [
    path("", dashboard.dashboard, name="dashboard"),
    path("healthz/", views.health, name="health"),
    path("manifest.webmanifest", pwa.manifest, name="manifest"),
    path("sw.js", pwa.service_worker, name="service_worker"),
    path("offline/", pwa.offline, name="offline"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/close-books/", views.close_books, name="close_books"),
    path("settings/subscription/", views.subscription, name="subscription"),
    path("settings/users/", views.user_list, name="user_list"),
    path("settings/users/new/", views.user_edit, name="user_create"),
    path("settings/users/<int:pk>/", views.user_edit, name="user_edit"),
    path("settings/audit/", views.audit_log, name="audit_log"),
    path("settings/backup/", views.backup, name="backup"),
    path("documents/upload/<int:content_type_id>/<int:object_id>/", views.document_upload, name="document_upload"),
    path("documents/<int:pk>/", views.document_download, name="document_download"),
    path("documents/<int:pk>/delete/", views.document_delete, name="document_delete"),
]
