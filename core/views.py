import json
import secrets
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from .forms import ConfiguracionEmpresaForm, NodoBotForm, OpcionNodoForm
from .models import Empresa, SesionWhatsApp, CicloFacturacion, NodoBot, OpcionNodo, SesionUsuario, HistorialChat
from .conversaciones import procesar_mensaje_whatsapp
from .utils import solicitar_whatsapp, enviar_mensaje_whatsapp


def registro(request):
    # al registrarse creo su empresa y lo mando a su panel
    formulario = UserCreationForm(request.POST or None)
    if request.method == 'POST' and formulario.is_valid():
        usuario = formulario.save()
        # cada cuenta arranca con su propia empresa
        Empresa.objects.create(propietario=usuario)
        login(request, usuario)
        return redirect('dashboard')
    return render(request, 'registration/registro.html', {'formulario': formulario})

def solicitud_interna_autorizada(request):
    # node usa este secreto cuando devuelve estados y mensajes
    secreto = settings.WHATSAPP_INTERNAL_SECRET
    recibido = request.headers.get('Authorization', '')
    return bool(secreto) and secrets.compare_digest(recibido, f'Bearer {secreto}')

@login_required
def dashboard(request):
    # cargo solo la conexion y el consumo de esta cuenta
    empresa = Empresa.objects.filter(propietario=request.user).first()
    sesion = SesionWhatsApp.objects.filter(empresa=empresa).first() if empresa else None
    hoy = timezone.localtime()
    ciclo = CicloFacturacion.objects.filter(empresa=empresa, mes=hoy.month, anio=hoy.year).first() if empresa else None
    return render(request, 'core/dashboard.html', {
        'sesion': sesion,
        'mensajes_ia': ciclo.conteo_mensajes_ia if ciclo else 0,
        'empresa': empresa,
    })


def obtener_empresa(request):
    # creo la empresa si la cuenta todavia no tiene una
    empresa, _ = Empresa.objects.get_or_create(
        propietario=request.user,
        defaults={'prompt_sistema_ia': 'Eres un asistente virtual'},
    )
    return empresa

@login_required
@require_GET
def estado_whatsapp(request):
    sesion = SesionWhatsApp.objects.filter(empresa__propietario=request.user).first()
    if not sesion:
        return JsonResponse({'estado': 'desconectado', 'numero_telefono': '', 'codigo_qr': ''})
    return JsonResponse({
        'estado': sesion.estado,
        'numero_telefono': sesion.numero_telefono,
        'codigo_qr': sesion.codigo_qr,
    })

@login_required
@require_POST
def conectar_whatsapp(request):
    # creo una sesion propia antes de pedirle el qr a node
    empresa = obtener_empresa(request)
    sesion, _ = SesionWhatsApp.objects.get_or_create(empresa=empresa)
    if sesion.estado == 'conectado':
        return JsonResponse({'estado': sesion.estado})

    sesion.estado = 'autenticando'
    sesion.codigo_qr = ''
    sesion.save(update_fields=['estado', 'codigo_qr'])
    try:
        solicitar_whatsapp('/api/sesiones/iniciar/', {'identificador': str(sesion.identificador)})
    except Exception:
        sesion.estado = 'error'
        sesion.save(update_fields=['estado'])
        return JsonResponse({'estado': 'error', 'error': 'No se pudo iniciar el servicio de WhatsApp'}, status=503)
    return JsonResponse({'estado': sesion.estado})

@login_required
@require_POST
def desconectar_whatsapp(request):
    sesion = SesionWhatsApp.objects.filter(empresa__propietario=request.user).first()
    if not sesion:
        return JsonResponse({'estado': 'desconectado'})
    try:
        solicitar_whatsapp(f'/api/sesiones/{sesion.identificador}/desconectar/')
    except Exception:
        sesion.estado = 'error'
        sesion.save(update_fields=['estado'])
        return JsonResponse({'estado': 'error', 'error': 'No se pudo desconectar el servicio de WhatsApp'}, status=503)
    sesion.estado = 'desconectado'
    sesion.codigo_qr = ''
    sesion.numero_telefono = ''
    sesion.fecha_conexion = None
    sesion.ultima_actividad = timezone.now()
    sesion.save(update_fields=['estado', 'codigo_qr', 'numero_telefono', 'fecha_conexion', 'ultima_actividad'])
    return JsonResponse({'estado': sesion.estado})

@csrf_exempt
def evento_whatsapp_interno(request):
    # aqui llegan los cambios de estado y mensajes de whatsapp-web.js
    if not solicitud_interna_autorizada(request):
        return JsonResponse({'error': 'No autorizado'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    try:
        datos = json.loads(request.body)
        sesion = SesionWhatsApp.objects.select_related('empresa').get(identificador=datos['identificador'])
        if datos.get('tipo') == 'mensaje':
            if not sesion.empresa.activo or sesion.estado != 'conectado':
                return JsonResponse({'error': 'Sesión no conectada'}, status=409)
            try:
                procesar_mensaje_whatsapp(
                    sesion.identificador,
                    datos['telefono_cliente'],
                    datos['texto'],
                    datos.get('id_mensaje', ''),
                    datos.get('destino') or None,
                )
            except Exception:
                logger = __import__('logging').getLogger(__name__)
                logger.exception('Error al procesar mensaje entrante de WhatsApp')
                return JsonResponse({'estado': 'recibido', 'error': 'mensaje no procesado'}, status=200)
            sesion.refresh_from_db()
            sesion.ultima_actividad = timezone.now()
            sesion.save(update_fields=['ultima_actividad'])
            return JsonResponse({'estado': 'recibido'})

        estado = datos.get('estado')
        if estado not in dict(SesionWhatsApp.ESTADOS):
            return JsonResponse({'error': 'Estado no válido'}, status=400)
        sesion.estado = estado
        sesion.codigo_qr = datos.get('codigo_qr', '') if estado == 'esperando_qr' else ''
        if datos.get('numero_telefono'):
            sesion.numero_telefono = datos['numero_telefono']
        if estado == 'conectado':
            sesion.fecha_conexion = timezone.now()
        elif estado == 'desconectado':
            sesion.fecha_conexion = None
            sesion.numero_telefono = ''
        sesion.ultima_actividad = timezone.now()
        sesion.save()
        return JsonResponse({'estado': 'actualizado'})
    except (KeyError, ValueError, json.JSONDecodeError):
        return JsonResponse({'error': 'Evento no válido'}, status=400)
    except SesionWhatsApp.DoesNotExist:
        return JsonResponse({'error': 'Sesión no encontrada'}, status=404)

@csrf_exempt
def sesiones_whatsapp_internas(request):
    if not solicitud_interna_autorizada(request):
        return JsonResponse({'error': 'No autorizado'}, status=401)
    if request.method != 'GET':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    sesiones = SesionWhatsApp.objects.filter(
        estado__in=['conectado', 'esperando_qr', 'autenticando']
    ).values_list('identificador', flat=True)
    return JsonResponse({'identificadores': [str(identificador) for identificador in sesiones]})


@login_required
def configuracion_bot(request):
    # el editor siempre trabaja con los pasos de esta empresa
    empresa = obtener_empresa(request)
    formulario = ConfiguracionEmpresaForm(request.POST or None, instance=empresa)
    if request.method == 'POST' and formulario.is_valid():
        formulario.save()
        return redirect('configuracion_bot')

    nodos = NodoBot.objects.filter(empresa=empresa).prefetch_related('opciones_salida__nodo_siguiente').order_by('id')
    pasos = []
    for nodo in nodos:
        opciones = []
        for opcion in nodo.opciones_salida.all():
            opciones.append({
                'objeto': opcion,
                'formulario': OpcionNodoForm(instance=opcion, empresa=empresa),
            })
        pasos.append({
            'objeto': nodo,
            'formulario': NodoBotForm(instance=nodo, empresa=empresa),
            'formulario_opcion': OpcionNodoForm(empresa=empresa),
            'opciones': opciones,
        })
    return render(request, 'core/configuracion_bot.html', {
        'empresa': empresa,
        'formulario': formulario,
        'formulario_nodo': NodoBotForm(empresa=empresa),
        'pasos': pasos,
    })


@login_required
@require_POST
def guardar_nodo(request, nodo_id=None):
    empresa = obtener_empresa(request)
    instancia = get_object_or_404(NodoBot, pk=nodo_id, empresa=empresa) if nodo_id else None
    formulario = NodoBotForm(request.POST, instance=instancia, empresa=empresa)
    if formulario.is_valid():
        formulario.save()
        messages.success(request, 'Se guardó el paso del bot.')
    else:
        messages.error(request, 'No se guardó el paso. Revisa los campos e inténtalo de nuevo.')
    return redirect('configuracion_bot')


@login_required
@require_POST
def eliminar_nodo(request, nodo_id):
    empresa = obtener_empresa(request)
    get_object_or_404(NodoBot, pk=nodo_id, empresa=empresa).delete()
    return redirect('configuracion_bot')


@login_required
@require_POST
def guardar_opcion(request, nodo_id, opcion_id=None):
    # el paso padre y el destino quedan dentro del mismo cliente
    empresa = obtener_empresa(request)
    nodo = get_object_or_404(NodoBot, pk=nodo_id, empresa=empresa)
    instancia = get_object_or_404(OpcionNodo, pk=opcion_id, nodo_padre=nodo) if opcion_id else None
    formulario = OpcionNodoForm(request.POST, request.FILES, instance=instancia, empresa=empresa)
    if formulario.is_valid():
        opcion = formulario.save(commit=False)
        opcion.nodo_padre = nodo
        opcion.save()
        messages.success(request, 'Se guardó la opción.')
    else:
        messages.error(request, 'No se guardó la opción. Comprueba el destino y que el adjunto sea un PDF válido de hasta 15 MB.')
    return redirect('configuracion_bot')


@login_required
@require_POST
def eliminar_opcion(request, nodo_id, opcion_id):
    nodo = get_object_or_404(NodoBot, pk=nodo_id, empresa__propietario=request.user)
    get_object_or_404(OpcionNodo, pk=opcion_id, nodo_padre=nodo).delete()
    return redirect('configuracion_bot')


@login_required
def atencion_humana(request):
    # muestro los chats que esperan a una persona y los que ya cerraron
    empresa = Empresa.objects.filter(propietario=request.user).first()
    conversaciones = SesionUsuario.objects.none()
    if empresa:
        conversaciones = SesionUsuario.objects.filter(
            empresa=empresa,
            estado__in=['humano', 'cerrada'],
        ).prefetch_related('historialchat_set').order_by('-ultima_actividad')
    return render(request, 'core/atencion_humana.html', {'conversaciones': conversaciones})


@login_required
@require_POST
def responder_agente(request, sesion_id):
    # solo permito responder si el chat de esta empresa espera un agente
    sesion_chat = get_object_or_404(
        SesionUsuario.objects.select_related('empresa'),
        pk=sesion_id,
        empresa__propietario=request.user,
        estado='humano',
    )
    texto = request.POST.get('texto', '').strip()
    if texto:
        whatsapp = get_object_or_404(SesionWhatsApp, empresa=sesion_chat.empresa, estado='conectado')
        enviar_mensaje_whatsapp(whatsapp, sesion_chat.telefono_cliente, texto)
        HistorialChat.objects.create(sesion_usuario=sesion_chat, rol='agent', contenido=texto)
        sesion_chat.ultima_actividad = timezone.now()
        sesion_chat.save(update_fields=['ultima_actividad'])
    return redirect('atencion_humana')


@login_required
@require_POST
def cambiar_estado_conversacion(request, sesion_id, estado):
    # desde el panel se puede cerrar el chat o devolverlo al bot
    sesion_chat = get_object_or_404(
        SesionUsuario,
        pk=sesion_id,
        empresa__propietario=request.user,
        estado__in=['humano', 'cerrada'],
    )
    if estado == 'cerrada':
        sesion_chat.estado = 'cerrada'
        sesion_chat.activo = False
    elif estado == 'bot':
        sesion_chat.estado = 'bot'
        sesion_chat.activo = True
        sesion_chat.nodo_actual = None
    else:
        return JsonResponse({'error': 'Estado no válido'}, status=400)
    sesion_chat.save(update_fields=['estado', 'activo', 'nodo_actual', 'ultima_actividad'])
    return redirect('atencion_humana')


@csrf_exempt
def archivo_opcion_interno(request, identificador, opcion_id):
    # node solo puede bajar archivos de la sesion que esta atendiendo
    if not solicitud_interna_autorizada(request):
        return JsonResponse({'error': 'No autorizado'}, status=401)
    if request.method != 'GET':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    whatsapp = get_object_or_404(SesionWhatsApp, identificador=identificador, estado='conectado')
    opcion = get_object_or_404(
        OpcionNodo.objects.select_related('nodo_padre'),
        pk=opcion_id,
        nodo_padre__empresa=whatsapp.empresa,
    )
    if not opcion.archivo_pdf:
        return JsonResponse({'error': 'Esta opción no tiene PDF'}, status=404)
    return FileResponse(opcion.archivo_pdf.open('rb'), as_attachment=True, filename=opcion.archivo_pdf.name.rsplit('/', 1)[-1], content_type='application/pdf')
