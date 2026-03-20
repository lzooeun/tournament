from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('ping/', views.server_ping, name='server_ping'),
]