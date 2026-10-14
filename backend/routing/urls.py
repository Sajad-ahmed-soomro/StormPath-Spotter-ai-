from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health),
    path("meta/", views.meta),
    path("geocode/", views.geocode),
    path("plan/", views.plan),
    path("heatmap/", views.heatmap),
]
