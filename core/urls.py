from django.urls import path
from . import views

urlpatterns = [
    path('webhook/', views.webhook_whatsapp, name='webhook_whatsapp'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard-datos/', views.dashboard_datos, name='dashboard_datos'),
]
