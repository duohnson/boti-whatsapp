# Boti Whatsapp 

Pequeño backend basico de PostgreSQL, Python y Javascript. 
Sin frontend, y con DJANGO ORM + SQL MODELOS.
Listo para descargar y crear tu propia plataforma de chatbot.

ATENCIÓN: Es básico, apenas para ahorrarse la creación de nodos y continuarlo, logins no poseen Auth de 2 pasos ni seguridad, no hacer deploy, es para continuar programando o reutilizarse en distintos proyectos que incluyan chatbots de whatsapp + modelos IA.

El sistema opera bajo la licencia [GPL-3.0](#LICENSE).

Plataforma multi-tenant para chatbots, con flujos personalizables, integración de IA (OpenAI, Gemini y Claude) y atención de servicio al cliente para soporte web. Cada usuario registra su propia cuenta, conecta su número de WhatsApp mediante código QR y crea su árbol de flujos y respuesta desde un panel web.

---

## Contenido

- [Arquitectura](#arquitectura)
- [Características](#características)
- [Requisitos previos](#requisitos-previos)
- [Instalación](#instalación)
- [Variables de entorno](#variables-de-entorno)
- [Ejecución en desarrollo](#ejecución-en-desarrollo)
- [Modelos de datos](#modelos-de-datos)
- [API interna Django y Node](#api-interna-django-y-node)
- [Flujo de un mensaje entrante](#flujo-de-un-mensaje-entrante)
- [Tests](#tests)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Despliegue en producción](#despliegue-en-producción)
- [Licencia](#licencia)

---

## Arquitectura

El sistema se compone de dos procesos que se comunican por HTTP local autenticado con un secreto compartido:

1. Cliente / Panel web
   - Dashboard, Configuración de bot, Atención humana
   - Se comunica vía HTTPS con Django
2. Backend (Django en puerto 7213)
   - Autenticación y registro de usuarios
   - Gestión de flujos (NodoBot / OpcionNodo)
   - Motor de conversaciones
   - Integración multi-proveedor de Inteligencia Artificial
   - Panel de atención humana
   - Se comunica vía HTTP interno con Token Bearer con Node.js
3. Servicio WhatsApp (Node.js en puerto 11223)
   - Utiliza whatsapp-web.js (sesión Puppeteer)
   - Generación de código QR
   - Envío y recepción de mensajes y archivos PDF
   - Recuperación automática de sesiones

Componentes principales:
- Backend: Django 6.1 y Python. Maneja la lógica de negocio, modelos, vistas e IA.
- Servicio WhatsApp: Node.js y whatsapp-web.js. Actúa como puente con WhatsApp Web.
- Base de datos: PostgreSQL (producción) y SQLite (desarrollo) para persistencia.
- Inteligencia Artificial: OpenAI, Gemini, Claude. Respuestas automáticas con respaldo en caso de fallos.

---

## Características

- Multi-tenant: Cada usuario cuenta con su propia empresa, flujo de bot, sesión de WhatsApp y límites de IA.
- Conexión QR en tiempo real: El panel web muestra el código QR generado por whatsapp-web.js y actualiza su estado periódicamente.
- Editor de flujos: Permite crear pasos de tipo Menú, Texto, Agente IA, Atención humana o Fin de conversación, y conectarlos.
- Adjuntos PDF: Cada opción del bot puede enviar un archivo PDF adjunto (con límite de tamaño y validación).
- IA multi-proveedor: Permite configurar un proveedor principal y alternativas de respaldo.
- Límites de IA: Conteo mensual de uso por empresa con bloqueo al alcanzar el tope establecido.
- Atención humana: Capacidad de pausar el bot y transferir el chat a un operador humano.
- Comando volver: El cliente puede escribir "volver" en cualquier momento para regresar al menú inicial.
- Seguridad: Implementa protecciones CSRF, HSTS, cookies seguras y autorización interna mediante tokens.
- Recuperación de sesiones: El servicio de Node reintenta automáticamente conectar las sesiones activas al reiniciar.

---

## Requisitos previos

- Python 3.11 o superior.
- Node.js 18 o superior (incluye npm).
- PostgreSQL 14 o superior (opcional en desarrollo, se utiliza SQLite por defecto).
- Google Chrome o Chromium (requerido para el funcionamiento de Puppeteer y whatsapp-web.js).

---

## Instalación

1. Clonar el repositorio
Clona el repositorio en tu máquina local e ingresa al directorio del proyecto:
git clone https://github.com/duohnson/boti-whatsapp.git
cd boti-whatsapp

2. Backend (Django)
Crea y activa un entorno virtual de Python, luego instala las dependencias:
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

3. Servicio WhatsApp (Node.js)
Instala las dependencias del servicio de Node:
cd servicio_whatsapp
npm install
cd ..

4. Configurar variables de entorno
Crea un archivo .env en la raíz del proyecto basándote en la sección de Variables de entorno.

5. Migraciones y superusuario
Aplica las migraciones de base de datos y crea un usuario administrador:
python manage.py migrate
python manage.py createsuperuser

---

## Variables de entorno

Crea un archivo .env en la raíz del proyecto. Las variables más importantes son:

Variables Obligatorias
- DJANGO_SECRET_KEY: Clave secreta para la aplicación Django.
- WHATSAPP_INTERNAL_SECRET: Secreto compartido entre Django y Node para autenticar llamadas internas.

Configuración de Django
- DJANGO_DEBUG: 1 para activar modo debug, 0 para producción.
- DJANGO_ALLOWED_HOSTS: Hosts permitidos, separados por coma (ej. localhost,127.0.0.1).
- DJANGO_FORZAR_HTTPS: 1 para redirigir tráfico a HTTPS en producción.

Base de datos
- POSTGRES_DB: Nombre de la base de datos PostgreSQL (si se deja vacío, usa SQLite).
- POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT: Credenciales de conexión a PostgreSQL.

Servicio WhatsApp
- WHATSAPP_NODE_URL: URL del servicio Node (por defecto http://127.0.0.1:11223).
- DJANGO_URL_INTERNA: URL de Django para que Node se comunique (por defecto http://127.0.0.1:7213).
- PUERTO_WHATSAPP: Puerto donde se ejecuta Node (por defecto 11223).

Proveedores de IA
- IA_PROVEEDOR_PRINCIPAL: Proveedor a utilizar (openai, gemini, claude).
- OPENAI_API_KEY, GEMINI_API_KEY, CLAUDE_API_KEY: Claves de API correspondientes a cada servicio activo.

---

## Ejecución en desarrollo

Para ejecutar la aplicación localmente, se requieren dos terminales en paralelo.

Terminal 1 (Django)
Activa el entorno virtual y ejecuta el servidor de desarrollo:
source .venv/bin/activate
python manage.py runserver

Terminal 2 (Node.js)
Inicia el servicio de WhatsApp:
cd servicio_whatsapp
node servidor.js

Una vez iniciados ambos servicios, ingresa a http://127.0.0.1:7213 desde el navegador web.

---

## Modelos de datos

Los datos se estructuran de la siguiente manera:

- Empresa: Representa la cuenta del usuario. Contiene instrucciones de IA y límites de consumo.
- SesionWhatsApp: Sesión vinculada a una empresa, guarda el identificador único y estado de la conexión.
- NodoBot: Representa un paso en el flujo de conversación (Menú, Texto, IA, Atención humana).
- OpcionNodo: Conexiones entre distintos nodos, permite definir la opción y archivo adjunto.
- SesionUsuario: Estado actual de la conversación con un número de teléfono específico.
- HistorialChat: Registro de los mensajes enviados por el usuario, asistente y agente.
- CicloFacturacion: Registro del uso mensual de respuestas generadas por IA.

---

## API interna Django y Node

La comunicación entre servicios requiere el header Authorization con el token configurado en WHATSAPP_INTERNAL_SECRET.

Endpoints de Django a Node:
- POST /api/sesiones/iniciar/: Inicializa o reconecta una sesión.
- POST /api/sesiones/{uuid}/mensajes/: Envía mensajes y adjuntos.
- POST /api/sesiones/{uuid}/desconectar/: Cierra la sesión activa.

Endpoints de Node a Django:
- POST /api/interno/whatsapp/evento/: Reporta estado y mensajes entrantes.
- GET /api/interno/whatsapp/sesiones/: Lista sesiones activas al iniciar.
- GET /api/interno/whatsapp/{uuid}/opciones/{id}/pdf/: Descarga archivos adjuntos a opciones.

---

## Flujo de un mensaje entrante

1. El cliente envía un mensaje por WhatsApp.
2. Node.js recibe el evento y notifica a Django mediante la API interna.
3. Django verifica si es una conversación nueva o existente.
4. Según la configuración, Django deriva la conversación a:
   - Una respuesta automática generada por IA.
   - El nodo inicial del flujo configurado.
   - Un operador humano, si la conversación se encuentra en ese estado.
5. El mensaje procesado se envía de vuelta a Node.js para ser entregado por WhatsApp.

---

## Tests

Las pruebas automatizadas se encuentran en el directorio testes/varios/ y cubren validación de modelos, formularios y flujos básicos. Para ejecutarlas:
python manage.py test testes

---

## Estructura del proyecto

El repositorio está organizado en los siguientes directorios principales:
- boti_project/: Configuración global de Django.
- core/: Aplicación central con modelos, vistas, lógica de conversaciones y panel web.
- servicio_whatsapp/: Código del servidor Node.js que maneja la sesión con WhatsApp Web.
- testes/: Conjunto de pruebas unitarias.

---

## Despliegue en producción

1. Configura una base de datos PostgreSQL y las variables correspondientes en el archivo .env.
2. Habilita el entorno de producción (DJANGO_DEBUG=0, DJANGO_FORZAR_HTTPS=1).
3. Asegura la instalación de Chromium en el servidor.
4. Aplica las migraciones (python manage.py migrate).
5. Sirve la aplicación Django utilizando Gunicorn o uWSGI junto con Nginx.
6. Ejecuta el servicio Node.js como un proceso administrado mediante systemd o PM2.
7. Comprueba la comunicación interna entre ambos servicios mediante el secreto compartido.

Es de suma importancia que la variable WHATSAPP_INTERNAL_SECRET sea segura y aleatoria.

---

## Licencia

Este proyecto está licenciado bajo la Licencia Pública General de GNU v3.0 (GPL-3.0). Consulta el archivo LICENSE para más detalles.
