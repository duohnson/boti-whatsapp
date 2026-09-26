from django.contrib import admin
from .models import Empresa, SesionWhatsApp, CicloFacturacion, NodoBot, OpcionNodo, SesionUsuario, HistorialChat

admin.site.register(Empresa)
# desde admin puedo revisar el qr y el estado de cada numero
admin.site.register(SesionWhatsApp)
admin.site.register(CicloFacturacion)
admin.site.register(NodoBot)
admin.site.register(OpcionNodo)
admin.site.register(SesionUsuario)
admin.site.register(HistorialChat)
