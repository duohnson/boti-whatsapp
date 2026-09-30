from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from core.models import Empresa, PerfilUsuario, AvisoPlan, SuscripcionPlan, CodigoCorreo, LimiteAcceso
from core.correos import enviar_correo
from core.planes import PLANES


class Command(BaseCommand):
    help = 'Envia un aviso por periodo dentro de los tres dias anteriores al vencimiento.'

    def add_arguments(self, parser):
        parser.add_argument('--reintentar-errores', action='store_true')

    def handle(self, *args, **opciones):
        ahora = timezone.now()
        empresas = Empresa.objects.filter(plan__in=['premium', 'corporativo'], plan_hasta__gt=ahora, plan_hasta__lte=ahora + timedelta(days=3), propietario__is_active=True).select_related('propietario')
        enviados, errores = 0, 0
        for empresa in empresas:
            correo = empresa.propietario.email.strip().lower()
            if not PerfilUsuario.objects.filter(usuario=empresa.propietario, correo_verificado=correo).exists():
                continue
            with transaction.atomic():
                aviso, _ = AvisoPlan.objects.get_or_create(empresa=empresa, vencimiento=empresa.plan_hasta)
                aviso = AvisoPlan.objects.select_for_update().get(pk=aviso.pk)
                if aviso.estado != 'pendiente' and not (opciones['reintentar_errores'] and aviso.estado == 'error'):
                    continue
                aviso.estado = 'enviando'
                aviso.save(update_fields=['estado'])
            suscripcion = SuscripcionPlan.objects.filter(empresa=empresa, estado='activo').first()
            fecha = timezone.localtime(empresa.plan_hasta).strftime('%d/%m/%Y %H:%M %Z')
            nombre = PLANES[empresa.plan]['nombre']
            if suscripcion:
                titulo = 'Tu próxima renovación está cerca'
                mensaje = f'Tu periodo de {nombre} termina el {fecha}. Tu suscripción tiene renovación automática por {suscripcion.importe} USD.'
                detalle = 'Puedes cancelar los próximos cobros desde Planes en Boti o desde PayPal. Conservarás el acceso hasta terminar el periodo pagado.'
            else:
                titulo = 'Tu plan está por vencer'
                mensaje = f'Tu acceso a {nombre} termina el {fecha}. Después volverás al plan gratuito con el cupo que te corresponda.'
                detalle = 'Tus pasos y conversaciones se conservan. Puedes revisar las opciones en tu panel o renovar por WhatsApp si contrataste desde Cuba.'
            try:
                enviar_correo(correo, titulo, mensaje, detalle=detalle)
            except Exception:
                AvisoPlan.objects.filter(pk=aviso.pk).update(estado='error')
                errores += 1
            else:
                AvisoPlan.objects.filter(pk=aviso.pk).update(estado='enviado', enviado=timezone.now())
                enviados += 1
        CodigoCorreo.objects.filter(vence__lt=ahora - timedelta(days=1)).delete()
        LimiteAcceso.objects.filter(inicio__lt=ahora - timedelta(days=2)).delete()
        self.stdout.write(f'avisados: {enviados}; errores: {errores}')
        if errores:
            raise CommandError('Hay correos sin confirmacion. Revisa SMTP antes de reintentarlos.')
