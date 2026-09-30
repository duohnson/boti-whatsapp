from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password
from django.contrib.auth.decorators import login_required
from django.db import transaction, IntegrityError
from django.shortcuts import render, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from .forms import RegistroForm, CambioCorreoForm
from .models import Empresa, PerfilUsuario, CodigoCorreo
from .seguridad import iniciar_codigo, comprobar_codigo, limitar_solicitud, ErrorCodigo, huella


@never_cache
def ingresar(request):
    formulario = AuthenticationForm(request, data=request.POST if request.method == 'POST' else None)
    formulario.error_messages = {**formulario.error_messages, 'invalid_login': 'Usuario o contraseña incorrectos. Intenta de nuevo.'}
    siguiente = request.POST.get('next', request.GET.get('next', ''))
    if not url_has_allowed_host_and_scheme(siguiente, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        siguiente = ''
    if request.method == 'POST':
        if not limitar_solicitud(request, request.POST.get('username', '')):
            formulario.add_error(None, 'Demasiados intentos. Espera 15 minutos antes de continuar.')
        elif formulario.is_valid():
            usuario = formulario.get_user()
            try:
                iniciar_codigo(request, usuario.email, 'ingreso', usuario, {'clave_actual': usuario.password, 'correo_actual': usuario.email, 'recordarme': request.POST.get('recordarme') == '1', 'siguiente': siguiente})
                return redirect('verificar_codigo')
            except ErrorCodigo as error:
                formulario.add_error(None, str(error))
    return render(request, 'registration/login.html', {'form': formulario, 'next': siguiente})


@never_cache
def registro(request):
    formulario = RegistroForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if not limitar_solicitud(request, request.POST.get('email', '')) or request.POST.get('sitio_web'):
            formulario.add_error(None, 'No se pudo iniciar el registro. Espera antes de intentar nuevamente.')
        elif formulario.is_valid():
            datos = formulario.cleaned_data
            try:
                iniciar_codigo(request, datos['email'], 'registro', datos={'username': datos['username'], 'first_name': datos['first_name'], 'password': make_password(datos['password1'])})
                return redirect('verificar_codigo')
            except ErrorCodigo as error:
                formulario.add_error(None, str(error))
    return render(request, 'registration/registro.html', {'formulario': formulario})


@login_required
@never_cache
def cambiar_correo(request):
    formulario = CambioCorreoForm(request.user, request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and not limitar_solicitud(request, request.user.username):
        formulario.add_error(None, 'Demasiados intentos. Espera antes de continuar.')
    elif request.method == 'POST' and formulario.is_valid():
        try:
            iniciar_codigo(request, request.user.email, 'correo_actual', request.user,
                {'nuevo_correo': formulario.cleaned_data['correo'], 'correo_actual': request.user.email, 'clave_actual': request.user.password})
            return redirect('verificar_codigo')
        except ErrorCodigo as error:
            formulario.add_error(None, str(error))
    return render(request, 'core/seguridad_cuenta.html', {'formulario': formulario, 'titulo': 'Cambiar correo', 'detalle': 'Primero confirmaremos tu correo actual y después el nuevo. El cambio solo se guarda al verificar ambos.'})


@login_required
@never_cache
def cambiar_clave(request):
    formulario = PasswordChangeForm(request.user, request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and not limitar_solicitud(request, request.user.username):
        formulario.add_error(None, 'Demasiados intentos. Espera antes de continuar.')
    elif request.method == 'POST' and formulario.is_valid():
        try:
            iniciar_codigo(request, request.user.email, 'clave', request.user,
                {'nueva_clave': make_password(formulario.cleaned_data['new_password1']), 'clave_actual': request.user.password, 'correo_actual': request.user.email})
            return redirect('verificar_codigo')
        except ErrorCodigo as error:
            formulario.add_error(None, str(error))
    return render(request, 'core/seguridad_cuenta.html', {'formulario': formulario, 'titulo': 'Cambiar contraseña', 'detalle': 'Confirma tu contraseña actual y el código que enviaremos a tu correo. Al terminar se cerrarán las sesiones anteriores.'})


def obtener_pendiente(request):
    identificador = request.session.get('codigo_pendiente')
    return CodigoCorreo.objects.filter(identificador=identificador).first() if identificador else None


@never_cache
def verificar(request):
    pendiente = obtener_pendiente(request)
    if not pendiente:
        return redirect('ingresar')
    error = ''
    if request.method == 'POST':
        if not limitar_solicitud(request):
            error = 'Demasiados intentos. Espera 15 minutos.'
        else:
            with transaction.atomic():
                pendiente = CodigoCorreo.objects.select_for_update().get(pk=pendiente.pk)
                if not comprobar_codigo(pendiente, request, request.POST.get('codigo', '')):
                    error = 'Código incorrecto, vencido o agotado. Puedes solicitar otro.'
                else:
                    try:
                        with transaction.atomic():
                            destino = completar(request, pendiente)
                        return redirect(destino)
                    except (ErrorCodigo, IntegrityError):
                        error = 'No se pudo completar la operación. Iníciala nuevamente o contacta a soporte.'
    partes = pendiente.correo.split('@')
    correo_oculto = partes[0][:1] + '***@' + partes[-1]
    return render(request, 'registration/verificar.html', {'error': error, 'correo_oculto': correo_oculto, 'proposito': pendiente.proposito})


def completar(request, pendiente):
    datos = pendiente.datos
    usuario = None
    if pendiente.usuario_id:
        usuario = User.objects.select_for_update().get(pk=pendiente.usuario_id)
        if not usuario.is_active or usuario.password != datos.get('clave_actual') or usuario.email != datos.get('correo_actual'):
            raise ErrorCodigo('La cuenta cambió durante la solicitud')
        if pendiente.proposito not in ['ingreso'] and (not request.user.is_authenticated or request.user.pk != usuario.pk):
            raise ErrorCodigo('La sesión no corresponde a esta cuenta')
    if pendiente.proposito == 'registro':
        if User.objects.filter(email__iexact=pendiente.correo).exists():
            raise ErrorCodigo('El correo ya existe')
        usuario = User.objects.create(username=datos['username'], first_name=datos['first_name'], email=pendiente.correo, password=datos['password'])
        PerfilUsuario.objects.create(usuario=usuario, correo_verificado=pendiente.correo)
        Empresa.objects.create(propietario=usuario)
    elif pendiente.proposito == 'correo_actual':
        iniciar_codigo(request, datos['nuevo_correo'], 'correo_nuevo', usuario, datos)
        pendiente.usado, pendiente.datos = True, {}
        pendiente.save(update_fields=['usado', 'datos'])
        return 'verificar_codigo'
    elif pendiente.proposito == 'correo_nuevo':
        if User.objects.filter(email__iexact=pendiente.correo).exclude(pk=usuario.pk).exists():
            raise ErrorCodigo('El correo ya existe')
        usuario.email = pendiente.correo
        usuario.save(update_fields=['email'])
    elif pendiente.proposito == 'clave':
        usuario.password = datos['nueva_clave']
        usuario.save(update_fields=['password'])
    perfil, _ = PerfilUsuario.objects.get_or_create(usuario=usuario)
    perfil.correo_verificado = usuario.email.lower()
    perfil.save(update_fields=['correo_verificado'])
    pendiente.usado, pendiente.datos = True, {}
    pendiente.save(update_fields=['usado', 'datos'])
    request.session.pop('codigo_pendiente', None)
    if pendiente.proposito in ['registro', 'ingreso']:
        login(request, usuario, backend='django.contrib.auth.backends.ModelBackend')
        request.session.set_expiry(1209600 if datos.get('recordarme') else 0)
        return datos.get('siguiente') or 'dashboard'
    if pendiente.proposito == 'clave':
        CodigoCorreo.objects.filter(usuario=usuario, usado=False).update(usado=True, datos={})
        logout(request)
        return 'ingresar'
    messages.success(request, 'Tu correo quedó verificado y actualizado.')
    return 'perfil'


@require_POST
@never_cache
def reenviar(request):
    pendiente = obtener_pendiente(request)
    if not pendiente or pendiente.usado or pendiente.vinculo != huella(request.session.get('vinculo_codigo', '')):
        return redirect('ingresar')
    try:
        if not limitar_solicitud(request):
            raise ErrorCodigo('Espera antes de solicitar otro código.')
        iniciar_codigo(request, pendiente.correo, pendiente.proposito, pendiente.usuario, pendiente.datos)
        messages.success(request, 'Enviamos un código nuevo. El anterior dejó de funcionar.')
    except ErrorCodigo as error:
        messages.error(request, str(error))
    return redirect('verificar_codigo')
