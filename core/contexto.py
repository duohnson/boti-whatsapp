from .models import SesionUsuario, SesionWhatsApp
from .planes import resumen_plan
from .cuentas import empresa_actual, empresas_usuario


def avisos_cuenta(request):
    if not request.user.is_authenticated:
        return {}
    empresa = empresa_actual(request, crear=False)
    pendientes = SesionUsuario.objects.filter(empresa=empresa, estado='humano') if empresa else SesionUsuario.objects.none()
    return {
        'empresa_activa': empresa,
        'consumo_plan': resumen_plan(empresa) if empresa else None,
        'propietario_activo': bool(empresa and empresa.propietario_id == request.user.pk),
        'empresas_disponibles': empresas_usuario(request.user).select_related('propietario'),
        'chats_pendientes': pendientes.count(),
        'whatsapp_conectado': bool(empresa and SesionWhatsApp.objects.filter(empresa=empresa, estado='conectado').exists()),
        'avisos': [{'texto': f'{chat.telefono_cliente} espera atención humana', 'fecha': chat.ultima_actividad}
                   for chat in pendientes.order_by('-ultima_actividad')[:5]],
    }
