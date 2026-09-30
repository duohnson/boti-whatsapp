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
from django.contrib.auth.views import LogoutView
from django.urls import path, include
from django.views.generic import RedirectView
from core import views, vistas_seguridad

urlpatterns = [
    path('admin/login/', RedirectView.as_view(url='/cuentas/ingresar/?next=/admin/', permanent=False)),
    path('admin/', admin.site.urls),
    # acceso y registro de las cuentas del servicio
    path('cuentas/registro/', vistas_seguridad.registro, name='registro'),
    path('cuentas/ingresar/', vistas_seguridad.ingresar, name='ingresar'),
    path('cuentas/verificar/', vistas_seguridad.verificar, name='verificar_codigo'),
    path('cuentas/reenviar/', vistas_seguridad.reenviar, name='reenviar_codigo'),
    path('cuentas/correo/', vistas_seguridad.cambiar_correo, name='cambiar_correo'),
    path('cuentas/clave/', vistas_seguridad.cambiar_clave, name='cambiar_clave'),
    path('cuentas/salir/', LogoutView.as_view(), name='salir'),
    path('api/', include('core.urls')),
    path('', RedirectView.as_view(url='/api/dashboard/', permanent=False)),
]
