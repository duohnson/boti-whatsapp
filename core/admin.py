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


from .models import PagoPlan, SuscripcionPlan


@admin.register(PagoPlan, SuscripcionPlan)
class RegistroPagoAdmin(admin.ModelAdmin):
    list_display = ['empresa', 'plan', 'periodo', 'importe', 'estado', 'creado']
    list_filter = ['plan', 'estado']

    def get_readonly_fields(self, request, obj=None):
        return [campo.name for campo in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
