from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from core.paypal import solicitar, frecuencia, ErrorPaypal
from core.planes import PLANES, PERIODOS


def guardar_variable(nombre, valor):
    archivo = Path(settings.BASE_DIR) / '.env'
    lineas = archivo.read_text().splitlines() if archivo.exists() else []
    nueva = f'{nombre}={valor}'
    for posicion, linea in enumerate(lineas):
        if linea.startswith(nombre + '='):
            lineas[posicion] = nueva
            break
    else:
        lineas.append(nueva)
    archivo.write_text('\n'.join(lineas) + '\n')
    archivo.chmod(0o600)


class Command(BaseCommand):
    help = 'Crea el catalogo de suscripciones y el webhook de PayPal y guarda sus identificadores en .env.'

    def handle(self, *args, **opciones):
        if not settings.BOTI_URL_PUBLICA.startswith('https://'):
            raise CommandError('Configura BOTI_URL_PUBLICA con una direccion https accesible por PayPal.')
        try:
            producto = settings.PAYPAL_PRODUCTO_ID
            if not producto:
                datos = solicitar('/v1/catalogs/products', {'name': 'Boti', 'description': 'Planes de atencion y automatizacion de conversaciones', 'type': 'SERVICE', 'category': 'SOFTWARE'}, 'POST')
                producto = datos['id']
                guardar_variable('PAYPAL_PRODUCTO_ID', producto)
            for plan in ['premium', 'corporativo']:
                for periodo, valores in PERIODOS.items():
                    if settings.PAYPAL_PLANES[f'{plan}_{periodo}']:
                        continue
                    datos = solicitar('/v1/billing/plans', {
                        'product_id': producto, 'name': f'Boti {PLANES[plan]["nombre"]} - {valores[0]}', 'status': 'ACTIVE',
                        'billing_cycles': [{'frequency': frecuencia(periodo), 'tenure_type': 'REGULAR', 'sequence': 1,
                            'total_cycles': 0, 'pricing_scheme': {'fixed_price': {'value': str(PLANES[plan]['precio'] * valores[1]), 'currency_code': 'USD'}}}],
                        'payment_preferences': {'auto_bill_outstanding': False, 'setup_fee': {'value': '0', 'currency_code': 'USD'}, 'payment_failure_threshold': 1}}, 'POST')
                    guardar_variable(f'PAYPAL_{plan.upper()}_{periodo.upper()}', datos['id'])
                    self.stdout.write(f'listo: {plan} / {periodo}')
            if not settings.PAYPAL_WEBHOOK_ID:
                url = settings.BOTI_URL_PUBLICA + '/api/paypal/webhook/'
                existentes = solicitar('/v1/notifications/webhooks').get('webhooks', [])
                existente = next((item for item in existentes if item.get('url') == url), None)
                datos = existente or solicitar('/v1/notifications/webhooks', {'url': url, 'event_types': [{'name': '*'}]}, 'POST')
                guardar_variable('PAYPAL_WEBHOOK_ID', datos['id'])
            self.stdout.write(self.style.SUCCESS('catalogo listo. reinicia django para cargar los identificadores.'))
        except (ErrorPaypal, KeyError) as error:
            raise CommandError('No se pudo completar la configuracion. Se conservaron los identificadores ya guardados; revisa las credenciales y reintenta.') from error
