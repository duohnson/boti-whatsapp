from django.db.models import Q
from .models import Empresa


def empresas_usuario(usuario):
    return Empresa.objects.filter(Q(propietario=usuario) | Q(agentes__usuario=usuario)).distinct()


def empresa_actual(request, crear=True):
    empresas = empresas_usuario(request.user)
    elegida = empresas.filter(pk=request.session.get('empresa_activa')).first()
    if elegida:
        return elegida
    propia = empresas.filter(propietario=request.user).first()
    if propia:
        return propia
    if empresas.exists():
        return empresas.first()
    if crear:
        return Empresa.objects.create(propietario=request.user)
    return None


def solo_propietario(vista):
    from functools import wraps
    from django.http import HttpResponse

    @wraps(vista)
    def comprobar(request, *args, **kwargs):
        if empresa_actual(request).propietario_id != request.user.pk:
            return HttpResponse('Solo el propietario puede modificar la configuración de la empresa.', status=403)
        return vista(request, *args, **kwargs)
    return comprobar
