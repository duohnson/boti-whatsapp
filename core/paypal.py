from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode, urlparse
import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from .models import Empresa, PagoPlan, SuscripcionPlan
from .planes import PLANES, PERIODOS, activar_pago


class ErrorPaypal(Exception):
    pass


def solicitar(ruta, datos=None, metodo='GET', identificador=None):
    if not settings.PAYPAL_CLIENT_ID or not settings.PAYPAL_CLIENT_SECRET:
        raise ErrorPaypal('PayPal todavía no está configurado.')
    if settings.PAYPAL_ENTORNO not in ['sandbox', 'live']:
        raise ErrorPaypal('El entorno de PayPal no es válido.')
    base = 'https://api-m.paypal.com' if settings.PAYPAL_ENTORNO == 'live' else 'https://api-m.sandbox.paypal.com'
    try:
        token = requests.post(base + '/v1/oauth2/token', auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET), data={'grant_type': 'client_credentials'}, timeout=20)
        token.raise_for_status()
        cabeceras = {'Authorization': 'Bearer ' + token.json()['access_token'], 'Content-Type': 'application/json'}
        if identificador:
            cabeceras['PayPal-Request-Id'] = str(identificador)
        respuesta = requests.request(metodo, base + ruta, headers=cabeceras, json=datos, timeout=25)
        respuesta.raise_for_status()
        return respuesta.json() if respuesta.content else {}
    except (requests.RequestException, ValueError, KeyError) as error:
        raise ErrorPaypal('No se pudo confirmar la operación con PayPal. Puedes consultar de nuevo sin repetir el pago.') from error


def frecuencia(periodo):
    datos = PERIODOS[periodo]
    return {'interval_unit': 'MONTH' if datos[3] else 'DAY', 'interval_count': datos[3] or datos[2]}


def validar_plan(identificador, plan, periodo):
    datos = solicitar('/v1/billing/plans/' + identificador)
    ciclos = datos.get('billing_cycles', [])
    esperado = Decimal(PLANES[plan]['precio'] * PERIODOS[periodo][1])
    if len(ciclos) != 1 or datos.get('status') != 'ACTIVE':
        raise ErrorPaypal('Revisa la configuración del plan en PayPal.')
    ciclo = ciclos[0]
    precio = ciclo.get('pricing_scheme', {}).get('fixed_price', {})
    preferencias = datos.get('payment_preferences', {})
    if (ciclo.get('tenure_type') != 'REGULAR' or ciclo.get('total_cycles') != 0
            or ciclo.get('frequency') != frecuencia(periodo) or precio.get('currency_code') != 'USD'
            or Decimal(precio.get('value', '-1')) != esperado
            or Decimal(preferencias.get('setup_fee', {}).get('value', '0')) != 0
            or Decimal(datos.get('taxes', {}).get('percentage', '0')) != 0):
        raise ErrorPaypal('El precio o periodo de PayPal no coincide con el mostrado en Boti.')


def crear_suscripcion(suscripcion):
    validar_plan(suscripcion.paypal_plan, suscripcion.plan, suscripcion.periodo)
    datos = solicitar('/v1/billing/subscriptions', {
        'plan_id': suscripcion.paypal_plan, 'custom_id': str(suscripcion.identificador),
        'application_context': {'brand_name': 'Boti', 'shipping_preference': 'NO_SHIPPING',
            'user_action': 'SUBSCRIBE_NOW', 'return_url': settings.BOTI_URL_PUBLICA + '/api/planes/retorno/',
            'cancel_url': settings.BOTI_URL_PUBLICA + '/api/planes/'}}, 'POST', suscripcion.identificador)
    aprobacion = next((enlace['href'] for enlace in datos.get('links', []) if enlace.get('rel') == 'approve'), '')
    url = urlparse(aprobacion)
    if url.scheme != 'https' or url.hostname not in ['www.paypal.com', 'www.sandbox.paypal.com'] or not datos.get('id'):
        raise ErrorPaypal('PayPal no devolvió un enlace de aprobación válido.')
    suscripcion.paypal_id = datos['id']
    suscripcion.aprobacion = aprobacion
    suscripcion.save(update_fields=['paypal_id', 'aprobacion'])
    return aprobacion


def consultar_suscripcion(suscripcion):
    datos = solicitar('/v1/billing/subscriptions/' + suscripcion.paypal_id)
    if datos.get('custom_id') != str(suscripcion.identificador) or datos.get('plan_id') != suscripcion.paypal_plan:
        raise ErrorPaypal('La suscripción no corresponde a este plan.')
    estados = {'ACTIVE': 'activo', 'SUSPENDED': 'suspendido', 'CANCELLED': 'cancelado', 'EXPIRED': 'terminado', 'APPROVAL_PENDING': 'pendiente', 'APPROVED': 'pendiente'}
    estado = estados.get(datos.get('status'))
    if not estado:
        raise ErrorPaypal('Estado de suscripción desconocido.')
    # no reactivo una cancelacion local por una respuesta atrasada
    SuscripcionPlan.objects.filter(pk=suscripcion.pk).exclude(estado__in=['cancelado', 'terminado']).update(estado=estado)
    return datos


@transaction.atomic
def registrar_cobro(suscripcion, identificador, importe, moneda, fecha):
    empresa = Empresa.objects.select_for_update().get(pk=suscripcion.empresa_id)
    if PagoPlan.objects.filter(captura_paypal=identificador).exists():
        return
    if moneda != 'USD' or Decimal(importe) != suscripcion.importe or not fecha or timezone.is_naive(fecha):
        raise ErrorPaypal('El cobro no coincide con la suscripción.')
    pago = PagoPlan.objects.create(empresa=empresa, captura_paypal=identificador,
        plan=suscripcion.plan, periodo=suscripcion.periodo, importe=suscripcion.importe, inicio=fecha)
    activar_pago(pago, empresa)


def sincronizar(suscripcion):
    consultar_suscripcion(suscripcion)
    ahora = timezone.now()
    desde = max(suscripcion.creado - timedelta(minutes=5), ahora - timedelta(days=179))
    consulta = urlencode({'start_time': desde.isoformat(), 'end_time': ahora.isoformat()})
    datos = solicitar(f'/v1/billing/subscriptions/{suscripcion.paypal_id}/transactions?{consulta}')
    for pago in sorted(datos.get('transactions', []), key=lambda pago: pago.get('time', '')):
        if pago.get('status') == 'COMPLETED':
            monto = pago.get('amount_with_breakdown', {}).get('gross_amount', {})
            registrar_cobro(suscripcion, pago['id'], monto.get('value', '-1'), monto.get('currency_code'), parse_datetime(pago.get('time', '')))


def verificar_evento(request, evento):
    if not settings.PAYPAL_WEBHOOK_ID:
        raise ErrorPaypal('Falta configurar el webhook de PayPal.')
    datos = {'webhook_id': settings.PAYPAL_WEBHOOK_ID, 'webhook_event': evento}
    for campo in ['auth_algo', 'cert_url', 'transmission_id', 'transmission_sig', 'transmission_time']:
        valor = request.headers.get('Paypal-' + campo.replace('_', '-'))
        if not valor:
            return False
        datos[campo] = valor
    return solicitar('/v1/notifications/verify-webhook-signature', datos, 'POST').get('verification_status') == 'SUCCESS'
