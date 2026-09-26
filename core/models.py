from django.db import models

class Empresa(models.Model):
    waba_id = models.CharField(max_length=255)
    telefono_id = models.CharField(max_length=255)
    token_acceso = models.CharField(max_length=255)
    prompt_sistema_ia = models.TextField()
    activo = models.BooleanField(default=True)

class CicloFacturacion(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    mes = models.IntegerField()
    anio = models.IntegerField()
    conteo_mensajes_ia = models.IntegerField(default=0)

class NodoBot(models.Model):
    TIPO_NODO_OPCIONES = [
        ('MENU', 'Menu'),
        ('TEXT', 'Texto'),
        ('AI_AGENT', 'Agente IA'),
    ]
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    nombre = models.CharField(max_length=255)
    tipo_nodo = models.CharField(max_length=50, choices=TIPO_NODO_OPCIONES)
    contenido_mensaje = models.TextField()
    es_nodo_inicial = models.BooleanField(default=False)

class OpcionNodo(models.Model):
    nodo_padre = models.ForeignKey(NodoBot, related_name='opciones_salida', on_delete=models.CASCADE)
    nodo_siguiente = models.ForeignKey(NodoBot, related_name='opciones_entrada', on_delete=models.CASCADE)
    entrada_esperada = models.CharField(max_length=255)

class SesionUsuario(models.Model):
    telefono_cliente = models.CharField(max_length=255)
    nodo_actual = models.ForeignKey(NodoBot, on_delete=models.SET_NULL, null=True, blank=True)
    ultima_actividad = models.DateTimeField(auto_now=True)
    activo = models.BooleanField(default=True)

class HistorialChat(models.Model):
    ROL_OPCIONES = [
        ('user', 'Usuario'),
        ('assistant', 'Asistente'),
    ]
    sesion_usuario = models.ForeignKey(SesionUsuario, on_delete=models.CASCADE)
    rol = models.CharField(max_length=50, choices=ROL_OPCIONES)
    contenido = models.TextField()
    fecha = models.DateTimeField(auto_now_add=True)
