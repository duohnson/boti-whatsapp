import json
from decimal import InvalidOperation
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .cuentas import empresa_actual, solo_propietario
from .models import Empresa, PagoPlan, SuscripcionPlan
from .planes import PLANES, PERIODOS, actualizar_cupo, resumen_plan
from . import paypal


@login_required
def planes(request):
    empresa = empresa_actual(request)
    resumen = resumen_plan(empresa)
    suscripcion = SuscripcionPlan.objects.filter(empresa=empresa).order_by('-creado').first()
    tarjetas = []
    for clave, datos in PLANES.items():
        tarjetas.append({'clave': clave, **datos, 'periodos': [
            {'clave': periodo, 'nombre': valores[0], 'importe': datos['precio'] * valores[1]}
            for periodo, valores in PERIODOS.items()]})
    return render(request, 'core/planes.html', {'empresa': empresa, 'resumen': resumen, 'tarjetas': tarjetas,
        'suscripcion': suscripcion, 'pagos': PagoPlan.objects.filter(empresa=empresa).order_by('-creado')[:20],
        'paypal_disponible': bool(settings.PAYPAL_CLIENT_ID and settings.PAYPAL_CLIENT_SECRET and settings.PAYPAL_WEBHOOK_ID)})


@login_required
@require_POST
@solo_propietario
def suscribir(request):
    plan, periodo = request.POST.get('plan'), request.POST.get('periodo')
    if request.POST.get('mercado') != 'internacional':
        messages.info(request, 'Para contratar desde Cuba, contacta a Boti por WhatsApp.')
        return redirect('planes')
    if plan not in ['premium', 'corporativo'] or periodo not in PERIODOS or request.POST.get('acepto') != '1':
        return JsonResponse({'error': 'Selecciona un plan, periodo y acepta la renovación automática.'}, status=400)
    if not settings.PAYPAL_WEBHOOK_ID:
        messages.error(request, 'PayPal todavía no está disponible. Contacta a Boti.')
        return redirect('planes')
    identificador = settings.PAYPAL_PLANES.get(f'{plan}_{periodo}')
    if not identificador:
        messages.error(request, 'Este periodo todavía no está disponible en PayPal.')
        return redirect('planes')
    try:
        with transaction.atomic():
            empresa = Empresa.objects.select_for_update().get(pk=empresa_actual(request).pk)
            actualizar_cupo(empresa)
            existente = SuscripcionPlan.objects.filter(empresa=empresa, estado__in=['pendiente', 'activo', 'suspendido']).first()
            if existente:
                if existente.estado != 'pendiente' or existente.plan != plan or existente.periodo != periodo:
                    raise paypal.ErrorPaypal('Ya tienes una suscripción en curso. Revísala antes de contratar otra.')
                suscripcion = existente
            else:
                if empresa.plan != 'gratis':
                    raise paypal.ErrorPaypal('Tu periodo pagado sigue vigente. Podrás contratar de nuevo cuando termine.')
                suscripcion = SuscripcionPlan.objects.create(empresa=empresa, plan=plan, periodo=periodo,
                    importe=PLANES[plan]['precio'] * PERIODOS[periodo][1], paypal_plan=identificador)
        # guardo el identificador antes de pedir la suscripcion para poder reintentar
        enlace = suscripcion.aprobacion or paypal.crear_suscripcion(suscripcion)
        return redirect(enlace)
    except paypal.ErrorPaypal as error:
        messages.error(request, str(error))
        return redirect('planes')


@login_required
def retorno(request):
    suscripcion = get_object_or_404(SuscripcionPlan, empresa__propietario=request.user, paypal_id=request.GET.get('subscription_id', ''))
    try:
        paypal.sincronizar(suscripcion)
        messages.info(request, 'Consultamos tu suscripción. El acceso se activa cuando PayPal confirma el cobro.')
    except (paypal.ErrorPaypal, ValueError, InvalidOperation):
        messages.warning(request, 'La confirmación sigue pendiente. Consulta de nuevo desde Planes; no necesitas pagar otra vez.')
    return redirect('planes')


@login_required
@require_POST
@solo_propietario
def consultar(request, identificador):
    suscripcion = get_object_or_404(SuscripcionPlan, pk=identificador, empresa=empresa_actual(request))
    try:
        if not suscripcion.paypal_id:
            return redirect(paypal.crear_suscripcion(suscripcion))
        paypal.sincronizar(suscripcion)
        messages.success(request, 'Estado de PayPal actualizado.')
    except (paypal.ErrorPaypal, ValueError, InvalidOperation):
        messages.error(request, 'No se pudo confirmar el estado. Puedes volver a consultar sin repetir el pago.')
    return redirect('planes')


@login_required
@require_POST
@solo_propietario
def cancelar(request, identificador):
    suscripcion = get_object_or_404(SuscripcionPlan, pk=identificador, empresa=empresa_actual(request))
    try:
        if suscripcion.estado not in ['cancelado', 'terminado']:
            datos = paypal.consultar_suscripcion(suscripcion)
            if datos['status'] not in ['CANCELLED', 'EXPIRED']:
                paypal.solicitar(f'/v1/billing/subscriptions/{suscripcion.paypal_id}/cancel', {'reason': 'Cancelación solicitada por el titular desde Boti.'}, 'POST')
            SuscripcionPlan.objects.filter(pk=suscripcion.pk).update(estado='cancelado')
        messages.success(request, 'Renovación cancelada. Conservas el acceso hasta el final del periodo pagado.')
    except paypal.ErrorPaypal:
        messages.error(request, 'No se pudo confirmar la cancelación. Puedes reintentar o cancelarla desde tu cuenta PayPal.')
    return redirect('planes')


@csrf_exempt
@require_POST
def webhook(request):
    if len(request.body) > 256000:
        return JsonResponse({'error': 'Evento demasiado grande'}, status=400)
    try:
        evento = json.loads(request.body)
        if not isinstance(evento, dict) or not paypal.verificar_evento(request, evento):
            return JsonResponse({'error': 'Firma no válida'}, status=400)
        recurso, tipo = evento.get('resource', {}), evento.get('event_type', '')
        if tipo == 'PAYMENT.SALE.COMPLETED':
            suscripcion = SuscripcionPlan.objects.filter(paypal_id=recurso.get('billing_agreement_id')).first()
            if not suscripcion:
                return JsonResponse({'error': 'Suscripción pendiente de registrar'}, status=503)
            paypal.consultar_suscripcion(suscripcion)
            monto = recurso.get('amount', {})
            paypal.registrar_cobro(suscripcion, recurso['id'], monto.get('total', '-1'), monto.get('currency'), parse_datetime(recurso.get('create_time', '')))
        elif tipo in ['PAYMENT.SALE.REFUNDED', 'PAYMENT.SALE.REVERSED']:
            with transaction.atomic():
                pago = PagoPlan.objects.filter(captura_paypal=recurso.get('sale_id') or recurso.get('id')).first()
                if not pago:
                    return JsonResponse({'error': 'Cobro pendiente de registrar'}, status=503)
                if pago:
                    empresa = Empresa.objects.select_for_update().get(pk=pago.empresa_id)
                    pago.estado = 'revisar'
                    pago.save(update_fields=['estado'])
                    if pago.fin and empresa.plan_hasta and pago.fin >= empresa.plan_hasta:
                        empresa.plan_hasta = timezone.now()
                        empresa.plan = 'gratis'
                        empresa.save(update_fields=['plan', 'plan_hasta'])
        elif tipo.startswith('BILLING.SUBSCRIPTION.'):
            suscripcion = SuscripcionPlan.objects.filter(paypal_id=recurso.get('id')).first()
            if suscripcion:
                paypal.consultar_suscripcion(suscripcion)
        return JsonResponse({'estado': 'recibido'})
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, InvalidOperation):
        return JsonResponse({'error': 'Evento no válido'}, status=400)
    except paypal.ErrorPaypal:
        return JsonResponse({'error': 'No se pudo verificar el evento'}, status=503)
