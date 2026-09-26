import json
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from .tasks import procesar_mensaje_whatsapp

@csrf_exempt
def webhook_whatsapp(request):
    if request.method == 'GET':
        mode = request.GET.get('hub.mode')
        token = request.GET.get('hub.verify_token')
        challenge = request.GET.get('hub.challenge')
        
        if mode == 'subscribe' and token == 'boti_token_secreto':
            return HttpResponse(int(challenge), content_type="text/plain", status=200)
        return HttpResponse('Error', status=403)
        
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            procesar_mensaje_whatsapp.delay(data)
            return HttpResponse('EVENT_RECEIVED', status=200)
        except Exception:
            return HttpResponse('ERROR', status=400)
            
    return HttpResponse('Method not allowed', status=405)

from django.shortcuts import render
from django.utils import timezone
from .models import Empresa, CicloFacturacion

def dashboard(request):
    return render(request, 'core/dashboard.html')

def dashboard_datos(request):
    empresas = Empresa.objects.all()
    hoy = timezone.now()
    datos = []
    for empresa in empresas:
        ciclo = CicloFacturacion.objects.filter(empresa=empresa, mes=hoy.month, anio=hoy.year).first()
        conteo = ciclo.conteo_mensajes_ia if ciclo else 0
        datos.append((empresa, conteo))
    return render(request, 'core/dashboard_filas.html', {'datos': datos})

@csrf_exempt
def vincular_whatsapp(peticion):
    if peticion.method == 'POST':
        try:
            datos = json.loads(peticion.body)
            token_acceso = datos.get('accessToken')
            
            waba_id = "pendiente_por_api_meta"
            telefono_id = "pendiente_por_api_meta"
            
            Empresa.objects.create(
                waba_id=waba_id, 
                telefono_id=telefono_id, 
                token_acceso=token_acceso, 
                activo=True,
                prompt_sistema_ia="Eres un asistente virtual"
            )
            
            return HttpResponse(json.dumps({'estado': 'ok'}), content_type='application/json')
        except Exception as error:
            return HttpResponse(json.dumps({'estado': 'error', 'error': str(error)}), content_type='application/json', status=400)
    return HttpResponse('Metodo no permitido', status=405)
