import uuid
from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator

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
    limite_respuestas_ia = models.PositiveIntegerField(default=100)
    respuestas_ia_utilizadas = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)

# sesion de whatsapp al unir el codigo qr
class SesionWhatsApp(models.Model):
    # estos son los estados que se muestran mientras se enlaza el numero
    ESTADOS = [
        ('desconectado', 'Desconectado'),
        ('esperando_qr', 'Esperando QR'),
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
    fecha_conexion = models.DateTimeField(null=True, blank=True)
    ultima_actividad = models.DateTimeField(null=True, blank=True)

class CicloFacturacion(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    mes = models.IntegerField()
    anio = models.IntegerField()
    conteo_mensajes_ia = models.IntegerField(default=0)

    class Meta:
        constraints = [
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
            repetida = OpcionNodo.objects.filter(
                nodo_padre_id=self.nodo_padre_id,
                entrada_esperada__iexact=self.entrada_esperada.strip(),
            ).exclude(pk=self.pk)
            if repetida.exists():
                raise ValidationError({'entrada_esperada': 'Este valor ya está conectado a otro paso.'})

    def save(self, *args, **kwargs):
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
