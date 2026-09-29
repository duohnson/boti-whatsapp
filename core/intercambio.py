import base64
import binascii
import json
from pathlib import Path
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from .models import NodoBot, OpcionNodo, validar_pdf

LIMITE_ARCHIVO = 25 * 1024 * 1024


def exportar_flujo(empresa):
    pasos = []
    for nodo in NodoBot.objects.filter(empresa=empresa).prefetch_related('opciones_salida').order_by('pk'):
        opciones = []
        for opcion in nodo.opciones_salida.all():
            datos = {'entrada':opcion.entrada_esperada, 'etiqueta':opcion.etiqueta, 'destino':opcion.nodo_siguiente_id}
            if opcion.archivo_pdf:
                with opcion.archivo_pdf.open('rb') as archivo:
                    contenido = archivo.read(15 * 1024 * 1024 + 1)
                if len(contenido) > 15 * 1024 * 1024:
                    raise ValidationError('Un PDF supera los 15 MB.')
                datos['pdf'] = {'nombre':Path(opcion.archivo_pdf.name).name, 'contenido':base64.b64encode(contenido).decode('ascii')}
            opciones.append(datos)
        pasos.append({'id':nodo.pk, 'nombre':nodo.nombre, 'tipo':nodo.tipo_nodo, 'mensaje':nodo.contenido_mensaje, 'inicial':nodo.es_nodo_inicial, 'opciones':opciones})
        if len(json.dumps(pasos).encode()) > LIMITE_ARCHIVO:
            raise ValidationError('El flujo con sus PDF supera los 25 MB. Reduce los adjuntos antes de exportar.')
    return {'version':1, 'pasos':pasos}


def importar_flujo(empresa, archivo):
    if archivo.size > LIMITE_ARCHIVO:
        raise ValidationError('El archivo no puede superar los 25 MB.')
    try:
        datos = json.loads(archivo.read())
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise ValidationError('El archivo no contiene JSON válido.')
    if not isinstance(datos, dict) or datos.get('version') != 1 or not isinstance(datos.get('pasos'), list):
        raise ValidationError('Formato de flujo no compatible.')
    pasos = datos['pasos']
    if not 1 <= len(pasos) <= 100:
        raise ValidationError('Importa entre 1 y 100 pasos por archivo.')
    identificadores, total_opciones, iniciales = set(), 0, 0
    for paso in pasos:
        if not isinstance(paso, dict) or type(paso.get('id')) is not int or paso['id'] in identificadores:
            raise ValidationError('Los identificadores de los pasos deben ser enteros y únicos.')
        identificadores.add(paso['id'])
        if not isinstance(paso.get('nombre'), str) or not 1 <= len(paso['nombre']) <= 255:
            raise ValidationError('Cada paso necesita un nombre de hasta 255 caracteres.')
        if not isinstance(paso.get('mensaje'), str) or not 1 <= len(paso['mensaje']) <= 10000:
            raise ValidationError('Cada mensaje debe tener entre 1 y 10000 caracteres.')
        if paso.get('tipo') not in dict(NodoBot.TIPO_NODO_OPCIONES) or type(paso.get('inicial')) is not bool:
            raise ValidationError('Tipo o marca inicial no válidos.')
        iniciales += paso['inicial']
        if not isinstance(paso.get('opciones'), list):
            raise ValidationError('Las opciones deben ser una lista.')
        total_opciones += len(paso['opciones'])
    if iniciales > 1 or total_opciones > 500:
        raise ValidationError('El flujo admite un inicio y hasta 500 opciones por archivo.')
    for paso in pasos:
        entradas = set()
        for opcion in paso['opciones']:
            if not isinstance(opcion, dict) or type(opcion.get('destino')) is not int or opcion['destino'] not in identificadores:
                raise ValidationError('Una opción apunta a un paso que no está en el archivo.')
            entrada, etiqueta = opcion.get('entrada'), opcion.get('etiqueta', '')
            if not isinstance(entrada, str) or not 1 <= len(entrada.strip()) <= 255 or not isinstance(etiqueta, str) or len(etiqueta) > 255:
                raise ValidationError('Entrada o etiqueta no válidas.')
            if entrada.strip().casefold() in entradas:
                raise ValidationError('Hay entradas repetidas en un paso.')
            entradas.add(entrada.strip().casefold())
            if 'pdf' in opcion:
                pdf = opcion['pdf']
                if not isinstance(pdf, dict) or not isinstance(pdf.get('contenido'), str):
                    raise ValidationError('PDF no válido.')
                try:
                    contenido = base64.b64decode(pdf['contenido'], validate=True)
                except (binascii.Error, ValueError):
                    raise ValidationError('El PDF no está codificado correctamente.')
                adjunto = ContentFile(contenido, name='opcion.pdf')
                validar_pdf(adjunto)
                opcion['_archivo'] = adjunto
    guardados = []
    try:
        with transaction.atomic():
            # serializo las importaciones para no crear dos inicios
            type(empresa).objects.select_for_update().get(pk=empresa.pk)
            hay_inicio = NodoBot.objects.filter(empresa=empresa, es_nodo_inicial=True).exists()
            mapa = {}
            for paso in pasos:
                mapa[paso['id']] = NodoBot.objects.create(empresa=empresa, nombre=paso['nombre'], tipo_nodo=paso['tipo'], contenido_mensaje=paso['mensaje'], es_nodo_inicial=paso['inicial'] and not hay_inicio)
            for paso in pasos:
                for opcion in paso['opciones']:
                    nueva = OpcionNodo(nodo_padre=mapa[paso['id']], nodo_siguiente=mapa[opcion['destino']], entrada_esperada=opcion['entrada'].strip(), etiqueta=opcion.get('etiqueta', ''))
                    if '_archivo' in opcion:
                        nueva.archivo_pdf.save('opcion.pdf', opcion['_archivo'], save=False)
                        guardados.append((nueva.archivo_pdf.storage, nueva.archivo_pdf.name))
                    nueva.save()
            return len(mapa)
    except Exception:
        for almacen, nombre in guardados:
            almacen.delete(nombre)
        raise
