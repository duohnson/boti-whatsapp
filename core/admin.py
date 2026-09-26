from django.contrib import admin
from .models import Empresa, CicloFacturacion, NodoBot, OpcionNodo, SesionUsuario, HistorialChat

admin.site.register(Empresa)
admin.site.register(CicloFacturacion)
admin.site.register(NodoBot)
admin.site.register(OpcionNodo)
admin.site.register(SesionUsuario)
admin.site.register(HistorialChat)
