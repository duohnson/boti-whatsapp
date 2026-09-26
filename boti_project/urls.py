"""
URL configuration for boti_project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path, include
from django.views.generic import RedirectView
from core import views

urlpatterns = [
    path('admin/', admin.site.urls),
    # acceso y registro de las cuentas del servicio
    path('cuentas/registro/', views.registro, name='registro'),
    path('cuentas/ingresar/', LoginView.as_view(template_name='registration/login.html'), name='ingresar'),
    path('cuentas/salir/', LogoutView.as_view(), name='salir'),
    path('api/', include('core.urls')),
    path('', RedirectView.as_view(url='/api/dashboard/', permanent=False)),
]
