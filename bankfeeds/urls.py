from django.urls import path

from . import views

app_name = "bankfeeds"

urlpatterns = [
    path("<int:account_pk>/", views.feed, name="feed"),
    path("<int:account_pk>/link/", views.link, name="link"),
    path("<int:account_pk>/unlink/", views.unlink, name="unlink"),
    path("<int:account_pk>/import/", views.import_statement, name="import"),
    path("<int:account_pk>/match/", views.auto_match, name="auto_match"),
    path("<int:account_pk>/register/", views.register, name="register"),
    path("line/<int:pk>/", views.line_action, name="line_action"),
]

# Safaricom posts payments here. No login: the long token in the address identifies the account.
# (Safaricom refuses callback addresses containing "mpesa" or "safaricom".)
callback_urlpatterns = [
    path("bank-feed/c2b/<str:token>/confirm/", views.c2b_confirm, name="c2b_confirm"),
    path("bank-feed/c2b/<str:token>/validate/", views.c2b_validate, name="c2b_validate"),
]
