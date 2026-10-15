from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health),
    path("meta/", views.meta),
    path("geocode/", views.geocode),
    path("plan/", views.plan),
    path("plan/<slug:plan_id>/score/", views.plan_score),
    path("heatmap/", views.heatmap),
    path("heatmap/<slug:heatmap_id>/score/", views.heatmap_score),
]
