from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from core.models import Empresa, PagoPlan, SuscripcionPlan
from core.planes import PLANES, PERIODOS, activar_pago


class Command(BaseCommand):
    help = 'Registra un pago verificado por WhatsApp y activa el periodo contratado, sin renovacion automatica.'

    def add_arguments(self, parser):
        parser.add_argument('empresa', type=int)
        parser.add_argument('plan', choices=['premium', 'corporativo'])
        parser.add_argument('periodo', choices=list(PERIODOS))
        parser.add_argument('--referencia', required=True)

    @transaction.atomic
    def handle(self, *args, **opciones):
        empresa = Empresa.objects.select_for_update().filter(pk=opciones['empresa']).first()
        if not empresa:
            raise CommandError('La empresa no existe.')
        referencia = 'cuba-' + opciones['referencia'].strip()
        if len(referencia) > 128 or referencia == 'cuba-':
            raise CommandError('Usa una referencia de pago de 1 a 123 caracteres.')
        if PagoPlan.objects.filter(captura_paypal=referencia).exists():
            raise CommandError('Esta referencia ya fue registrada.')
        if SuscripcionPlan.objects.filter(empresa=empresa, estado__in=['pendiente', 'activo', 'suspendido']).exists():
            raise CommandError('Primero resuelve la suscripcion existente de PayPal.')
        pago = PagoPlan.objects.create(empresa=empresa, plan=opciones['plan'], periodo=opciones['periodo'],
            importe=Decimal(PLANES[opciones['plan']]['precio'] * PERIODOS[opciones['periodo']][1]), medio='whatsapp', captura_paypal=referencia)
        if empresa.plan_hasta and empresa.plan == pago.plan:
            from django.utils import timezone
            pago.inicio = max(timezone.now(), empresa.plan_hasta)
        try:
            activar_pago(pago, empresa)
        except ValueError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(self.style.SUCCESS('pago registrado y periodo activado.'))
