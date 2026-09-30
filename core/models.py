import uuid
from datetime import time
from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator, MaxValueValidator

# validacion de pdf para que no supere mucho peso
def validar_pdf(archivo):
    # primero reviso el peso antes de guardar el archivo
    if archivo.size > 15 * 1024 * 1024:
        raise ValidationError('El PDF no puede superar los 15 MB.')
    # reviso que el archivo si arranque como pdf
    posicion = archivo.tell()
    encabezado = archivo.read(5)
    archivo.seek(posicion)
    if encabezado != b'%PDF-':
        raise ValidationError('El archivo debe ser un PDF válido.')

class Empresa(models.Model):
    # cada cuenta guarda aqui el prompt y el modo de inicio
    propietario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='empresa_whatsapp', null=True, blank=True)
    prompt_sistema_ia = models.TextField(default='Eres un asistente virtual')
    ia_desde_primer_mensaje = models.BooleanField(default=False)
    # limitar las respuestas gratuitas de ia por empresa
    limite_respuestas_ia = models.PositiveIntegerField(default=0)
    respuestas_ia_utilizadas = models.PositiveIntegerField(default=0)
    plan = models.CharField(max_length=16, default='gratis', choices=[('gratis', 'Gratuito'), ('premium', 'Premium'), ('corporativo', 'Corporativo')])
    plan_hasta = models.DateTimeField(null=True, blank=True)
    ciclo_ia_hasta = models.DateTimeField(null=True, blank=True)
    bloqueado_hasta = models.DateTimeField(null=True, blank=True)
    respuestas_gratis = models.PositiveIntegerField(default=0)
    respuestas_totales = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)
    reabrir_conversaciones = models.BooleanField(default=True)
    max_mensajes_ia = models.PositiveSmallIntegerField(default=20, validators=[MinValueValidator(1), MaxValueValidator(50)])
    accion_limite_ia = models.CharField(max_length=10, default='aviso', choices=[('aviso', 'Mostrar aviso'), ('humano', 'Pasar a una persona')])
    mensaje_limite_ia = models.TextField(default='Se alcanzó el límite de respuestas de IA para esta cuenta.')
    bienvenida = models.TextField(blank=True)
    despedida = models.TextField(blank=True)
    tono = models.CharField(max_length=12, default='neutral', choices=[('neutral', 'Neutral'), ('cercano', 'Cercano'), ('formal', 'Formal')])
    idioma = models.CharField(max_length=5, default='es', choices=[('es', 'Español'), ('en', 'Inglés'), ('pt', 'Portugués')])
    derivar_auto = models.BooleanField(default=False)
    palabras_clave = models.CharField(max_length=500, blank=True, default='persona, agente, humano')
    fuera_horario = models.BooleanField(default=False)
    horario_inicio = models.TimeField(default=time(8))
    horario_fin = models.TimeField(default=time(17))
    zona_horaria = models.CharField(max_length=64, default='America/Costa_Rica')
    mensaje_fuera_horario = models.TextField(default='Estamos fuera de horario. Te responderemos cuando volvamos.')

class AgenteEmpresa(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='agentes')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['empresa', 'usuario'], name='agente_empresa_unico')]


# sesion de whatsapp al unir el codigo qr
class SesionWhatsApp(models.Model):
    # estos son los estados que se muestran mientras se enlaza el numero
    ESTADOS = [
        ('desconectado', 'Desconectado'),
        ('esperando_qr', 'Esperando QR'),
        ('esperando_codigo', 'Esperando código manual'),
        ('conectado', 'Conectado'),
        ('autenticando', 'Autenticando'),
        ('error', 'Error'),
    ]
    empresa = models.OneToOneField(Empresa, on_delete=models.CASCADE, related_name='sesion_whatsapp')
    # este id tambien separa la carpeta persistente de whatsapp-web.js
    identificador = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    numero_telefono = models.CharField(max_length=32, blank=True)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='desconectado')
    codigo_qr = models.TextField(blank=True)
    codigo_manual = models.CharField(max_length=20, blank=True)
    fecha_conexion = models.DateTimeField(null=True, blank=True)
    ultima_actividad = models.DateTimeField(null=True, blank=True)

class CicloFacturacion(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    mes = models.IntegerField()
    anio = models.IntegerField()
    conteo_mensajes_ia = models.IntegerField(default=0)

    class Meta:
        constraints = [
            # guardar un solo conteo mensual por empresa
            models.UniqueConstraint(fields=['empresa', 'mes', 'anio'], name='ciclo_ia_empresa_mes_unico'),
        ]

class NodoBot(models.Model):
    # con estos pasos el cliente arma su propio flujo
    TIPO_NODO_OPCIONES = [
        ('MENU', 'Menu'),
        ('TEXT', 'Texto'),
        ('AI_AGENT', 'Agente IA'),
        ('HUMAN_AGENT', 'Atención humana'),
        ('END', 'Finalizar conversación'),
    ]
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    nombre = models.CharField(max_length=255)
    tipo_nodo = models.CharField(max_length=50, choices=TIPO_NODO_OPCIONES)
    contenido_mensaje = models.TextField()
    es_nodo_inicial = models.BooleanField(default=False)

    class Meta:
        constraints = [
            # cada empresa puede tener una sola bienvenida
            models.UniqueConstraint(
                fields=['empresa'],
                condition=models.Q(es_nodo_inicial=True),
                name='un_nodo_inicial_por_empresa',
            ),
        ]

class OpcionNodo(models.Model):
    # la opcion conecta este paso con el que sigue
    nodo_padre = models.ForeignKey(NodoBot, related_name='opciones_salida', on_delete=models.CASCADE)
    nodo_siguiente = models.ForeignKey(NodoBot, related_name='opciones_entrada', on_delete=models.CASCADE)
    entrada_esperada = models.CharField(max_length=255)
    etiqueta = models.CharField(max_length=255, blank=True)
    # pdf opcional para mandar segun la opcion elegida
    archivo_pdf = models.FileField(upload_to='documentos_bot/', blank=True, validators=[FileExtensionValidator(['pdf']), validar_pdf])

    def __str__(self):
        return self.etiqueta or self.entrada_esperada

    def clean(self):
        if self.nodo_padre_id and self.nodo_siguiente_id:
            # no dejo que un flujo salte a pasos de otra empresa
            if self.nodo_padre.empresa_id != self.nodo_siguiente.empresa_id:
                raise ValidationError('Los pasos de una opción deben pertenecer a la misma empresa.')
        if self.nodo_padre_id and self.entrada_esperada:
            # evitar dos conexiones con el mismo valor de entrada
            repetida = OpcionNodo.objects.filter(
                nodo_padre_id=self.nodo_padre_id,
                entrada_esperada__iexact=self.entrada_esperada.strip(),
            ).exclude(pk=self.pk)
            if repetida.exists():
                raise ValidationError({'entrada_esperada': 'Este valor ya está conectado a otro paso.'})

    def save(self, *args, **kwargs):
        # validar tambien los guardados que no pasan por formularios
        self.full_clean()
        return super().save(*args, **kwargs)

class SesionUsuario(models.Model):
    # aqui queda si contesta el bot, una persona o nadie
    ESTADOS = [
        ('bot', 'Bot'),
        ('humano', 'Atención humana'),
        ('cerrada', 'Cerrada'),
    ]
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='sesiones_chat', null=True, blank=True)
    telefono_cliente = models.CharField(max_length=255)
    asignado_a = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    destino_chat = models.CharField(max_length=255, blank=True)
    nodo_actual = models.ForeignKey(NodoBot, on_delete=models.SET_NULL, null=True, blank=True)
    estado = models.CharField(max_length=12, choices=ESTADOS, default='bot')
    ultima_actividad = models.DateTimeField(auto_now=True)
    activo = models.BooleanField(default=True)

    class Meta:
        constraints = [
            # el mismo telefono puede escribir a varias empresas sin mezclar chats
            models.UniqueConstraint(fields=['empresa', 'telefono_cliente'], name='sesion_chat_empresa_telefono_unicos'),
        ]

class HistorialChat(models.Model):
    # guardo aparte los mensajes del cliente, la ia y la persona
    ROL_OPCIONES = [
        ('user', 'Usuario'),
        ('assistant', 'Asistente'),
        ('agent', 'Agente humano'),
    ]
    sesion_usuario = models.ForeignKey(SesionUsuario, on_delete=models.CASCADE)
    rol = models.CharField(max_length=50, choices=ROL_OPCIONES)
    contenido = models.TextField()
    estado_entrega = models.CharField(max_length=12, default='recibido', choices=[('recibido', 'Recibido'), ('historico', 'Sin estado anterior'), ('generado', 'Generado'), ('enviando', 'Enviando'), ('enviado', 'Enviado'), ('fallido', 'Fallido'), ('incierto', 'Sin confirmación')])
    id_envio = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    respuesta_a = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='respuestas')
    adjunto_entrega = models.FileField(upload_to='pdfs/', blank=True)
    opcion_pdf = models.ForeignKey(OpcionNodo, on_delete=models.SET_NULL, null=True, blank=True)
    error_entrega = models.CharField(max_length=255, blank=True)
    intento_entrega = models.DateTimeField(null=True, blank=True)
    identificador_mensaje = models.CharField(max_length=255, blank=True)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # si node reintenta un mensaje no proceso dos veces la misma entrada
            models.UniqueConstraint(
                fields=['sesion_usuario', 'identificador_mensaje'],
                condition=~models.Q(identificador_mensaje=''),
                name='mensaje_whatsapp_entrante_unico',
            ),
        ]


class PagoPlan(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT)
    identificador = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    orden_paypal = models.CharField(max_length=128, null=True, blank=True, unique=True)
    captura_paypal = models.CharField(max_length=128, null=True, blank=True, unique=True)
    plan = models.CharField(max_length=16, choices=[('premium', 'Premium'), ('corporativo', 'Corporativo')])
    periodo = models.CharField(max_length=16)
    importe = models.DecimalField(max_digits=8, decimal_places=2)
    moneda = models.CharField(max_length=3, default='USD')
    estado = models.CharField(max_length=16, default='pendiente', choices=[('pendiente', 'Pendiente'), ('completado', 'Completado'), ('revisar', 'Revisar')])
    medio = models.CharField(max_length=16, default='paypal')
    creado = models.DateTimeField(auto_now_add=True)
    inicio = models.DateTimeField(null=True, blank=True)
    fin = models.DateTimeField(null=True, blank=True)


class SuscripcionPlan(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT)
    identificador = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    paypal_id = models.CharField(max_length=128, unique=True, null=True, blank=True)
    paypal_plan = models.CharField(max_length=128)
    plan = models.CharField(max_length=16)
    periodo = models.CharField(max_length=16)
    importe = models.DecimalField(max_digits=8, decimal_places=2)
    estado = models.CharField(max_length=24, default='pendiente')
    aprobacion = models.URLField(max_length=1000, blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['empresa'], condition=models.Q(estado__in=['pendiente', 'activo', 'suspendido']), name='una_suscripcion_vigente_empresa')]


class PerfilUsuario(models.Model):
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='perfil_boti')
    correo_verificado = models.EmailField(unique=True, null=True, blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    ubicacion = models.CharField(max_length=200, blank=True)
    organizacion = models.CharField(max_length=150, blank=True)
    cedula_juridica = models.CharField(max_length=60, blank=True)
    codigo_postal = models.CharField(max_length=20, blank=True)
    pais = models.CharField(max_length=80, blank=True)
    direccion = models.CharField(max_length=250, blank=True)


class CodigoCorreo(models.Model):
    identificador = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True)
    correo = models.EmailField()
    proposito = models.CharField(max_length=20)
    huella = models.CharField(max_length=64)
    vinculo = models.CharField(max_length=64)
    datos = models.JSONField(default=dict)
    intentos = models.PositiveSmallIntegerField(default=0)
    creado = models.DateTimeField(auto_now_add=True)
    vence = models.DateTimeField()
    usado = models.BooleanField(default=False)


class LimiteAcceso(models.Model):
    clave = models.CharField(max_length=64, unique=True)
    inicio = models.DateTimeField()
    intentos = models.PositiveIntegerField(default=0)


class AvisoPlan(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    vencimiento = models.DateTimeField()
    estado = models.CharField(max_length=16, default='pendiente')
    enviado = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['empresa', 'vencimiento'], name='aviso_unico_periodo')]
