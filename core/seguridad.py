import secrets
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac, constant_time_compare
from .models import CodigoCorreo, LimiteAcceso
from .correos import enviar_correo


class ErrorCodigo(Exception):
    pass


def huella(valor):
    return salted_hmac('boti-correo', str(valor), algorithm='sha256').hexdigest()


@transaction.atomic
def permitir(clave, maximo, minutos=15):
    ahora = timezone.now()
    limite, _ = LimiteAcceso.objects.get_or_create(clave=huella(clave), defaults={'inicio': ahora})
    limite = LimiteAcceso.objects.select_for_update().get(pk=limite.pk)
    if limite.inicio + timedelta(minutes=minutos) <= ahora:
        limite.inicio, limite.intentos = ahora, 0
    limite.intentos += 1
    limite.save()
    return limite.intentos <= maximo


def limitar_solicitud(request, identidad=''):
    # uso la direccion del servidor, nunca cabeceras de proxy sin verificar
    ip = request.META.get('REMOTE_ADDR', '')
    permitido = permitir('acceso-ip:' + ip, 30)
    identidad_permitida = permitir('acceso-identidad:' + identidad.lower(), 10) if identidad else True
    return permitido and identidad_permitida


def iniciar_codigo(request, correo, proposito, usuario=None, datos=None):
    correo = correo.strip().lower()
    if not correo:
        raise ErrorCodigo('Tu cuenta necesita un correo válido. Contacta a soporte para recuperarla.')
    if not permitir('envio:' + correo, 5) or not permitir('pausa:' + correo, 1, 1):
        raise ErrorCodigo('Espera antes de solicitar otro código. Revisa también la carpeta de spam.')
    vinculo = request.session.setdefault('vinculo_codigo', secrets.token_urlsafe(32))
    codigo = f'{secrets.randbelow(1000000):06d}'
    registro = CodigoCorreo.objects.create(correo=correo, proposito=proposito, usuario=usuario,
        huella=huella(codigo), vinculo=huella(vinculo), datos=datos or {}, vence=timezone.now() + timedelta(minutes=10))
    CodigoCorreo.objects.filter(vinculo=registro.vinculo, usado=False).exclude(pk=registro.pk).update(usado=True, datos={})
    titulos = {'registro': 'Confirma tu cuenta', 'ingreso': 'Confirma tu acceso', 'correo_actual': 'Autoriza el cambio de correo', 'correo_nuevo': 'Verifica tu nuevo correo', 'clave': 'Confirma el cambio de contraseña', 'recuperar': 'Recupera tu contraseña'}
    try:
        enviar_correo(correo, titulos[proposito], 'Escribe este código en la ventana de Boti donde iniciaste la operación.', codigo)
    except Exception as error:
        registro.usado, registro.datos = True, {}
        registro.save(update_fields=['usado', 'datos'])
        raise ErrorCodigo('No pudimos enviar el código. Intenta más tarde o contacta a soporte.') from error
    request.session['codigo_pendiente'] = str(registro.identificador)
    return registro


def comprobar_codigo(registro, request, codigo):
    if registro.usado or registro.vence <= timezone.now() or registro.intentos >= 5:
        return False
    if not constant_time_compare(registro.vinculo, huella(request.session.get('vinculo_codigo', ''))):
        return False
    registro.intentos += 1
    registro.save(update_fields=['intentos'])
    return constant_time_compare(registro.huella, huella(codigo.strip()))
