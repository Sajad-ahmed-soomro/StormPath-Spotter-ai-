from django.urls import include, path, re_path

from routing.views import spa_index

urlpatterns = [
    path("api/", include("routing.urls")),
    # Everything else is the single-page React app.
    re_path(r"^(?!api/|static/|assets/).*$", spa_index),
]
