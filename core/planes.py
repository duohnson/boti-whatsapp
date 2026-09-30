import calendar
from datetime import timedelta
from django.utils import timezone

PLANES = {
    'gratis': {'nombre': 'Gratuito', 'precio': 0, 'limite': 50},
    'premium': {'nombre': 'Premium', 'precio': 1, 'limite': 0},
    'corporativo': {'nombre': 'Corporativo', 'precio': 2, 'limite': 1000},
}
PERIODOS = {
    'semana': ('1 semana', 1, 7, 0),
    'quincena': ('15 dias', 2, 15, 0),
    'mes': ('1 mes', 4, 0, 1),
    'trimestre': ('3 meses', 12, 0, 3),
    'semestre': ('6 meses', 24, 0, 6),
}


def sumar_meses(fecha, meses=1):
    total = fecha.year * 12 + fecha.month - 1 + meses
    anio, mes = divmod(total, 12)
    return fecha.replace(year=anio, month=mes + 1, day=min(fecha.day, calendar.monthrange(anio, mes + 1)[1]))


def actualizar_cupo(empresa, ahora=None):
    ahora = ahora or timezone.now()
    if empresa.plan != 'gratis' and (not empresa.plan_hasta or empresa.plan_hasta <= ahora):
        empresa.plan = 'gratis'
    if empresa.bloqueado_hasta and empresa.bloqueado_hasta <= ahora:
        empresa.respuestas_gratis = 0
        if empresa.plan == 'gratis':
            empresa.respuestas_ia_utilizadas = 0
        empresa.bloqueado_hasta = None
    if empresa.ciclo_ia_hasta and empresa.ciclo_ia_hasta <= ahora:
        empresa.respuestas_ia_utilizadas = 0
        while empresa.ciclo_ia_hasta <= ahora:
            empresa.ciclo_ia_hasta = sumar_meses(empresa.ciclo_ia_hasta)
    empresa.limite_respuestas_ia = PLANES['corporativo']['limite'] if empresa.plan == 'corporativo' else 0
    return empresa


def puede_responder(empresa):
    return empresa.plan != 'gratis' or (not empresa.bloqueado_hasta and empresa.respuestas_gratis < 50)


def contar_respuesta(empresa, ahora=None):
    empresa.respuestas_totales += 1
    if empresa.plan == 'gratis':
        empresa.respuestas_gratis += 1
        if empresa.respuestas_gratis >= 50:
            empresa.bloqueado_hasta = sumar_meses(ahora or timezone.now())


def resumen_plan(empresa):
    actualizar_cupo(empresa)
    gratis = empresa.plan == 'gratis'
    usados = empresa.respuestas_gratis if gratis else empresa.respuestas_ia_utilizadas
    limite = PLANES[empresa.plan]['limite']
    return {'nombre': PLANES[empresa.plan]['nombre'], 'gratis': gratis, 'usados': usados,
            'limite': limite, 'restantes': max(0, limite - usados), 'porcentaje': min(100, usados * 100 // limite) if limite else 0,
            'bloqueado': gratis and not puede_responder(empresa)}


def activar_pago(pago, empresa):
    if pago.estado == 'completado':
        return
    ahora = timezone.now()
    actualizar_cupo(empresa, ahora)
    inicio = pago.inicio or ahora
    periodo = PERIODOS[pago.periodo]
    pago.inicio = inicio
    pago.fin = sumar_meses(inicio, periodo[3]) if periodo[3] else inicio + timedelta(days=periodo[2])
    if pago.fin <= ahora:
        pago.estado = 'completado'
        pago.save()
        return
    if empresa.plan != 'gratis' and empresa.plan != pago.plan:
        raise ValueError('Espera a que termine tu plan actual para cambiar de plan.')
    empresa.plan = pago.plan
    empresa.plan_hasta = max(empresa.plan_hasta, pago.fin) if empresa.plan_hasta else pago.fin
    empresa.limite_respuestas_ia = PLANES[pago.plan]['limite']
    if not empresa.ciclo_ia_hasta:
        empresa.ciclo_ia_hasta = sumar_meses(inicio)
        empresa.respuestas_ia_utilizadas = 0
    actualizar_cupo(empresa, ahora)
    empresa.save()
    pago.estado = 'completado'
    pago.save()
