from django.urls import path

from . import views

app_name = "giving"

urlpatterns = [
    path("batches/", views.batch_list, name="batch_list"),
    path("batches/new/", views.batch_edit, name="batch_create"),
    path("batches/<int:pk>/", views.batch_detail, name="batch_detail"),
    path("batches/<int:pk>/edit/", views.batch_edit, name="batch_edit"),
    path("batches/<int:pk>/post/", views.batch_post, name="batch_post"),
    path("batches/<int:pk>/reopen/", views.batch_unpost, name="batch_unpost"),
    path("batches/<int:pk>/delete/", views.batch_delete, name="batch_delete"),
    path("contributions/<int:pk>/edit/", views.contribution_edit, name="contribution_edit"),
    path("contributions/<int:pk>/delete/", views.contribution_delete, name="contribution_delete"),
    path("donors/", views.donor_list, name="donor_list"),
    path("donors/new/", views.donor_edit, name="donor_create"),
    path("donors/import/", views.donor_import, name="donor_import"),
    path("donors/<int:pk>/", views.donor_detail, name="donor_detail"),
    path("donors/<int:pk>/edit/", views.donor_edit, name="donor_edit"),
    path("donors/<int:pk>/statement/", views.donor_statement, name="donor_statement"),
    path("campaigns/", views.campaign_list, name="campaign_list"),
    path("campaigns/new/", views.campaign_edit, name="campaign_create"),
    path("campaigns/<int:pk>/", views.campaign_detail, name="campaign_detail"),
    path("campaigns/<int:pk>/edit/", views.campaign_edit, name="campaign_edit"),
    path("pledges/new/", views.pledge_edit, name="pledge_create"),
    path("pledges/<int:pk>/", views.pledge_edit, name="pledge_edit"),
    path("statements/", views.statements, name="statements"),
]
