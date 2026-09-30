# Boti Whatsapp

Un backend básico que estoy armando para manejar chatbots de WhatsApp. La idea principal es tener un panel donde se puedan armar flujos de mensajes, y no depender siempre de la IA, que pasa si no configuro una API KEY? Nada, haces tu flujo de mensajes y responde igual, usa IA solo si lo decido y que apis le coloque, ademas de que se puede enviar a consulta humana, para que un asistente o tu persona pueda responder.

Atención: El proyecto está en pleno desarrollo. Las sesiones no tienen medidas de seguridad avanzadas ni autenticación de dos pasos. Por ahora sirve más como base para continuar programando o reciclar código en otros proyectos. No recomiendo desplegarlo en producción tal como está.

Dentro de un tiempo estara mejor armado, le falta mucho..

El panel permite vincular whatsapp por qr o codigo manual, configurar el bot, editar sus pasos, atender conversaciones y consultar metricas.
Como conecto mi whatsapp? por codigo QR con la libreria de whatsapp-web.js que es un cliente de whatsapp no oficial.
Como se comunican? por medio de http, node se comunica con django y django con node.

## Qué tecnologías uso

- Backend: Python y Django (ORM, modelos, vistas).
- IA: Esto esta verde, apenas en desarrollo.
- Base de datos: PostgreSQL, en arquitectura multi-tenant.
- Servicio de WhatsApp: Node.js y la librería whatsapp-web.js (usa Puppeteer).

## Estructura básica

El repositorio está dividido en dos partes principales:

- `core/` y `boti_project/`: El código de Django donde está la lógica de los usuarios, los flujos del bot y la comunicación con la IA.
- `servicio_whatsapp/`: El servidor en Node.js que levanta la sesión de WhatsApp, procesa los mensajes y los envía a Django.

## Instalación

Necesitas tener la version de Python compatible con requirements.txt y Node.js 22+ instalados.

1. Clona el repositorio e ingresa a la carpeta:
```bash
git clone https://github.com/duohnson/boti-whatsapp.git
cd boti-whatsapp
```

2. Configura el entorno virtual y las dependencias de Python:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. Instala las dependencias de Node.js:
```bash
cd servicio_whatsapp
npm install
cd ..
```

4. Prepara la base de datos y crea tu usuario administrador:
```bash
python manage.py migrate
python manage.py createsuperuser
```

## Variables de entorno

Crea un archivo `.env` en la raíz del proyecto. Estos son los valores mínimos para arrancar:
(Aconsejo usar permisos 600 para el .env en linux.)

```env
DJANGO_SECRET_KEY=tu_clave_secreta
WHATSAPP_INTERNAL_SECRET=un_token_seguro_para_comunicar_node_y_django

WHATSAPP_NODE_URL=http://127.0.0.1:11223
DJANGO_URL_INTERNA=http://127.0.0.1:7213
PUERTO_WHATSAPP=11223

IA_PROVEEDOR_PRINCIPAL=openai
OPENAI_API_KEY=tu_api_key_de_openai
```

## Cómo ejecutar el proyecto

Necesitas abrir dos terminales en paralelo porque Django y Node.js corren por separado.

En la primera terminal, levanta Django:
```bash
source .venv/bin/activate
python manage.py runserver 7213
```

En la segunda terminal, inicia el servicio de WhatsApp:
```bash
cd servicio_whatsapp
node servidor.js
```

Cuando ambos estén corriendo, entra a `http://127.0.0.1:7213` en tu navegador.

