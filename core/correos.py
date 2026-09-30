from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def enviar_correo(destino, titulo, mensaje, codigo='', detalle=''):
    if settings.EMAIL_BACKEND == 'django.core.mail.backends.smtp.EmailBackend' and not settings.EMAIL_HOST:
        raise ValueError('Falta configurar SMTP_HOST')
    datos = {'titulo': titulo, 'mensaje': mensaje, 'codigo': codigo, 'detalle': detalle,
             'url': settings.BOTI_URL_PUBLICA + '/api/planes/'}
    texto = render_to_string('correos/mensaje.txt', datos)
    correo = EmailMultiAlternatives(titulo + ' · Boti', texto, settings.DEFAULT_FROM_EMAIL, [destino])
    correo.attach_alternative(render_to_string('correos/mensaje.html', datos), 'text/html')
    if correo.send() != 1:
        raise RuntimeError('El servidor de correo no acepto el mensaje')
