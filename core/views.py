import json
import secrets
import logging
import re
import uuid
from datetime import timedelta
from django.db import transaction
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.urls import reverse
from django.db.models import Count, OuterRef, Subquery
from django.db.models.functions import TruncDate
from django.views.decorators.cache import never_cache
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.contrib import messages
from django.http import FileResponse, JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from .forms import ConfiguracionEmpresaForm, NodoBotForm, OpcionNodoForm, RegistroForm, PerfilForm
from .models import AgenteEmpresa, Empresa, SesionWhatsApp, CicloFacturacion, NodoBot, OpcionNodo, SesionUsuario, HistorialChat
from .conversaciones import procesar_mensaje_whatsapp
from .utils import solicitar_whatsapp, enviar_mensaje_whatsapp
from .cuentas import empresa_actual, empresas_usuario, solo_propietario
from .flujos import validar_flujo, resolver_turno
from .entregas import entregar_mensaje


registro_errores = logging.getLogger(__name__)

class IngresarView(LoginView):
    template_name = 'registration/login.html'

    def form_valid(self, form):
        respuesta = super().form_valid(form)
        self.request.session.set_expiry(1209600 if self.request.POST.get('recordarme') == '1' else 0)
        return respuesta


def registro(request):
    # al registrarse creo su empresa y lo mando a su panel
    formulario = RegistroForm(request.POST if request.method == 'POST' else None)
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
    empresa = empresa_actual(request, crear=False)
    sesion = SesionWhatsApp.objects.filter(empresa=empresa).first() if empresa else None
    hoy = timezone.localtime()
    ciclo = CicloFacturacion.objects.filter(empresa=empresa, mes=hoy.month, anio=hoy.year).first() if empresa else None
    return render(request, 'core/dashboard.html', {
        'sesion': sesion,
        'mensajes_ia': ciclo.conteo_mensajes_ia if ciclo else 0,
        'empresa': empresa,
        'mensajes_hoy': HistorialChat.objects.filter(sesion_usuario__empresa=empresa, fecha__date=timezone.localdate()).count() if empresa else 0,
        'total_conversaciones': SesionUsuario.objects.filter(empresa=empresa).count() if empresa else 0,
    })


def obtener_empresa(request):
    return empresa_actual(request)


@login_required
@require_GET
@never_cache
def estado_whatsapp(request):
    sesion = SesionWhatsApp.objects.filter(empresa=obtener_empresa(request)).first()
    if not sesion:
        return JsonResponse({'estado': 'desconectado', 'numero_telefono': '', 'codigo_qr': '', 'codigo_manual': ''})
    return JsonResponse({
        'estado': sesion.estado,
        'numero_telefono': sesion.numero_telefono,
        'codigo_qr': sesion.codigo_qr,
        'codigo_manual': sesion.codigo_manual,
    })

@login_required
@require_POST
@solo_propietario
def conectar_whatsapp(request):
    # creo una sesion propia antes de pedirle el qr a node
    telefono = request.POST.get('telefono', '').strip().lstrip('+')
    if telefono and not re.fullmatch(r'[0-9]{7,15}', telefono):
        return JsonResponse({'error': 'Escribe el número con código de país, solo dígitos.'}, status=400)
    empresa = obtener_empresa(request)
    sesion, _ = SesionWhatsApp.objects.get_or_create(empresa=empresa)
    if sesion.estado == 'conectado':
        return JsonResponse({'estado': sesion.estado, 'numero_telefono': sesion.numero_telefono, 'codigo_qr': '', 'codigo_manual': ''})

    if sesion.estado not in ['autenticando', 'esperando_qr', 'esperando_codigo']:
        sesion.estado = 'autenticando'
        sesion.codigo_qr = ''
        sesion.codigo_manual = ''
        sesion.save(update_fields=['estado', 'codigo_qr', 'codigo_manual'])
    try:
        solicitar_whatsapp('/api/sesiones/iniciar/', {'identificador': str(sesion.identificador), 'telefono': telefono})
    except Exception:
        registro_errores.exception('No se pudo comunicar con el servicio de WhatsApp')
        sesion.estado = 'error'
        sesion.save(update_fields=['estado'])
        return JsonResponse({'estado': 'error', 'error': 'No se pudo iniciar el servicio de WhatsApp'}, status=503)
    sesion.refresh_from_db()
    return JsonResponse({'estado': sesion.estado, 'codigo_qr': sesion.codigo_qr, 'codigo_manual': sesion.codigo_manual, 'numero_telefono': sesion.numero_telefono})

@login_required
@require_POST
@solo_propietario
def desconectar_whatsapp(request):
    sesion = SesionWhatsApp.objects.filter(empresa=obtener_empresa(request)).first()
    if not sesion:
        return JsonResponse({'estado': 'desconectado'})
    try:
        solicitar_whatsapp(f'/api/sesiones/{sesion.identificador}/desconectar/')
    except Exception:
        registro_errores.exception('No se pudo comunicar con el servicio de WhatsApp')
        sesion.estado = 'error'
        sesion.save(update_fields=['estado'])
        return JsonResponse({'estado': 'error', 'error': 'No se pudo desconectar el servicio de WhatsApp'}, status=503)
    sesion.estado = 'desconectado'
    sesion.codigo_qr = ''
    sesion.codigo_manual = ''
    sesion.numero_telefono = ''
    sesion.fecha_conexion = None
    sesion.ultima_actividad = timezone.now()
    sesion.save(update_fields=['estado', 'codigo_qr', 'codigo_manual', 'numero_telefono', 'fecha_conexion', 'ultima_actividad'])
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
        if not isinstance(datos, dict):
            return JsonResponse({'error': 'Evento no válido'}, status=400)
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
                registro_errores.exception('Error al procesar mensaje entrante de WhatsApp')
                return JsonResponse({'error': 'No se pudo procesar el mensaje'}, status=503)
            sesion.refresh_from_db()
            sesion.ultima_actividad = timezone.now()
            sesion.save(update_fields=['ultima_actividad'])
            return JsonResponse({'estado': 'recibido'})

        estado = datos.get('estado')
        if estado not in dict(SesionWhatsApp.ESTADOS):
            return JsonResponse({'error': 'Estado no válido'}, status=400)
        codigo = datos.get('codigo_qr', '')
        manual = datos.get('codigo_manual', '')
        if not isinstance(codigo, str) or not isinstance(manual, str):
            return JsonResponse({'error': 'Código no válido'}, status=400)
        if estado == 'esperando_qr' and not codigo.startswith('data:image/png;base64,'):
            return JsonResponse({'error': 'QR no válido'}, status=400)
        if estado == 'esperando_codigo' and not re.fullmatch(r'[A-Z0-9]{8}', manual):
            return JsonResponse({'error': 'Código manual no válido'}, status=400)
        sesion.estado = estado
        sesion.codigo_manual = manual if estado == 'esperando_codigo' else ''
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
        estado__in=['conectado', 'esperando_qr', 'autenticando', 'esperando_codigo']
    ).values_list('identificador', flat=True)
    return JsonResponse({'identificadores': [str(identificador) for identificador in sesiones]})


@login_required
@solo_propietario
def configuracion_bot(request):
    # el editor siempre trabaja con los pasos de esta empresa
    empresa = obtener_empresa(request)
    formulario = ConfiguracionEmpresaForm(request.POST if request.method == 'POST' else None, instance=empresa)
    if request.method == 'POST' and formulario.is_valid():
        formulario.save()
        messages.success(request, 'Se guardó la configuración.')
        return redirect('configuracion_bot')

    return mostrar_configuracion(request, empresa, formulario)


def mostrar_configuracion(request, empresa, formulario=None, error=None):
    formulario = formulario if formulario is not None else ConfiguracionEmpresaForm(instance=empresa)
    error = error or {}
    nodos = NodoBot.objects.filter(empresa=empresa).prefetch_related('opciones_salida__nodo_siguiente').order_by('id')
    pasos = []
    for nodo in nodos:
        opciones = []
        for opcion in nodo.opciones_salida.all():
            opciones.append({
                'objeto': opcion,
                'formulario': error['formulario'] if error.get('opcion_id') == opcion.pk else OpcionNodoForm(instance=opcion, empresa=empresa, auto_id=f'opcion_{opcion.pk}_%s'),
            })
        pasos.append({
            'objeto': nodo,
            'abierto': error.get('nodo_id') == nodo.pk,
            'formulario': error['formulario'] if error.get('tipo') == 'nodo' and error.get('nodo_id') == nodo.pk else NodoBotForm(instance=nodo, empresa=empresa, auto_id=f'nodo_{nodo.pk}_%s'),
            'formulario_opcion': error['formulario'] if error.get('tipo') == 'opcion' and error.get('nodo_id') == nodo.pk and not error.get('opcion_id') else OpcionNodoForm(empresa=empresa, auto_id=f'nueva_opcion_{nodo.pk}_%s'),
            'opciones': opciones,
        })
    return render(request, 'core/configuracion_bot.html', {
        'empresa': empresa,
        'formulario': formulario,
        'formulario_nodo': error['formulario'] if error.get('tipo') == 'nodo' and not error.get('nodo_id') else NodoBotForm(empresa=empresa, auto_id='nuevo_nodo_%s'),
        'avisos_flujo': validar_flujo(empresa),
        'saldo_ia': max(0, empresa.limite_respuestas_ia - empresa.respuestas_ia_utilizadas),
        'pasos': pasos,
    })


@login_required
@require_POST
@solo_propietario
def guardar_nodo(request, nodo_id=None):
    empresa = obtener_empresa(request)
    instancia = get_object_or_404(NodoBot, pk=nodo_id, empresa=empresa) if nodo_id else None
    formulario = NodoBotForm(request.POST, instance=instancia, empresa=empresa)
    if formulario.is_valid():
        formulario.save()
        messages.success(request, 'Se guardó el paso del bot.')
    else:
        return mostrar_configuracion(request, empresa, error={'tipo':'nodo', 'nodo_id':nodo_id, 'formulario':formulario})
    return redirect('configuracion_bot')


@login_required
@require_POST
@solo_propietario
def eliminar_nodo(request, nodo_id):
    empresa = obtener_empresa(request)
    get_object_or_404(NodoBot, pk=nodo_id, empresa=empresa).delete()
    return redirect('configuracion_bot')


@login_required
@require_POST
@solo_propietario
def guardar_opcion(request, nodo_id, opcion_id=None):
    # el paso padre y el destino quedan dentro del mismo cliente
    empresa = obtener_empresa(request)
    nodo = get_object_or_404(NodoBot, pk=nodo_id, empresa=empresa)
    instancia = get_object_or_404(OpcionNodo, pk=opcion_id, nodo_padre=nodo) if opcion_id else None
    formulario = OpcionNodoForm(request.POST, request.FILES, instance=instancia, empresa=empresa)
    # asignar el paso padre antes de validar la conexion
    formulario.instance.nodo_padre = nodo
    if formulario.is_valid():
        opcion = formulario.save(commit=False)
        opcion.save()
        messages.success(request, 'Se guardó la opción.')
    else:
        return mostrar_configuracion(request, empresa, error={'tipo':'opcion', 'nodo_id':nodo_id, 'opcion_id':opcion_id, 'formulario':formulario})
    return redirect('configuracion_bot')


@login_required
@require_POST
@solo_propietario
def eliminar_opcion(request, nodo_id, opcion_id):
    nodo = get_object_or_404(NodoBot, pk=nodo_id, empresa=obtener_empresa(request))
    get_object_or_404(OpcionNodo, pk=opcion_id, nodo_padre=nodo).delete()
    return redirect('configuracion_bot')


@login_required
@never_cache
def atencion_humana(request):
    # muestro los chats que esperan a una persona y los que ya cerraron
    empresa = empresa_actual(request, crear=False)
    conversaciones = SesionUsuario.objects.none()
    if empresa:
        conversaciones = SesionUsuario.objects.filter(
            empresa=empresa,
            estado__in=['humano', 'cerrada'],
        ).annotate(ultimo_mensaje=Subquery(
            HistorialChat.objects.filter(sesion_usuario_id=OuterRef('pk')).order_by('-fecha', '-pk').values('contenido')[:1]
        )).order_by('-ultima_actividad')
    seleccion = request.GET.get('c', '')
    if seleccion and not seleccion.isdecimal():
        return JsonResponse({'error': 'Conversación no válida'}, status=400)
    conversacion = get_object_or_404(conversaciones, pk=seleccion) if seleccion else None
    if conversacion and request.GET.get('formato') == 'json':
        historial = list(conversacion.historialchat_set.order_by('-fecha', '-pk')[:100])
        return JsonResponse({'estado': conversacion.estado, 'asignado_a': conversacion.asignado_a.username if conversacion.asignado_a else '', 'puede_responder': conversacion.asignado_a_id in [None, request.user.pk], 'mensajes': [
            {'id': mensaje.pk, 'rol': mensaje.rol, 'contenido': mensaje.contenido, 'fecha': mensaje.fecha.isoformat(), 'entrega': mensaje.get_estado_entrega_display()}
            for mensaje in reversed(historial)
        ]})
    return render(request, 'core/atencion_humana.html', {
        'conversaciones': conversaciones,
        'conversacion': conversacion,
        'id_envio': str(uuid.uuid4()),
        'historial': conversacion.historialchat_set.order_by('fecha', 'pk') if conversacion else [],
    })


@login_required
@require_POST
def responder_agente(request, sesion_id):
    texto = request.POST.get('texto', '').strip()
    if not texto or len(texto) > 10000:
        return JsonResponse({'error': 'Escribe entre 1 y 10000 caracteres.'}, status=400)
    try:
        id_envio = uuid.UUID(request.POST.get('id_envio', ''))
    except ValueError:
        return JsonResponse({'error': 'Recarga el formulario para obtener un identificador de envío.'}, status=400)
    with transaction.atomic():
        chat = get_object_or_404(SesionUsuario.objects.select_for_update(), pk=sesion_id, empresa=obtener_empresa(request), estado='humano')
        if chat.asignado_a_id and chat.asignado_a_id != request.user.pk:
            return JsonResponse({'error': 'Otro agente está atendiendo esta conversación.'}, status=409)
        chat.asignado_a = request.user
        chat.save(update_fields=['asignado_a', 'ultima_actividad'])
        mensaje, creado = HistorialChat.objects.get_or_create(id_envio=id_envio, defaults={
            'sesion_usuario':chat, 'rol':'agent', 'contenido':texto, 'estado_entrega':'generado',
        })
        if mensaje.sesion_usuario_id != chat.pk or mensaje.contenido != texto or mensaje.rol != 'agent':
            return JsonResponse({'error':'El identificador corresponde a otro mensaje.'}, status=409)
    estado = entregar_mensaje(mensaje.pk, enviar=enviar_mensaje_whatsapp)
    return JsonResponse({'estado':estado, 'mensaje_id':mensaje.pk})


@login_required
@require_POST
def tomar_conversacion(request, sesion_id):
    empresa = obtener_empresa(request)
    with transaction.atomic():
        chat = get_object_or_404(SesionUsuario.objects.select_for_update(), pk=sesion_id, empresa=empresa, estado='humano')
        if request.POST.get('liberar') == '1':
            if chat.asignado_a_id not in [None, request.user.pk] and empresa.propietario_id != request.user.pk:
                return JsonResponse({'error':'Solo el agente asignado o el propietario puede liberarla.'}, status=403)
            chat.asignado_a = None
        elif chat.asignado_a_id not in [None, request.user.pk]:
            return JsonResponse({'error':'Otro agente ya tomó esta conversación.'}, status=409)
        else:
            chat.asignado_a = request.user
        chat.save(update_fields=['asignado_a'])
    return JsonResponse({'estado':'actualizado'})


@login_required
@require_POST
def cambiar_estado_conversacion(request, sesion_id, estado):
    if estado not in ['cerrada', 'bot']:
        return JsonResponse({'error':'Estado no válido'}, status=400)
    empresa = obtener_empresa(request)
    pendiente = None
    with transaction.atomic():
        chat = get_object_or_404(SesionUsuario.objects.select_for_update(), pk=sesion_id, empresa=empresa)
        if chat.asignado_a_id not in [None, request.user.pk] and empresa.propietario_id != request.user.pk:
            return JsonResponse({'error':'La conversación está asignada a otro agente.'}, status=409)
        if estado == 'cerrada' and chat.estado != 'cerrada' and empresa.despedida:
            pendiente = HistorialChat.objects.create(sesion_usuario=chat, rol='agent', contenido=empresa.despedida, estado_entrega='generado')
        chat.estado, chat.activo = estado, estado != 'cerrada'
        chat.asignado_a = None
        if estado == 'bot':
            chat.nodo_actual = None
        chat.save()
    entrega = entregar_mensaje(pendiente.pk, enviar=enviar_mensaje_whatsapp) if pendiente else None
    return JsonResponse({'estado':estado, 'entrega':entrega})


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




@login_required
def metricas(request):
    empresa = obtener_empresa(request)
    desde = timezone.localdate() - timedelta(days=29)
    historial = HistorialChat.objects.filter(sesion_usuario__empresa=empresa)
    dias = historial.filter(fecha__date__gte=desde).annotate(dia=TruncDate('fecha')).values('dia').annotate(total=Count('id')).order_by('-dia')
    return render(request, 'core/metricas.html', {
        'dias': dias, 'empresa': empresa,
        'mensajes_hoy': historial.filter(fecha__date=timezone.localdate()).count(),
        'conversaciones': empresa.sesiones_chat.count(),
        'pendientes': empresa.sesiones_chat.filter(estado='humano').count(),
        'sesion': SesionWhatsApp.objects.filter(empresa=empresa).first(),
    })


@login_required
def perfil(request):
    formulario = PerfilForm(request.POST if request.method == 'POST' else None, instance=request.user)
    if request.method == 'POST' and formulario.is_valid():
        formulario.save()
        messages.success(request, 'Se guardó tu perfil.')
        return redirect('perfil')
    return render(request, 'core/perfil.html', {'formulario': formulario})


@login_required
@require_GET
def archivo_opcion(request, opcion_id):
    opcion = get_object_or_404(OpcionNodo, pk=opcion_id, nodo_padre__empresa=obtener_empresa(request))
    if not opcion.archivo_pdf:
        return JsonResponse({'error': 'Esta opción no tiene PDF'}, status=404)
    return FileResponse(opcion.archivo_pdf.open('rb'), as_attachment=True, filename=opcion.archivo_pdf.name.rsplit('/', 1)[-1])


@login_required
@require_GET
@never_cache
def diagnostico_whatsapp(request):
    sesion = SesionWhatsApp.objects.filter(empresa=obtener_empresa(request)).first()
    if not sesion:
        return JsonResponse({'servicio':'sin sesión', 'estado':'desconectado', 'detalle':'Genera un código para iniciar la conexión.', 'ultimo_evento':None})
    datos = {'estado_guardado':sesion.estado, 'ultimo_evento':sesion.ultima_actividad.isoformat() if sesion.ultima_actividad else None}
    try:
        respuesta = solicitar_whatsapp(f'/api/sesiones/{sesion.identificador}/diagnostico/', metodo='get', espera=4)
        datos.update(respuesta)
        datos['detalle'] = 'El proceso tiene la sesión conectada.' if respuesta.get('estado') == 'conectado' else 'La sesión necesita completar la vinculación o reconectarse.'
    except Exception:
        datos.update(servicio='no disponible', estado='desconocido', detalle='Django no pudo consultar node. Revisa el servicio, su URL y el secreto compartido.')
    return JsonResponse(datos)


@login_required
def simulador(request):
    empresa = obtener_empresa(request)
    clave = f'simulador_{empresa.pk}'
    estado = request.session.get(clave, {'nodo':None, 'estado':'bot', 'nueva':True, 'historial':[]})
    error = ''
    if request.method == 'POST':
        if request.POST.get('reiniciar'):
            request.session.pop(clave, None)
            return redirect('simulador')
        texto = request.POST.get('texto', '').strip()
        if not 1 <= len(texto) <= 1000:
            error = 'Escribe entre 1 y 1000 caracteres.'
        else:
            nodo = NodoBot.objects.filter(empresa=empresa, pk=estado.get('nodo')).first()
            resultado = resolver_turno(empresa, nodo, estado['estado'], estado['nueva'], texto, timezone.now())
            salidas = [salida['texto'] + ('\n[PDF adjunto]' if salida['opcion'] and salida['opcion'].archivo_pdf else '') for salida in resultado['salidas']]
            if resultado['ia']:
                if empresa.respuestas_ia_utilizadas >= empresa.limite_respuestas_ia:
                    salidas.append(empresa.mensaje_limite_ia)
                    if empresa.accion_limite_ia == 'humano':
                        resultado['estado'] = 'humano'
                else:
                    salidas.append(f'[Aquí respondería la IA en {empresa.get_idioma_display()}, con tono {empresa.get_tono_display().lower()}. No se consume saldo.]')
            historial = estado['historial'] + [{'entrada':texto, 'salidas':salidas, 'motivo':resultado['motivo'], 'estado':resultado['estado']}]
            estado = {'nodo':resultado['nodo'].pk if resultado['nodo'] else None, 'estado':resultado['estado'], 'nueva':False, 'historial':historial[-20:]}
            request.session[clave] = estado
    return render(request, 'core/simulador.html', {'simulacion':estado, 'error':error, 'avisos_flujo':validar_flujo(empresa)})


@login_required
@require_POST
@solo_propietario
def duplicar_nodo(request, nodo_id):
    empresa = obtener_empresa(request)
    with transaction.atomic():
        original = get_object_or_404(NodoBot, pk=nodo_id, empresa=empresa)
        copia = NodoBot.objects.create(empresa=empresa, nombre=(original.nombre[:248] + ' (copia)'), tipo_nodo=original.tipo_nodo, contenido_mensaje=original.contenido_mensaje)
        for opcion in original.opciones_salida.all():
            OpcionNodo.objects.create(nodo_padre=copia, nodo_siguiente=copia if opcion.nodo_siguiente_id == original.pk else opcion.nodo_siguiente,
                                     entrada_esperada=opcion.entrada_esperada, etiqueta=opcion.etiqueta, archivo_pdf=opcion.archivo_pdf.name)
    messages.success(request, 'Se duplicó el paso con sus opciones. El inicio del flujo se conserva.')
    return redirect('configuracion_bot')


@login_required
@require_GET
@solo_propietario
def descargar_flujo(request):
    from .intercambio import exportar_flujo
    try:
        respuesta = HttpResponse(json.dumps(exportar_flujo(obtener_empresa(request)), ensure_ascii=False), content_type='application/json')
        respuesta['Content-Disposition'] = 'attachment; filename="flujo-boti.json"'
        return respuesta
    except (ValidationError, OSError) as error:
        messages.error(request, str(error))
        return redirect('configuracion_bot')


@login_required
@require_POST
@solo_propietario
def cargar_flujo(request):
    from .intercambio import importar_flujo
    archivo = request.FILES.get('flujo')
    if not archivo:
        messages.error(request, 'Selecciona un archivo de flujo.')
    else:
        try:
            cantidad = importar_flujo(obtener_empresa(request), archivo)
            messages.success(request, f'Se agregaron {cantidad} pasos. Los pasos existentes se conservaron.')
        except (ValidationError, OSError) as error:
            messages.error(request, str(error))
    return redirect('configuracion_bot')


@login_required
def entregas(request):
    empresa = obtener_empresa(request)
    pendientes = HistorialChat.objects.filter(sesion_usuario__empresa=empresa, estado_entrega__in=['generado','fallido','incierto','enviando']).select_related('sesion_usuario').order_by('-fecha')
    return render(request, 'core/entregas.html', {'pendientes':Paginator(pendientes, 30).get_page(request.GET.get('pagina'))})


@login_required
@require_POST
def reintentar_entrega(request, mensaje_id):
    mensaje = get_object_or_404(HistorialChat, pk=mensaje_id, sesion_usuario__empresa=obtener_empresa(request), estado_entrega__in=['generado','fallido','incierto','enviando'])
    chat = mensaje.sesion_usuario
    if chat.asignado_a_id not in [None, request.user.pk] and chat.empresa.propietario_id != request.user.pk:
        return HttpResponse('Esta conversación está asignada a otra persona.', status=403)
    if request.POST.get('confirmado') == '1':
        HistorialChat.objects.filter(pk=mensaje.pk).update(estado_entrega='enviado', error_entrega='Confirmado manualmente desde el panel.')
        messages.success(request, 'Se registró tu confirmación de entrega.')
    else:
        estado = entregar_mensaje(mensaje.pk)
        if estado == 'enviado':
            messages.success(request, 'Entrega confirmada. Se reutilizó el mismo identificador.')
        else:
            messages.warning(request, 'La entrega sigue pendiente. Si está sin confirmación, verifica el chat de WhatsApp antes de marcarla como enviada.')
    return redirect('entregas')


@login_required
@require_POST
def elegir_empresa(request):
    elegida = get_object_or_404(empresas_usuario(request.user), pk=request.POST.get('empresa') if request.POST.get('empresa', '').isdigit() else 0)
    request.session['empresa_activa'] = elegida.pk
    return redirect('dashboard')


@login_required
def equipo(request):
    empresa = obtener_empresa(request)
    if empresa.propietario_id != request.user.pk:
        return HttpResponse('Solo el propietario puede administrar el equipo.', status=403)
    if request.method == 'POST':
        if request.POST.get('quitar'):
            miembro = get_object_or_404(AgenteEmpresa, pk=request.POST.get('quitar'), empresa=empresa)
            with transaction.atomic():
                SesionUsuario.objects.filter(empresa=empresa, asignado_a=miembro.usuario).update(asignado_a=None)
                miembro.delete()
            messages.success(request, 'Se retiró el acceso del agente y se liberaron sus chats.')
        else:
            usuario = User.objects.filter(username=request.POST.get('usuario', '').strip(), is_active=True).first()
            if not usuario or usuario.pk == request.user.pk:
                messages.error(request, 'Escribe el usuario de otra cuenta registrada y activa.')
            else:
                AgenteEmpresa.objects.get_or_create(empresa=empresa, usuario=usuario)
                messages.success(request, 'El agente puede elegir esta empresa desde su menú de usuario.')
        return redirect('equipo')
    return render(request, 'core/equipo.html', {'miembros':empresa.agentes.select_related('usuario')})
